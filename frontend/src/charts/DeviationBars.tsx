import type { BreakdownRow, Direction, Unit } from '../api'
import { DIMENSION_LABELS, changeIcon, changeMagnitude, changeTone, formatChange, formatValue } from '../format'

interface Props {
  rows: BreakdownRow[]
  unit: Unit
  direction: Direction
  limit: number
}

const TONE_FILL = { good: 'var(--div-good)', bad: 'var(--div-bad)', neutral: 'var(--axis)' } as const
const TONE_TEXT = { good: 'good', bad: 'bad', neutral: '' } as const

/** Diverging bars of the change vs the previous period. Blue = favourable, red = unfavourable
 *  (from the registry direction); every value is also printed, so colour never carries it alone. */
export function DeviationBars({ rows, unit, direction, limit }: Props) {
  const shown = rows.slice(0, limit)
  // Cap the scale so one tiny member with +900 % does not flatten all other bars.
  const maxAbs = Math.min(Math.max(...shown.map((r) => Math.abs(changeMagnitude(r, unit) ?? 0)), 1), 100)

  return (
    <div role="list">
      {shown.map((row) => {
        const pct = changeMagnitude(row, unit)
        const name = row.dimension_value === 'all' ? DIMENSION_LABELS.total : row.dimension_value
        const tone = changeTone(pct, direction)
        const share = pct === null ? 0 : (Math.min(Math.abs(pct), maxAbs) / maxAbs) * 50
        const negative = (pct ?? 0) < 0
        return (
          <div className="dev-row" role="listitem" key={row.entity_id}>
            <span className="dev-name" title={name}>
              {name}
            </span>
            <div className="dev-track" aria-hidden="true">
              <div className="dev-axis" />
              {share > 0 && (
                <div
                  className="dev-bar"
                  style={{
                    width: `${share}%`,
                    background: TONE_FILL[tone],
                    ...(negative
                      ? { right: '50%', borderRadius: '4px 0 0 4px' }
                      : { left: '50%', borderRadius: '0 4px 4px 0' }),
                  }}
                />
              )}
            </div>
            <span className="dev-values">
              <span className={`delta-text ${TONE_TEXT[tone]}`}>
                {changeIcon(pct)} {formatChange(row, unit)}
              </span>
              {' · '}
              {formatValue(row.current, unit, true)} <span className="muted">vorher {formatValue(row.previous, unit, true)}</span>
            </span>
          </div>
        )
      })}
    </div>
  )
}
