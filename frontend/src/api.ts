// Typed client for the BIS API v1. Shapes mirror api/main.py response models.

export type Grain = 'day' | 'month'
export type Unit = 'BRL' | 'count' | 'ratio' | 'multiple' | 'days' | 'score'
export type Direction = 'higher_is_better' | 'lower_is_better' | 'neutral'

export interface Kpi {
  key: string
  label: string
  description: string
  source: string
  grain: Grain
  unit: Unit
  direction: Direction
  dimensions: string[]
  entity_type: string | null
  alert: { method: string; threshold: number; min_history_days: number | null } | null
  data_origin: 'real' | 'partly_synthetic'
  data_class: string
  owner: string
}

export interface Health {
  status: 'ok' | 'stale' | 'down'
  sim_date: string | null
  latest_kpi_date: string | null
  last_successful_load_at: string | null
  last_failed_load_at: string | null
  built_at: string | null
}

export interface Window {
  start: string
  end: string
}

export interface Point {
  period: string
  value: number | null
}

export interface SeriesItem {
  dimension_value: string
  entity_id: string
  points: Point[]
}

export interface SeriesResponse {
  kpi: string
  grain: Grain
  dimension: string
  window: Window
  series: SeriesItem[]
}

export interface BreakdownRow {
  dimension_value: string
  entity_id: string
  current: number | null
  previous: number | null
  change_abs: number | null
  change_pct: number | null
}

export interface BreakdownResponse {
  kpi: string
  grain: Grain
  dimension: string
  current_window: Window
  previous_window: Window
  rows: BreakdownRow[]
}

export type Params = Record<string, string | number | string[] | undefined | null>

export function buildUrl(path: string, params: Params = {}): string {
  const query = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === '') continue
    for (const v of Array.isArray(value) ? value : [value]) query.append(key, String(v))
  }
  const qs = query.toString()
  return `/api/v1${path}${qs ? `?${qs}` : ''}`
}

export async function getUrl<T>(url: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(url, { signal })
  const body = await response.json().catch(() => ({}))
  if (!response.ok) {
    const detail = typeof body.detail === 'string' ? body.detail : response.statusText
    throw new Error(`${response.status}: ${detail}`)
  }
  return body as T
}
