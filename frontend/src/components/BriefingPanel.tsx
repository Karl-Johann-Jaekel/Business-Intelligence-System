import type { Insight } from '../api'
import { formatDate } from '../format'
import { useApi } from '../useApi'

/** Latest AI analyst briefing. Every number in it passed the server-side number guardrail. */
export function BriefingPanel() {
  const briefing = useApi<Insight>('/briefings/latest')
  const content = briefing.data?.details?.briefing

  if (briefing.error?.startsWith('404')) {
    return (
      <section className="panel" aria-labelledby="briefing-title">
        <h2 id="briefing-title">Tagesbriefing</h2>
        <p className="muted" style={{ margin: 0 }}>
          Noch kein Briefing. Der AI-Analyst braucht konfigurierte LLM-Zugangsdaten.
        </p>
      </section>
    )
  }
  if (!briefing.data || !content) return null

  return (
    <section className="panel" aria-labelledby="briefing-title">
      <div className="panel-head">
        <h2 id="briefing-title">Tagesbriefing {formatDate(briefing.data.period.end)}</h2>
        <span className="badge" title="Jede Zahl wurde gegen die berechneten Kennzahlen geprüft">
          KI-generiert · Zahlen geprüft
        </span>
      </div>
      <p style={{ marginTop: 0 }}>{content.summary}</p>
      <h3>Befunde</h3>
      <ul>
        {content.findings.map((f, i) => (
          <li key={i}>
            {f.text} <span className="muted">({f.evidence_ref})</span>
          </li>
        ))}
      </ul>
      <h3>Handlungsvorschläge</h3>
      <ul style={{ marginBottom: 0 }}>
        {content.actions.map((a, i) => (
          <li key={i}>{a}</li>
        ))}
      </ul>
    </section>
  )
}
