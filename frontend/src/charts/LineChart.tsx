import { useLayoutEffect, useMemo, useRef, useState, type KeyboardEvent, type PointerEvent } from 'react'
import type { Grain, Point, Unit } from '../api'
import { formatDate, formatShortDate, formatValue } from '../format'
import { linear, niceTicks, pickEvery } from './scale'

export interface ChartSeries {
  id: string
  name: string
  color: string
  points: Point[]
}

/** A flagged data point (e.g. a detected anomaly), drawn as a ring in a status colour. */
export interface ChartMarker {
  period: string
  seriesId: string
  label: string
  color: string
}

interface Props {
  series: ChartSeries[]
  markers?: ChartMarker[]
  unit: Unit
  grain: Grain
  height?: number
  label: string
}

const MARGIN = { top: 8, right: 12, bottom: 24, left: 72 }

function useWidth<T extends HTMLElement>() {
  const ref = useRef<T>(null)
  const [width, setWidth] = useState(600)
  useLayoutEffect(() => {
    if (!ref.current) return
    const observer = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width))
    observer.observe(ref.current)
    return () => observer.disconnect()
  }, [])
  return [ref, width] as const
}

/** Multi-series line chart: 2px lines, hairline grid, crosshair + one tooltip for all series. */
export function LineChart({ series, markers = [], unit, grain, height = 260, label }: Props) {
  const [containerRef, width] = useWidth<HTMLDivElement>()
  const [hover, setHover] = useState<number | null>(null)

  const periods = useMemo(
    () => [...new Set(series.flatMap((s) => s.points.map((p) => p.period)))].sort(),
    [series],
  )
  const lookup = useMemo(
    () => series.map((s) => new Map(s.points.map((p) => [p.period, p.value]))),
    [series],
  )
  const values = series.flatMap((s) => s.points.map((p) => p.value)).filter((v): v is number => v !== null)
  const ticks = niceTicks(Math.min(0, ...values), Math.max(0, ...values))

  const innerW = Math.max(width - MARGIN.left - MARGIN.right, 10)
  const innerH = height - MARGIN.top - MARGIN.bottom
  const x = linear([0, Math.max(periods.length - 1, 1)], [0, innerW])
  const y = linear([ticks[0], ticks[ticks.length - 1]], [innerH, 0])

  const paths = series.map((_, si) => {
    let d = ''
    let pen = false
    periods.forEach((period, i) => {
      const v = lookup[si].get(period)
      if (v === null || v === undefined) {
        pen = false
        return
      }
      d += `${pen ? 'L' : 'M'}${x(i).toFixed(1)},${y(v).toFixed(1)}`
      pen = true
    })
    return d
  })

  function onPointerMove(event: PointerEvent<SVGRectElement>) {
    const rect = event.currentTarget.getBoundingClientRect()
    const index = Math.round(((event.clientX - rect.left) / rect.width) * (periods.length - 1))
    setHover(Math.min(Math.max(index, 0), periods.length - 1))
  }

  function onKeyDown(event: KeyboardEvent<SVGSVGElement>) {
    if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return
    event.preventDefault()
    const delta = event.key === 'ArrowLeft' ? -1 : 1
    setHover((h) => Math.min(Math.max((h ?? periods.length - 1) + delta, 0), periods.length - 1))
  }

  // Keep the measured container mounted even when empty, so the ResizeObserver stays attached.
  if (periods.length === 0)
    return (
      <div className="chart" ref={containerRef}>
        <p className="muted">Keine Daten im gewählten Zeitraum.</p>
      </div>
    )

  const hoverPeriod = hover !== null ? periods[hover] : null
  const tooltipRows =
    hoverPeriod === null
      ? []
      : series
          .map((s, si) => ({ s, v: lookup[si].get(hoverPeriod) ?? null }))
          .sort((a, b) => (b.v ?? -Infinity) - (a.v ?? -Infinity))
  const tooltipLeft = hover !== null ? MARGIN.left + x(hover) : 0
  const flip = tooltipLeft > width * 0.6

  return (
    <div className="chart" ref={containerRef}>
      {series.length >= 2 && (
        <ul className="legend" aria-label="Legende">
          {series.map((s) => (
            <li key={s.id}>
              <span className="key" style={{ background: s.color }} />
              {s.name}
            </li>
          ))}
        </ul>
      )}
      <svg
        height={height}
        role="img"
        aria-label={label}
        tabIndex={0}
        onKeyDown={onKeyDown}
        onBlur={() => setHover(null)}
      >
        <g transform={`translate(${MARGIN.left},${MARGIN.top})`}>
          {ticks.map((t) => (
            <g key={t}>
              <line x1={0} x2={innerW} y1={y(t)} y2={y(t)} stroke={t === 0 ? 'var(--axis)' : 'var(--grid)'} />
              <text className="tick" x={-8} y={y(t)} dy="0.32em" textAnchor="end">
                {formatValue(t, unit, true)}
              </text>
            </g>
          ))}
          {pickEvery(
            periods.map((p, i) => ({ p, i })),
            Math.max(2, Math.floor(innerW / 80)),
          ).map(({ p, i }) => (
            <text key={p} className="tick" x={x(i)} y={innerH + 16} textAnchor="middle">
              {formatShortDate(p, grain)}
            </text>
          ))}
          {paths.map((d, si) => (
            <path
              key={series[si].id}
              d={d}
              fill="none"
              stroke={series[si].color}
              strokeWidth={2}
              strokeLinejoin="round"
              strokeLinecap="round"
            />
          ))}
          {markers.map((m) => {
            const si = series.findIndex((s) => s.id === m.seriesId)
            const i = periods.indexOf(m.period)
            const v = si >= 0 && i >= 0 ? lookup[si].get(m.period) : null
            if (v === null || v === undefined) return null
            return (
              <circle
                key={`${m.seriesId}-${m.period}`}
                cx={x(i)}
                cy={y(v)}
                r={6}
                fill="var(--surface-1)"
                stroke={m.color}
                strokeWidth={2.5}
              />
            )
          })}
          {hover !== null && (
            <g>
              <line x1={x(hover)} x2={x(hover)} y1={0} y2={innerH} stroke="var(--axis)" />
              {tooltipRows.map(({ s, v }) =>
                v === null ? null : (
                  <circle
                    key={s.id}
                    cx={x(hover)}
                    cy={y(v)}
                    r={4}
                    fill={s.color}
                    stroke="var(--surface-1)"
                    strokeWidth={2}
                  />
                ),
              )}
            </g>
          )}
          <rect
            width={innerW}
            height={innerH}
            fill="transparent"
            onPointerMove={onPointerMove}
            onPointerLeave={() => setHover(null)}
          />
        </g>
      </svg>
      {hoverPeriod !== null && (
        <div
          className="tooltip"
          style={{
            top: MARGIN.top + (series.length >= 2 ? 28 : 0),
            left: flip ? undefined : tooltipLeft + 12,
            right: flip ? width - tooltipLeft + 12 : undefined,
          }}
        >
          <div className="when">{formatDate(hoverPeriod, grain)}</div>
          {tooltipRows.map(({ s, v }) => (
            <div className="row" key={s.id}>
              <span className="key" style={{ background: s.color }} />
              <strong>{formatValue(v, unit)}</strong>
              {series.length >= 2 && <span className="secondary">{s.name}</span>}
            </div>
          ))}
          {markers
            .filter((m) => m.period === hoverPeriod)
            .map((m) => (
              <div className="row" key={`m-${m.seriesId}`} style={{ marginTop: 4 }}>
                <span aria-hidden="true" style={{ color: m.color }}>
                  ●
                </span>
                <span>{m.label}</span>
              </div>
            ))}
        </div>
      )}
    </div>
  )
}
