import type { Window } from '../api'
import { PRESETS } from '../dates'
import { DIMENSION_LABELS } from '../format'

interface Props {
  presetId: string
  onPreset: (id: string) => void
  window: Window
  onCustom: (window: Window) => void
  maxDate: string
  dimensions: string[]
  dimension: string
  onDimension: (dim: string) => void
}

/** One row above everything it scopes: date range first, then the dimension. */
export function FilterBar({ presetId, onPreset, window, onCustom, maxDate, dimensions, dimension, onDimension }: Props) {
  return (
    <div className="filters" role="toolbar" aria-label="Filter">
      <div className="segmented" role="group" aria-label="Zeitraum">
        {PRESETS.map((p) => (
          <button key={p.id} type="button" aria-pressed={presetId === p.id} onClick={() => onPreset(p.id)}>
            {p.label}
          </button>
        ))}
      </div>
      <label className="field">
        Von
        <input
          type="date"
          value={window.start}
          max={window.end}
          onChange={(e) => e.target.value && onCustom({ start: e.target.value, end: window.end })}
        />
      </label>
      <label className="field">
        Bis
        <input
          type="date"
          value={window.end}
          min={window.start}
          max={maxDate}
          onChange={(e) => e.target.value && onCustom({ start: window.start, end: e.target.value })}
        />
      </label>
      <label className="field">
        Dimension
        <select value={dimension} onChange={(e) => onDimension(e.target.value)}>
          {['total', ...dimensions].map((d) => (
            <option key={d} value={d}>
              {DIMENSION_LABELS[d] ?? d}
            </option>
          ))}
        </select>
      </label>
    </div>
  )
}
