import type { Severity } from '../api'

/** Status is never colour alone: icon + label + colour (dataviz status rule). */
export const SEVERITY: Record<Severity, { icon: string; label: string; color: string }> = {
  critical: { icon: '⛔', label: 'Kritisch', color: 'var(--status-critical)' },
  warning: { icon: '⚠', label: 'Warnung', color: 'var(--status-warning)' },
  info: { icon: 'ℹ', label: 'Info', color: 'var(--text-muted)' },
}
