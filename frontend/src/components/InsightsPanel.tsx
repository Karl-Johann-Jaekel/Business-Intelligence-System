import { useState } from 'react'
import { insightScope, type Insight, type Kpi, type Window } from '../api'
import { DIMENSION_LABELS, formatDate } from '../format'
import { useApi } from '../useApi'
import { SEVERITY } from './severity'

interface Props {
  window: Window
  kpis: Kpi[]
  onOpen: (kpi: string, dimension: string) => void
}

const LIMIT = 6

export function InsightsPanel({ window, kpis, onOpen }: Props) {
  const insights = useApi<Insight[]>('/insights', { since: window.start, type: 'anomaly', severity: 'warning', limit: 200 })
  const [showAll, setShowAll] = useState(false)
  const labels = new Map(kpis.map((k) => [k.key, k.label]))
  const rows = (insights.data ?? []).filter((i) => i.period.end <= window.end)
  const shown = showAll ? rows : rows.slice(0, LIMIT)

  return (
    <section className={`panel${insights.loading ? ' loading' : ''}`} aria-labelledby="insights-title">
      <div className="panel-head">
        <h2 id="insights-title">Auffälligkeiten</h2>
        <span className="muted">
          {rows.length} im Zeitraum · erkannt mit den Regeln der KPI-Registry
        </span>
      </div>
      {insights.error && <p className="error">Fehler: {insights.error}</p>}
      {!insights.error && rows.length === 0 && !insights.loading && (
        <p className="muted">Keine Auffälligkeiten im gewählten Zeitraum.</p>
      )}
      <ul className="insight-list">
        {shown.map((insight) => {
          const sev = SEVERITY[insight.severity]
          const scope = insightScope(insight)
          return (
            <li key={insight.insight_id}>
              <span className="sev" style={{ color: sev.color }}>
                <span aria-hidden="true">{sev.icon}</span> {sev.label}
              </span>
              <span className="when">{formatDate(insight.period.end, insight.period.grain)}</span>
              <span className="what">
                <strong>{labels.get(insight.kpi ?? '') ?? insight.kpi}</strong>
                {scope.dimension !== 'total' && (
                  <span className="secondary">
                    {' '}
                    · {DIMENSION_LABELS[scope.dimension] ?? scope.dimension} {scope.member}
                  </span>
                )}
                <span className="secondary"> — {insight.summary}</span>
              </span>
              {insight.kpi && (
                <button type="button" className="link-button" onClick={() => onOpen(insight.kpi!, scope.dimension)}>
                  Ansehen
                </button>
              )}
            </li>
          )
        })}
      </ul>
      {rows.length > LIMIT && (
        <button type="button" className="link-button" onClick={() => setShowAll((v) => !v)}>
          {showAll ? 'Weniger anzeigen' : `Alle ${rows.length} anzeigen`}
        </button>
      )}
    </section>
  )
}
