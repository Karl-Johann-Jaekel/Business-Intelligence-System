// Formatting driven purely by registry metadata (unit, direction). No KPI-specific code.

import type { Direction, Grain, Unit } from './api'

const LOCALE = 'de-DE'

export function formatValue(value: number | null | undefined, unit: Unit, compact = false): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '–'
  const notation = compact ? 'compact' : 'standard'
  switch (unit) {
    case 'BRL':
      return new Intl.NumberFormat(LOCALE, {
        style: 'currency',
        currency: 'BRL',
        notation,
        maximumFractionDigits: compact ? 1 : 2,
      }).format(value)
    case 'count':
      // Averages of counts (e.g. items per order) are not integers; keep their decimals.
      return new Intl.NumberFormat(LOCALE, {
        notation,
        maximumFractionDigits: compact || Number.isInteger(value) ? 1 : 2,
      }).format(value)
    case 'ratio':
      return new Intl.NumberFormat(LOCALE, {
        style: 'percent',
        minimumFractionDigits: 1,
        maximumFractionDigits: Math.abs(value) < 0.1 ? 2 : 1,
      }).format(value)
    case 'multiple':
      return `${new Intl.NumberFormat(LOCALE, { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(value)}×`
    case 'days':
      return `${new Intl.NumberFormat(LOCALE, { maximumFractionDigits: 1 }).format(value)} Tage`
    case 'score':
      return new Intl.NumberFormat(LOCALE, { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(value)
  }
}

export function formatPct(pct: number | null | undefined, suffix = '%', digits = 1): string {
  if (pct === null || pct === undefined) return '–'
  // Sign follows the displayed (rounded) value, so a tiny change never reads as "−0".
  const rounded = Number(pct.toFixed(digits))
  const sign = rounded > 0 ? '+' : rounded < 0 ? '−' : '±'
  return `${sign}${new Intl.NumberFormat(LOCALE, { maximumFractionDigits: digits }).format(Math.abs(rounded))} ${suffix}`
}

export interface Change {
  change_abs: number | null
  change_pct: number | null
}

/** Size of a change in the unit readers expect: percentage points for ratios
 *  (a relative change of a rate is misleading), percent otherwise. */
export function changeMagnitude(change: Change | undefined, unit: Unit): number | null {
  if (!change) return null
  if (unit === 'ratio') return change.change_abs === null ? null : change.change_abs * 100
  return change.change_pct
}

export function formatChange(change: Change | undefined, unit: Unit): string {
  const value = changeMagnitude(change, unit)
  return unit === 'ratio' ? formatPct(value, 'pp', 2) : formatPct(value)
}

/** Arrow for the sign of a change; favourability is carried by colour + text, not the arrow. */
export function changeIcon(change: number | null | undefined): string {
  if (change === null || change === undefined || change === 0) return '•'
  return change > 0 ? '▲' : '▼'
}

export type Tone = 'good' | 'bad' | 'neutral'

/** Whether a change is favourable, given the KPI's direction from the registry. */
export function changeTone(change: number | null | undefined, direction: Direction): Tone {
  if (change === null || change === undefined || change === 0 || direction === 'neutral') return 'neutral'
  const up = change > 0
  return up === (direction === 'higher_is_better') ? 'good' : 'bad'
}

export function formatDate(iso: string, grain: Grain = 'day'): string {
  const d = new Date(`${iso}T00:00:00`)
  return grain === 'month'
    ? d.toLocaleDateString(LOCALE, { month: 'short', year: 'numeric' })
    : d.toLocaleDateString(LOCALE, { day: '2-digit', month: '2-digit', year: 'numeric' })
}

export function formatShortDate(iso: string, grain: Grain = 'day'): string {
  const d = new Date(`${iso}T00:00:00`)
  return grain === 'month'
    ? d.toLocaleDateString(LOCALE, { month: 'short', year: '2-digit' })
    : d.toLocaleDateString(LOCALE, { day: '2-digit', month: 'short' })
}

export const DIMENSION_LABELS: Record<string, string> = {
  total: 'Gesamt',
  region: 'Region',
  category: 'Kategorie',
}

export const UNIT_LABELS: Record<Unit, string> = {
  BRL: 'BRL',
  count: 'Anzahl',
  ratio: 'Quote',
  multiple: 'Faktor',
  days: 'Tage',
  score: 'Bewertung',
}

export const DIRECTION_LABELS: Record<Direction, string> = {
  higher_is_better: 'höher ist besser',
  lower_is_better: 'niedriger ist besser',
  neutral: 'neutral',
}
