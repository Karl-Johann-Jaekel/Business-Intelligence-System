import { useCallback, useEffect, useMemo, useState } from 'react'
import type { Health, Kpi, Me, Window } from './api'
import { AdminPage } from './components/AdminPage'
import { BriefingPanel } from './components/BriefingPanel'
import { FilterBar } from './components/FilterBar'
import { InsightsPanel } from './components/InsightsPanel'
import { KpiCard } from './components/KpiCard'
import { KpiDetail } from './components/KpiDetail'
import { PRESETS, presetWindow, readUrlState, writeUrlState } from './dates'
import { formatDate } from './format'
import { authEnabled, currentSession, logout, userName } from './auth'
import { useApi } from './useApi'

const HEALTH_LABEL: Record<Health['status'], { text: string; color: string }> = {
  ok: { text: 'Daten aktuell', color: 'var(--status-good)' },
  stale: { text: 'Daten veraltet', color: 'var(--status-warning)' },
  down: { text: 'Warehouse nicht erreichbar', color: 'var(--status-critical)' },
}

type View = 'dashboard' | 'admin'

function initialView(): View {
  return new URLSearchParams(window.location.search).get('view') === 'admin' ? 'admin' : 'dashboard'
}

export default function App() {
  const registry = useApi<Kpi[]>('/kpis')
  const health = useApi<Health>('/health')
  const me = useApi<Me>('/me')
  const isAdmin = me.data?.admin ?? false
  const guest = currentSession() === 'guest'
  const [view, setView] = useState<View>(initialView)

  const simDate = health.data?.sim_date ?? null

  // Filters live in the URL so a view can be shared or bookmarked.
  const [initial] = useState(() => readUrlState())
  const [presetId, setPresetId] = useState(initial.presetId)
  const [custom, setCustom] = useState<Window | null>(initial.custom)
  const [selectedKey, setSelectedKey] = useState<string | null>(initial.kpi)
  const [dimension, setDimension] = useState(initial.dim)

  useEffect(() => {
    writeUrlState({ presetId, custom, kpi: selectedKey, dim: dimension })
    // The view is not part of the filter state; add it after the filters were written.
    if (view === 'admin') {
      const url = new URL(globalThis.location.href)
      url.searchParams.set('view', 'admin')
      globalThis.history.replaceState(null, '', url)
    }
  }, [presetId, custom, selectedKey, dimension, view])

  const window = useMemo<Window | null>(() => {
    if (custom) return custom
    if (!simDate) return null
    return presetWindow(simDate, PRESETS.find((p) => p.id === presetId)?.days ?? 90)
  }, [custom, simDate, presetId])

  const kpis = registry.data ?? []
  const selected = kpis.find((k) => k.key === selectedKey) ?? kpis[0]
  // A dimension the selected KPI does not offer falls back to the total.
  const activeDimension = selected?.dimensions.includes(dimension) ? dimension : 'total'

  const onPreset = useCallback((id: string) => {
    setPresetId(id)
    setCustom(null)
  }, [])
  const onOpenInsight = useCallback((kpi: string, dim: string) => {
    setSelectedKey(kpi)
    setDimension(dim)
    document.getElementById('detail-title')?.scrollIntoView({ behavior: 'smooth' })
  }, [])
  const onCustom = useCallback((w: Window) => {
    setPresetId('custom')
    setCustom(w)
  }, [])

  const status = health.data?.status ?? (health.error ? 'down' : null)

  return (
    <main className="app">
      <header className="header">
        <h1>Business-Intelligence-System</h1>
        {status && (
          <span className="health" role="status">
            <span className="dot" style={{ background: HEALTH_LABEL[status].color }} aria-hidden="true" />
            {HEALTH_LABEL[status].text}
            {simDate && <span className="muted">· Simulationsdatum {formatDate(simDate)}</span>}
          </span>
        )}
        {isAdmin && (
          <nav className="segmented" aria-label="Bereich">
            <button type="button" aria-pressed={view === 'dashboard'} onClick={() => setView('dashboard')}>
              Dashboard
            </button>
            <button type="button" aria-pressed={view === 'admin'} onClick={() => setView('admin')}>
              Admin
            </button>
          </nav>
        )}
        {authEnabled && (
          <span className="user">
            {guest && <span className="badge">Gastzugang · nur lesen</span>} {userName()}{' '}
            <button type="button" className="link-button" onClick={() => void logout()}>
              {guest ? 'Beenden' : 'Abmelden'}
            </button>
          </span>
        )}
      </header>

      {view === 'admin' && isAdmin && <AdminPage />}

      {registry.error && <p className="error">KPI-Registry nicht ladbar: {registry.error}</p>}
      {health.error && !registry.error && <p className="error">Status nicht ladbar: {health.error}</p>}
      {(registry.loading || health.loading) && !window && <p className="muted">Lade …</p>}

      {view === 'dashboard' && window && simDate && selected && (
        <>
          <BriefingPanel />
          <FilterBar
            presetId={presetId}
            onPreset={onPreset}
            window={window}
            onCustom={onCustom}
            maxDate={simDate}
            dimensions={selected.dimensions}
            dimension={activeDimension}
            onDimension={setDimension}
          />
          <InsightsPanel window={window} kpis={kpis} onOpen={onOpenInsight} />
          <section className="grid" aria-label="Kennzahlen">
            {kpis.map((kpi) => (
              <KpiCard
                key={kpi.key}
                kpi={kpi}
                window={window}
                selected={kpi.key === selected.key}
                onSelect={setSelectedKey}
              />
            ))}
          </section>
          <KpiDetail kpi={selected} window={window} dimension={activeDimension} />
        </>
      )}
    </main>
  )
}
