import type { Point } from '../api'
import { linear } from './scale'

/** Stat-tile trend: de-emphasised line, current period marked in the accent. */
export function Sparkline({ points, width = 180, height = 32 }: { points: Point[]; width?: number; height?: number }) {
  const valid = points.map((p, i) => ({ i, v: p.value })).filter((p): p is { i: number; v: number } => p.v !== null)
  if (valid.length < 2) return <svg width="100%" height={height} aria-hidden="true" />
  const values = valid.map((p) => p.v)
  const x = linear([0, points.length - 1], [2, width - 4])
  const y = linear([Math.min(...values), Math.max(...values)], [height - 4, 4])
  const d = valid.map((p, k) => `${k ? 'L' : 'M'}${x(p.i).toFixed(1)},${y(p.v).toFixed(1)}`).join('')
  const last = valid[valid.length - 1]
  const end = `M${x(last.i).toFixed(1)},${y(last.v).toFixed(1)}l0,0`
  return (
    <svg width="100%" height={height} viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" aria-hidden="true">
      <path d={d} fill="none" stroke="var(--text-muted)" strokeWidth={1.5} vectorEffect="non-scaling-stroke" />
      {/* Zero-length round-capped strokes stay circular although the viewBox is stretched. */}
      <path d={end} stroke="var(--surface-1)" strokeWidth={10} strokeLinecap="round" vectorEffect="non-scaling-stroke" />
      <path d={end} stroke="var(--series-1)" strokeWidth={7} strokeLinecap="round" vectorEffect="non-scaling-stroke" />
    </svg>
  )
}
