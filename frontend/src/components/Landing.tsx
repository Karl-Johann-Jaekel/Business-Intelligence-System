import { useEffect, useRef, useState } from 'react'
import type { GuestConfig } from '../api'
import { authEnabled, continueAsGuest, login } from '../auth'

// Cloudflare Turnstile, loaded only on this page (explicit rendering).
interface Turnstile {
  render: (
    element: HTMLElement,
    options: {
      sitekey: string
      callback: (token: string) => void
      'error-callback': () => void
      'expired-callback': () => void
      theme: 'auto'
      language: string
    },
  ) => string
  reset: (widgetId: string) => void
}

declare global {
  interface Window {
    turnstile?: Turnstile
  }
}

const TURNSTILE_SRC = 'https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit'
const REPO_URL = import.meta.env.VITE_REPO_URL ?? ''

function loadTurnstile(): Promise<Turnstile> {
  if (window.turnstile) return Promise.resolve(window.turnstile)
  return new Promise((resolve, reject) => {
    const script = document.createElement('script')
    script.src = TURNSTILE_SRC
    script.async = true
    script.onload = () => (window.turnstile ? resolve(window.turnstile) : reject(new Error('Turnstile fehlt')))
    script.onerror = () => reject(new Error('Captcha konnte nicht geladen werden'))
    document.head.appendChild(script)
  })
}

type GuestState =
  | { phase: 'loading' }
  | { phase: 'disabled' }
  | { phase: 'challenge'; siteKey: string }
  | { phase: 'entering' }
  | { phase: 'error'; message: string; siteKey: string | null }

function GuestEntry({ onEntered }: { onEntered: () => void }) {
  const [state, setState] = useState<GuestState>({ phase: 'loading' })
  const widget = useRef<HTMLDivElement>(null)
  const widgetId = useRef<string | null>(null)

  useEffect(() => {
    let cancelled = false
    fetch('/api/v1/guest/config')
      .then((r) => (r.ok ? (r.json() as Promise<GuestConfig>) : Promise.reject(new Error(r.statusText))))
      .then((config) => {
        if (cancelled) return
        setState(config.enabled && config.site_key ? { phase: 'challenge', siteKey: config.site_key } : { phase: 'disabled' })
      })
      .catch(() => !cancelled && setState({ phase: 'error', message: 'Gastzugang gerade nicht erreichbar.', siteKey: null }))
    return () => {
      cancelled = true
    }
  }, [])

  const siteKey = state.phase === 'challenge' ? state.siteKey : null
  useEffect(() => {
    if (!siteKey || !widget.current || widgetId.current) return
    const element = widget.current
    loadTurnstile()
      .then((turnstile) => {
        widgetId.current = turnstile.render(element, {
          sitekey: siteKey,
          theme: 'auto',
          language: 'de',
          callback: (token) => {
            setState({ phase: 'entering' })
            continueAsGuest(token)
              .then(onEntered)
              .catch((err: Error) => setState({ phase: 'error', message: err.message, siteKey }))
          },
          'error-callback': () => setState({ phase: 'error', message: 'Captcha fehlgeschlagen.', siteKey }),
          'expired-callback': () => {
            if (widgetId.current) turnstile.reset(widgetId.current)
          },
        })
      })
      .catch((err: Error) => setState({ phase: 'error', message: err.message, siteKey }))
  }, [siteKey, onEntered])

  if (state.phase === 'loading') return <p className="muted">Gastzugang wird vorbereitet …</p>
  if (state.phase === 'disabled') return <p className="muted">Der Gastzugang ist derzeit geschlossen.</p>
  return (
    <div className="guest-entry">
      <p className="secondary">
        Ohne Konto, nur lesend, für zwei Stunden. Eine kurze Prüfung von Cloudflare schützt vor Bots.
      </p>
      {state.phase === 'entering' && <p className="muted">Gastzugang wird geöffnet …</p>}
      {state.phase === 'error' && (
        <p className="error" role="alert">
          {state.message}{' '}
          {state.siteKey && (
            <button
              type="button"
              className="link-button"
              onClick={() => {
                widgetId.current = null
                setState({ phase: 'challenge', siteKey: state.siteKey! })
              }}
            >
              Erneut versuchen
            </button>
          )}
        </p>
      )}
      <div ref={widget} className="turnstile" aria-label="Sicherheitsprüfung" />
    </div>
  )
}

export function Landing({ onEntered }: { onEntered: () => void }) {
  const [entering, setEntering] = useState(false)

  return (
    <main className="app landing">
      <header className="landing-hero">
        <p className="eyebrow">Portfolio-Projekt · Agentic BI</p>
        <h1>Business-Intelligence-System</h1>
        <p className="lead">
          Ein Unternehmen, das jeden Tag einen Tag älter wird: echte Bestellungen eines Onlinehändlers,
          Kennzahlen, erkannte Auffälligkeiten und ein KI-Briefing mit belegten Zahlen. Darauf wächst ein
          Agentensystem, das Auffälligkeiten priorisiert und Fachbereichs-Agenten mit der Ursachensuche beauftragt.
        </p>
      </header>

      <section className="entry" aria-label="Zugang">
        <div className="panel entry-card">
          <h2>Als Gast fortfahren</h2>
          {entering ? (
            <GuestEntry onEntered={onEntered} />
          ) : (
            <>
              <p className="secondary">Alle Bereiche ansehen, ohne Anmeldung.</p>
              <button type="button" className="primary" onClick={() => setEntering(true)}>
                Als Gast fortfahren
              </button>
            </>
          )}
        </div>
        {authEnabled && (
          <div className="panel entry-card">
            <h2>Anmelden</h2>
            <p className="secondary">Für Inhaber und eingeladene Konten. Admins melden sich mit zweitem Faktor an.</p>
            <button type="button" onClick={() => void login()}>
              Anmelden
            </button>
          </div>
        )}
      </section>

      <section className="facts" aria-label="Über das Projekt">
        <div>
          <h2>Was echt ist</h2>
          <p className="secondary">
            Bestellungen, Zahlungen, Lieferungen und Bewertungen stammen aus dem öffentlichen Olist-Datensatz
            (Brasilien, 2016–2018) und werden über eine Simulationsuhr Tag für Tag nachgespielt.
          </p>
        </div>
        <div>
          <h2>Was simuliert ist</h2>
          <p className="secondary">
            Marketing, Budgets und künftig alle weiteren Unternehmensbereiche entstehen aus einem kausalen Modell,
            das an die echten Zahlen gekoppelt ist. Die Oberfläche kennzeichnet die Herkunft jeder Kennzahl.
          </p>
        </div>
        <div>
          <h2>Wie es gebaut ist</h2>
          <p className="secondary">
            Postgres, dbt und Dagster für die Daten, FastAPI und React für Portal und API, statistische
            Anomalieerkennung, ein KI-Briefing über Mistral mit Zahlen-Leitplanke und ein MCP-Server für Claude.
          </p>
        </div>
      </section>

      <footer className="landing-footer muted">
        Gastzugänge brauchen kein Konto. Die Sicherheitsprüfung übernimmt Cloudflare Turnstile; Details stehen in
        der Datenschutzerklärung der Portfolioseite.
        {REPO_URL && (
          <>
            {' '}
            <a href={REPO_URL}>Quellcode</a>
          </>
        )}
      </footer>
    </main>
  )
}
