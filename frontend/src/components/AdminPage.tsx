import type { Usage } from '../api'
import { formatDate } from '../format'
import { useApi } from '../useApi'

const NUMBER = new Intl.NumberFormat('de-DE')
const EURO = new Intl.NumberFormat('de-DE', { style: 'currency', currency: 'EUR', maximumFractionDigits: 4 })

/** Admin area (A1): LLM usage and guest sessions. Simulation control follows with phase A2. */
export function AdminPage() {
  const usage = useApi<Usage>('/admin/usage', { days: 30 })

  return (
    <section className="panel" aria-labelledby="admin-title">
      <div className="panel-head">
        <h2 id="admin-title">Admin</h2>
        <span className="muted">letzte 30 Tage</span>
      </div>

      {usage.loading && !usage.data && <p className="muted">Lade …</p>}
      {usage.error && <p className="error">Verbrauch nicht ladbar: {usage.error}</p>}

      {usage.data && (
        <>
          <div className="stats">
            <div className="stat">
              <span className="label">LLM-Kosten</span>
              <span className="value">{EURO.format(usage.data.total_cost_eur)}</span>
            </div>
            <div className="stat">
              <span className="label">Tokens</span>
              <span className="value">{NUMBER.format(usage.data.total_tokens)}</span>
            </div>
            <div className="stat">
              <span className="label">Gastzugänge (24 h)</span>
              <span className="value">
                {usage.data.guests ? NUMBER.format(usage.data.guests.sessions_last_24h) : 'aus'}
              </span>
            </div>
          </div>

          <h3>LLM-Aufrufe des BI-Systems</h3>
          {usage.data.llm.length === 0 ? (
            <p className="muted">Noch keine Aufrufe in diesem Zeitraum.</p>
          ) : (
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th scope="col">Tag</th>
                    <th scope="col">Zweck</th>
                    <th scope="col">Modell</th>
                    <th scope="col">Aufrufe</th>
                    <th scope="col">Tokens ein / aus</th>
                    <th scope="col">Kosten</th>
                  </tr>
                </thead>
                <tbody>
                  {usage.data.llm.map((row) => (
                    <tr key={`${row.day}-${row.purpose}-${row.model}`}>
                      <td>{formatDate(row.day)}</td>
                      <td>{row.purpose}</td>
                      <td>
                        {row.provider} · {row.model}
                      </td>
                      <td>{NUMBER.format(row.calls)}</td>
                      <td>
                        {NUMBER.format(row.tokens_in)} / {NUMBER.format(row.tokens_out)}
                      </td>
                      <td>{EURO.format(row.cost_eur)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <p className="muted">
            Gastzähler gelten seit dem letzten Neustart der API. Simulation steuern und Agenten konfigurieren folgen
            mit den Phasen A2 und A3.
          </p>
        </>
      )}
    </section>
  )
}
