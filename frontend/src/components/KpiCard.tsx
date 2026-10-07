import { memo } from 'react'
import type { BreakdownResponse, Kpi, SeriesResponse, Window } from '../api'
import { Sparkline } from '../charts/Sparkline'
import { windowForGrain } from '../dates'
import { changeIcon, changeMagnitude, changeTone, formatChange, formatValue } from '../format'
import { useApi } from '../useApi'

interface Props {
  kpi: Kpi
  window: Window
  selected: boolean
  onSelect: (key: string) => void
}

/** Stat tile rendered only from registry metadata: label, unit, direction, grain, origin. */
export const KpiCard = memo(function KpiCard({ kpi, window, selected, onSelect }: Props) {
  const w = windowForGrain(window, kpi.grain)
  const params = { from: w.start, to: w.end }
  const breakdown = useApi<BreakdownResponse>(`/kpis/${kpi.key}/breakdown`, params)
  const series = useApi<SeriesResponse>(`/kpis/${kpi.key}/series`, params)

  const row = breakdown.data?.rows[0]
  const change = changeMagnitude(row, kpi.unit)
  const tone = changeTone(change, kpi.direction)
  const loading = breakdown.loading || series.loading

  return (
    <button
      type="button"
      className={`card${loading ? ' loading' : ''}`}
      aria-pressed={selected}
      onClick={() => onSelect(kpi.key)}
      title={kpi.description}
    >
      <span className="label">
        <span>{kpi.label}</span>
        {kpi.grain === 'month' && <span className="muted">monatlich</span>}
      </span>
      {breakdown.error ? (
        <span className="error">Fehler: {breakdown.error}</span>
      ) : (
        <>
          <span className="value">{formatValue(row?.current, kpi.unit, true)}</span>
          <span className="delta">
            <span className={tone === 'neutral' ? '' : tone}>
              {changeIcon(change)} {formatChange(row, kpi.unit)}
            </span>{' '}
            ggü. Vorperiode
          </span>
          <Sparkline points={series.data?.series[0]?.points ?? []} />
        </>
      )}
      {kpi.data_origin === 'partly_synthetic' && <span className="badge">teils synthetisch</span>}
    </button>
  )
})
