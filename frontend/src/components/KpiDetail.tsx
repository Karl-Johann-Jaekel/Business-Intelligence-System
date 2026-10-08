import { useMemo, useState } from 'react'
import { insightScope, type BreakdownResponse, type Insight, type Kpi, type SeriesResponse, type Window } from '../api'
import { DeviationBars } from '../charts/DeviationBars'
import { LineChart, type ChartMarker, type ChartSeries } from '../charts/LineChart'
import { windowForGrain } from '../dates'
import {
  DIMENSION_LABELS,
  DIRECTION_LABELS,
  UNIT_LABELS,
  formatDate,
  formatChange,
  formatValue,
} from '../format'
import { useApi } from '../useApi'
import { assignSlots } from './colors'
import { SEVERITY } from './severity'

interface Props {
  kpi: Kpi
  window: Window
  dimension: string
}

const DEVIATION_LIMIT = 12

export function KpiDetail({ kpi, window, dimension }: Props) {
  const w = windowForGrain(window, kpi.grain)
  const dim = dimension === 'total' ? undefined : dimension
  const params = { from: w.start, to: w.end, dim }
  const series = useApi<SeriesResponse>(`/kpis/${kpi.key}/series`, params)
  const breakdown = useApi<BreakdownResponse>(`/kpis/${kpi.key}/breakdown`, params)
  const insights = useApi<Insight[]>('/insights', { kpi: kpi.key, since: w.start, type: 'anomaly', limit: 500 })
  const [showTable, setShowTable] = useState(false)
  const [showAll, setShowAll] = useState(false)

  // Colour follows the entity: survivors keep their slot when the member set changes.
  // Slots are derived from the previous render's slots (React "store info from previous renders").
  const items = series.data?.series
  const idsKey = (items ?? []).map((s) => s.entity_id).join('|')
  const [slots, setSlots] = useState<{ key: string; map: Map<string, number> }>({ key: '', map: new Map() })
  if (slots.key !== idsKey) {
    setSlots({ key: idsKey, map: assignSlots(idsKey ? idsKey.split('|') : [], slots.map) })
  }
  const chartSeries: ChartSeries[] = useMemo(
    () =>
      (items ?? []).map((s) => ({
        id: s.entity_id,
        name: s.dimension_value === 'all' ? kpi.label : s.dimension_value,
        color: `var(--series-${(slots.map.get(s.entity_id) ?? 0) + 1})`,
        points: s.points,
      })),
    [items, slots.map, kpi.label],
  )

  // Anomalies of this KPI on the plotted series (same dimension), drawn as rings on the line.
  const markers: ChartMarker[] = useMemo(
    () =>
      (insights.data ?? []).flatMap((insight) => {
        const scope = insightScope(insight)
        if (scope.dimension !== dimension) return []
        const seriesId = scope.dimension === 'total' ? `kpi:${kpi.key}` : `${scope.dimension}:${scope.member}`
        const sev = SEVERITY[insight.severity]
        return [{ period: insight.period.start, seriesId, label: `${sev.icon} ${sev.label}: ${insight.summary}`, color: sev.color }]
      }),
    [insights.data, dimension, kpi.key],
  )

  const grainLabel = kpi.grain === 'month' ? 'Monat' : 'Tag'
  const dimLabel = DIMENSION_LABELS[dimension] ?? dimension
  const rows = breakdown.data?.rows ?? []

  return (
    <>
      <section className="panel" aria-labelledby="detail-title">
        <h2 id="detail-title">{kpi.label}</h2>
        <p className="secondary" style={{ margin: 0 }}>
          {kpi.description}
        </p>
        <ul className="meta">
          <li className="badge">Einheit: {UNIT_LABELS[kpi.unit]}</li>
          <li className="badge">{DIRECTION_LABELS[kpi.direction]}</li>
          <li className="badge">Granularität: {grainLabel}</li>
          <li className="badge">{kpi.data_origin === 'real' ? 'echte Daten' : 'teils synthetisch'}</li>
          <li className="badge">Owner: {kpi.owner}</li>
          <li className="badge">
            {kpi.alert ? `Überwachung: ${kpi.alert.method} (${kpi.alert.threshold})` : 'nicht überwacht'}
          </li>
        </ul>
      </section>

      <section className={`panel${series.loading ? ' loading' : ''}`} aria-labelledby="trend-title">
        <div className="panel-head">
          <h3 id="trend-title">
            Verlauf pro {grainLabel}
            {dim ? ` · Top ${chartSeries.length} nach ${dimLabel}` : ''}
          </h3>
          <button type="button" className="link-button" onClick={() => setShowTable((v) => !v)}>
            {showTable ? 'Diagramm anzeigen' : 'Tabelle anzeigen'}
          </button>
        </div>
        {series.error && <p className="error">Fehler: {series.error}</p>}
        {!series.error &&
          (showTable ? (
            <SeriesTable series={chartSeries} kpi={kpi} />
          ) : (
            <LineChart
              series={chartSeries}
              markers={markers}
              unit={kpi.unit}
              grain={kpi.grain}
              label={`${kpi.label}, Verlauf ${formatDate(w.start, kpi.grain)} bis ${formatDate(w.end, kpi.grain)}`}
            />
          ))}
      </section>

      <section className={`panel${breakdown.loading ? ' loading' : ''}`} aria-labelledby="dev-title">
        <div className="panel-head">
          <h3 id="dev-title">Abweichung zur Vorperiode{dim ? ` nach ${dimLabel}` : ''}</h3>
          {breakdown.data && (
            <span className="muted">
              {formatDate(breakdown.data.current_window.start, kpi.grain)} –{' '}
              {formatDate(breakdown.data.current_window.end, kpi.grain)} vs.{' '}
              {formatDate(breakdown.data.previous_window.start, kpi.grain)} –{' '}
              {formatDate(breakdown.data.previous_window.end, kpi.grain)}
            </span>
          )}
        </div>
        {breakdown.error && <p className="error">Fehler: {breakdown.error}</p>}
        {!breakdown.error && rows.length === 0 && !breakdown.loading && (
          <p className="muted">Keine Daten im gewählten Zeitraum.</p>
        )}
        {rows.length > 0 && (
          <>
            <DeviationBars
              rows={rows}
              unit={kpi.unit}
              direction={kpi.direction}
              limit={showAll ? rows.length : DEVIATION_LIMIT}
            />
            {rows.length > DEVIATION_LIMIT && (
              <button type="button" className="link-button" onClick={() => setShowAll((v) => !v)}>
                {showAll ? 'Weniger anzeigen' : `Alle ${rows.length} anzeigen`}
              </button>
            )}
            {!dim && kpi.dimensions.length > 0 && (
              <p className="muted">Dimension in der Filterzeile wählen, um die Abweichung aufzuschlüsseln.</p>
            )}
            <p className="muted" style={{ marginBottom: 0 }}>
              Blau = günstige, Rot = ungünstige Entwicklung ({DIRECTION_LABELS[kpi.direction]}).
              {dim && rows[0]?.change_pct !== null && ` Größte Änderung: ${rows[0].dimension_value} ${formatChange(rows[0], kpi.unit)}.`}
            </p>
          </>
        )}
      </section>
    </>
  )
}

function SeriesTable({ series, kpi }: { series: ChartSeries[]; kpi: Kpi }) {
  const periods = [...new Set(series.flatMap((s) => s.points.map((p) => p.period)))].sort().reverse()
  const lookups = series.map((s) => new Map(s.points.map((p) => [p.period, p.value])))
  return (
    <div className="table-scroll">
      <table>
        <thead>
          <tr>
            <th scope="col">{kpi.grain === 'month' ? 'Monat' : 'Datum'}</th>
            {series.map((s) => (
              <th scope="col" key={s.id}>
                {s.name}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {periods.map((p) => (
            <tr key={p}>
              <td>{formatDate(p, kpi.grain)}</td>
              {lookups.map((lookup, i) => (
                <td key={series[i].id}>{formatValue(lookup.get(p), kpi.unit)}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
