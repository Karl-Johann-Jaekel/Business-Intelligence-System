import type { Grain, Window } from './api'

export interface RangePreset {
  id: string
  label: string
  days: number
}

export const PRESETS: RangePreset[] = [
  { id: '7d', label: 'Letzte 7 Tage', days: 7 },
  { id: '30d', label: 'Letzte 30 Tage', days: 30 },
  { id: '90d', label: 'Letzte 90 Tage', days: 90 },
  { id: '365d', label: 'Letzte 12 Monate', days: 365 },
]

export function toIso(d: Date): string {
  return d.toISOString().slice(0, 10)
}

export function addDays(iso: string, days: number): string {
  const d = new Date(`${iso}T00:00:00Z`)
  d.setUTCDate(d.getUTCDate() + days)
  return toIso(d)
}

export function presetWindow(simDate: string, days: number): Window {
  return { start: addDays(simDate, -(days - 1)), end: simDate }
}

/** Monthly KPIs are queried with the months that the day window touches. */
export function windowForGrain(window: Window, grain: Grain): Window {
  if (grain === 'day') return window
  return { start: `${window.start.slice(0, 7)}-01`, end: `${window.end.slice(0, 7)}-01` }
}

export interface UrlState {
  presetId: string
  custom: Window | null
  kpi: string | null
  dim: string
}

const ISO = /^\d{4}-\d{2}-\d{2}$/

/** Parse filters from the query string; unknown or malformed values fall back to defaults. */
export function parseUrlState(search: string): UrlState {
  const q = new URLSearchParams(search)
  const from = q.get('from')
  const to = q.get('to')
  const custom = from && to && ISO.test(from) && ISO.test(to) && from <= to ? { start: from, end: to } : null
  const range = q.get('range')
  return {
    presetId: custom ? 'custom' : PRESETS.some((p) => p.id === range) ? (range as string) : '90d',
    custom,
    kpi: q.get('kpi'),
    dim: q.get('dim') ?? 'total',
  }
}

export function serializeUrlState(state: UrlState): string {
  const q = new URLSearchParams()
  if (state.kpi) q.set('kpi', state.kpi)
  if (state.dim !== 'total') q.set('dim', state.dim)
  if (state.custom) {
    q.set('from', state.custom.start)
    q.set('to', state.custom.end)
  } else if (state.presetId !== '90d') {
    q.set('range', state.presetId)
  }
  const s = q.toString()
  return s ? `?${s}` : ''
}

export function readUrlState(): UrlState {
  return parseUrlState(globalThis.location?.search ?? '')
}

export function writeUrlState(state: UrlState): void {
  const search = serializeUrlState(state)
  if (search !== location.search) history.replaceState(null, '', `${location.pathname}${search}`)
}
