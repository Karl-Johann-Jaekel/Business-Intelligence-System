// Typed client for the BIS API v1. Shapes mirror api/main.py response models.

import { accessToken, authEnabled, sessionExpired } from './auth'

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
  const token = accessToken()
  const response = await fetch(url, { signal, headers: token ? { Authorization: `Bearer ${token}` } : {} })
  if (response.status === 401 && authEnabled) sessionExpired()
  const body = await response.json().catch(() => ({}))
  if (!response.ok) {
    const detail = typeof body.detail === 'string' ? body.detail : response.statusText
    throw new Error(`${response.status}: ${detail}`)
  }
  return body as T
}

/** GET /me: who the portal talks to. */
export interface Me {
  subject: string
  username: string | null
  guest: boolean
  admin: boolean
  scopes: string[]
}

/** GET /guest/config (open): whether guest mode is on and the public Turnstile site key. */
export interface GuestConfig {
  enabled: boolean
  site_key: string
}

export interface UsageRow {
  day: string
  purpose: string
  provider: string
  model: string
  calls: number
  tokens_in: number
  tokens_out: number
  cost_eur: number
}

/** GET /admin/usage (admin only). */
export interface Usage {
  days: number
  llm: UsageRow[]
  total_cost_eur: number
  total_tokens: number
  guests: { sessions_last_24h: number; sessions_last_hour: number } | null
}

export type Severity = 'info' | 'warning' | 'critical'

/** insight.v1 (see docs/company-brain-interface.md); only the fields the dashboard uses. */
export interface Insight {
  insight_id: string
  type: 'anomaly' | 'briefing' | 'forecast_deviation' | 'data_quality'
  kpi: string | null
  period: { start: string; end: string; grain: Grain }
  severity: Severity
  direction: 'up' | 'down' | null
  observed: number | null
  expected: number | null
  deviation_pct: number | null
  entity_refs: { type: string; id: string }[]
  evidence: { method: string; score?: number | null; model?: string }
  summary: string
  created_at: string
  details?: {
    briefing?: {
      summary: string
      findings: { text: string; kpi: string; evidence_ref: string }[]
      actions: string[]
    }
    attempts?: number
  } | null
}

/** Dimension and member an insight refers to (ignores the kpi:<key> reference). */
export function insightScope(insight: Insight): { dimension: string; member: string } {
  const ref = insight.entity_refs.find((r) => r.type !== 'kpi')
  if (!ref) return { dimension: 'total', member: 'all' }
  return { dimension: ref.type, member: ref.id.slice(ref.id.indexOf(':') + 1) }
}
