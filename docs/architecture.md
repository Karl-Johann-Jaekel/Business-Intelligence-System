# Architektur

Gesamtplan und Begründungen: [plan.md](../plan.md). Dieses Dokument beschreibt den
umgesetzten Stand.

```
Quellen                          Ingestion (Python)        Warehouse (Postgres, DB warehouse)
Postgres DB erp (ERP)      ──┐
CSV data/olist (Legacy)    ──┼─> Connector.extract() ──> raw ──> staging ──> intermediate ──> marts
Mock-API :8101 (Marketing) ──┤   + ops.load_log            (dbt)                               │
Excel data/controlling     ──┘                                                                  └─> kpi_daily / kpi_monthly
                                                                                                    ↑ KPI-Registry (YAML)
Dagster: Uhr-Asset → ein Multi-Asset je Quelle → dbt-Assets → Asset Checks
marts ──(Rolle bis_api, read-only)──> FastAPI :8102 ──> React-Dashboard (Vite :5173)
```

## Komponenten

| Pfad | Aufgabe |
|---|---|
| `ingestion/base.py` | Connector-Interface, Wasserstand-Logik, Ladeprotokoll |
| `ingestion/connectors/` | Je ein Connector pro Quelle |
| `ingestion/clock.py` | Simulationsuhr (`ops.sim_clock`) |
| `ingestion/setup/` | Download, ERP-Befüllung, synthetische Daten |
| `ingestion/mock_marketing_api/` | FastAPI-Mock der Marketing-Quelle (Container) |
| `dbt/` | Staging, Intermediate, Marts, Tests |
| `registry/` | KPI-Registry, Pydantic-Schema, Validator |
| `orchestration/` | Dagster-Definitions, `bis`-CLI |
| `infra/` | docker-compose (Postgres, Mock-API) |

## Datenbanken im Postgres-Container

| Datenbank | Inhalt |
|---|---|
| `warehouse` | Schemas `raw`, `staging`, `intermediate`, `marts`, `ops` |
| `erp` | Simuliertes Quellsystem (Schema `erp`, typisierte Olist-Tabellen) |
| `dagster` | Run- und Event-Storage von Dagster |

Abweichung vom Plan: Das ERP liegt in einer eigenen Datenbank statt nur in einem eigenen
Schema. Der Connector braucht so eine echte zweite Verbindung, wie bei einem fremden System.

## Ladelogik

- **incremental:** Wasserstand = höchster Zeitstempel des letzten erfolgreichen Laufs aus
  `ops.load_log`. Geladen wird `(Wasserstand, sim_date]`. Erster Lauf = Backfill.
- **full:** Tabelle wird pro Lauf ersetzt (Stammdaten, Geodaten, Budget).
- Raw-Tabellen speichern alle Fachspalten als `text` plus `_load_id` und `_loaded_at`;
  Typisierung und Deduplizierung (`latest_per_key`) passieren in dbt-Staging.
- Pro Entität werden Daten und Protokollzeile in einer Transaktion geschrieben. Fehler werden
  als `failed` protokolliert; der Wasserstand bleibt dann unverändert, ein Wiederholungslauf
  setzt sauber auf.

## Simulationsuhr

`ops.sim_clock` enthält ein Datum. Connectoren liefern nur Daten bis zu diesem Tag;
`stg_erp__orders` maskiert zusätzlich Zeitstempel, die danach liegen. `bis tick` schiebt die
Uhr um einen Tag und startet die Pipeline.

## Orchestrierung (Woche 2)

- **Schedule `simulated_day`:** Jeder Tick startet `daily_pipeline` mit `advance_days=1`. Das
  Asset `ops/sim_clock` rückt die Uhr vor; `ops.clock_advances` speichert das pro Root-Run-ID,
  sodass Wiederholungen und Re-Executions die Uhr nicht doppelt vorrücken. Manuelle Läufe
  (`bis materialize`) lassen die Uhr stehen.
- **Überlappung:** Der Schedule überspringt den Tick, solange ein Run aktiv ist
  (`QUEUED`/`STARTING`/`STARTED`); zusätzlich `max_concurrent_runs: 1`.
- **Wiederanlauf:** Ingestion-Steps haben eine Retry-Policy (2 Versuche, exponentiell ab 10 s).
  Scheitert der Run trotzdem, startet Dagster ihn bis zu zweimal ab dem fehlgeschlagenen Step
  neu (`dagster/max_retries`, `FROM_FAILURE`). Run-Monitoring beendet hängende Starts nach 3 min.
- **Asset Checks:** `rows_present` (Raw-Tabelle nicht leer) und `new_rows_loaded` (Warnung bei
  leerem Inkrement) je Ingestion-Asset; `kpi_daily_current` (letzter KPI-Tag = Simulationsdatum)
  und `kpi_registry_coverage` auf `marts/kpi_daily`; dazu alle dbt-Tests.

## API

FastAPI in `api/`, als Container `api` in docker-compose. Verbindet sich als Rolle `bis_api`:
nur `SELECT` auf `marts` (dbt `grants`), `default_transaction_read_only`, Statement-Timeout 10 s.
Der Status für `/health` kommt aus dem Mart `pipeline_status`, damit die Rolle `ops` nicht sehen muss.

| Endpoint | Zweck |
|---|---|
| `GET /api/v1/kpis`, `/kpis/{key}` | Registry (Semantic Layer) |
| `GET /api/v1/kpis/{key}/series` | Zeitreihe; `from`, `to`, `grain`, `dim`, `value` (mehrfach), `top` |
| `GET /api/v1/kpis/{key}/breakdown` | Wert je Dimensionsausprägung vs. gleich lange Vorperiode |
| `GET /api/v1/health` | `ok` / `stale` / `down`, Simulationsdatum, letzte Ladezeiten |

Quoten werden über Zähler/Nenner neu aggregiert, nie gemittelt. `breakdown` ist eine Ergänzung
zum Plan; sie speist KPI-Cards und Abweichungsansicht.

## Dashboard

React + Vite + TypeScript in `frontend/`, ohne Chart-Library (eigene SVG-Komponenten nach
Dataviz-Vorgaben: validierte Palette hell/dunkel, Crosshair-Tooltip, Tabellenansicht).
Alles wird aus Registry-Metadaten gerendert (Label, Einheit, Richtung, Dimensionen, Granularität,
Datenherkunft); es gibt keinen KPI-spezifischen Code. Filter (Zeitraum, Dimension, KPI) stehen
in der URL. Quotenänderungen werden in Prozentpunkten angezeigt.

## Insights (Woche 3)

Dagster-Assets nach den Marts: `insights/anomalies` → `insights/briefing` → `insights/dispatch`.

- **Anomalieerkennung** (`analytics/anomaly.py`, `analytics/detect.py`): Methode laut Registry.
  `stl_mad`: Wochentagseffekt aus STL (Median der letzten vier gleichen Wochentage), Niveau =
  rollierender Median der saisonbereinigten Vortage (14 Tage, kausal), robuster Z-Score der
  Abweichung gegen die Ein-Schritt-Fehler des Fensters. `threshold`: feste Grenze, monatlich auf
  dem letzten vollständigen Monat. Überwacht werden die Gesamtreihe und die fünf größten
  Mitglieder der `entity_type`-Dimension, bei Tageswerten nur für additive KPIs und mit
  1,5-facher Schwelle. Kalibrierung und Messwerte: [anomaly-evaluation.md](anomaly-evaluation.md).
- **Live-Messung inklusive Regionen/Kategorien** (Backfill 2017-10-01 bis 2018-01-11): 1,8 Alarme
  pro KPI und Monat außerhalb der Black-Friday-Woche; 40 weitere Alarme in der Woche
  24.–29.11.2017 sind echte Ereignisse.
- **Outbox** `ops.events` (bis 2026-10-08 `ops.insights`, migriert in `ensure_ops_schema`): ein
  Event pro Befund (`event_type` `insight`, ab A4 auch `decision`), Idempotenz über `dedup_key`
  (Typ, KPI, Entität, Periode). Backfill: `python -m analytics.detect --from … --to …`.
- **Dispatcher** (`events/dispatch.py`): Empfänger aus `events/consumers.yaml`, Zustellstatus je
  Event und Empfänger in `ops.event_deliveries`, Wiederholung mit Backoff (1, 2, 4, 8 min,
  max. 5 Versuche), `FOR UPDATE SKIP LOCKED`. Das Alter (`max_age_days`) zählt in
  Simulationszeit, damit ein Backfill keine Mail-Flut auslöst.
- **E-Mail**: HTML + Text, Deep Link ins Dashboard. Lokal landet alles in Mailpit
  (`http://127.0.0.1:8025`).
- **AI-Analyst** (`llm/`): Eingabe sind nur berechnete, formatierte Werte mit IDs
  (`llm/context.py`). Ausgabe strukturiert (Zusammenfassung, Befunde mit `evidence_ref`,
  Handlungsvorschläge). Die Zahlen-Leitplanke (`llm/guardrail.py`) verwirft jeden Entwurf mit
  Zahlen, Daten oder IDs, die nicht im Input stehen, und lässt bis zu dreimal neu erzeugen.
  Provider MVP: Anthropic (`claude-opus-5-5`, Effort `medium`, Refusal-Fallback). Ohne
  Zugangsdaten wird das Briefing übersprungen, Alerts laufen weiter.

Neue API-Endpoints: `GET /api/v1/insights` (`since`, `type`, `severity` als Mindeststufe, `kpi`)
und `GET /api/v1/briefings/latest`. Die Rolle `bis_api` darf zusätzlich `ops.events` lesen,
nicht aber das Zustellprotokoll.

## Plan v2: Angleichung (2026-10-08)

- **pgvector:** Image `pgvector/pgvector:0.8.1-pg16`, Erweiterung `vector` in `warehouse`. Das
  alte Alpine-Image sortiert Text anders (musl vs. glibc); die Migration lief daher per
  Dump/Restore in ein neues Volume `pgdata_pg16vector`.
- **Verträge:** [contracts/](../contracts/README.md) ist die Quelle der Wahrheit für `insight.v1`
  und den Entitäts-Namensraum. `tests/test_contracts.py` prüft Beispiele, das Pydantic-Modell
  (Felder deckungsgleich) und echte Outbox-Payloads sowie Entitäts-IDs aus den Dimensionen.
  Neu in `insight.v1`: optionales `context_ref` (A4).
- **Datenklassen:** Jeder Empfänger hat `max_data_class` (E-Mail: `internal`), das Event trägt
  `data_class` als Spalte. Die LLM-Schicht erzwingt Plan §8: jeder Aufruf nennt seine
  Datenklasse, ein externer Provider lehnt alles über `public` mit `LLMRoutingError` ab, bevor
  etwas das System verlässt. Das Briefing bekommt nur Kennzahlen, die der Provider sehen darf.
- **Registry-Owner:** `person:`-IDs des Referenzunternehmens ([reference-company.md](reference-company.md)).
- **Secrets:** keine Passwort-Defaults im Code. `infra/.env` (git-ignored) wird von `bis setup`
  mit Zufallswerten erzeugt und um neue Schlüssel ergänzt; Compose bricht ohne Werte ab.

## Login (Keycloak)

| Teil | Umsetzung |
|---|---|
| Realm | `bis`, Datei [infra/keycloak/realm-bis.json](../infra/keycloak/realm-bis.json) (Clients) |
| Clients | `bis-frontend` (public, Authorization Code + PKCE, Audience-Mapper auf `bis-api`), `bis-api` (bearer-only) |
| Scopes | `read:kpi`, `read:knowledge`, `write:facts`, `admin:review` (Plan §9/§10); Dashboard: `read:kpi` |
| Einrichtung | `orchestration/keycloak_setup.py` über die Admin-API, idempotent, aus `bis setup` |
| API | `api/auth.py`: Signatur (JWKS), Issuer, Audience, Ablauf, Scope pro Endpoint; 401/403 mit `WWW-Authenticate` |
| Frontend | `oidc-client-ts`, Token im `sessionStorage`, bei 401 neuer Login |

Lokal läuft Keycloak im Dev-Modus mit Dateispeicher. Auf dem VPS bekommt das bestehende
Keycloak den Realm `bis` (offener Punkt 1 im Plan), die Redirect-URIs werden angepasst.

## MCP-Server für Claude

`api/mcp_server.py`, eigener Container `mcp` aus dem API-Image, über nginx unter `/mcp`.

| Teil | Umsetzung |
|---|---|
| Transport | Streamable HTTP, zustandslos, JSON-Antworten (SDK `mcp` 2.x) |
| Tools | `get_status`, `list_kpis`, `get_kpi_series`, `compare_kpi`, `list_insights`, `get_latest_briefing`; alle read-only, nutzen die Logik und die Leserolle der API |
| Discovery | `/.well-known/oauth-protected-resource/mcp` verweist auf Keycloak; Keycloak 26.4 liefert RFC-8414-Metadaten |
| Login | Client `bis-claude` (vertraulich, PKCE S256, Callback von claude.ai), Scope `read:kpi`, Audience = MCP-Ressource. MCP-Token gelten nicht für die REST-API und umgekehrt |
| Datenklassen | nur `BIS_MCP_DATA_CLASSES` (Standard `public`); interne KPIs, Insights und Briefings bleiben im System |
| Schutz | DNS-Rebinding-Schutz über `BIS_MCP_ALLOWED_HOSTS`; keine offene dynamische Client-Registrierung |
