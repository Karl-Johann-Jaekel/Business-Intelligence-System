# PLAN.md – Business-Intelligence-System

Stand: 2026-10-09 · Version 2.1 · ersetzt Version 2 vom 2026-10-08 (Änderungen siehe §0)

## 0. Änderungen

### Version 2.1 (2026-10-09), Entscheidungen beim Deployment

- Auf dem VPS läuft kein Keycloak. Das BI-System betreibt deshalb ein eigenes Keycloak im eigenen Stack (Realm `bis`); offener Punkt 1 ist entschieden.
- Subdomains `business` (Dashboard, API, MCP) und `auth` (Login); offener Punkt 4 ist entschieden.
- Claude wird über einen MCP-Server angebunden (Custom Connector in claude.ai), nicht über einen API-Schlüssel. Der MCP-Server wird aus K4 nach Woche 3 vorgezogen und ist Teil von M1.
- Das automatische Briefing setzt einen LLM-Zugang voraus. Ohne Zugang wird es übersprungen; die Zahlen-Leitplanke ist gebaut und getestet, ihr Live-Nachweis folgt mit einem Zugang.

### Version 2 (2026-10-08), gegenüber Version 1

- Die Wissensschicht (Meetings, Entscheidungen, Kommunikation, Dokumente) ist jetzt Teil des BI-Systems. Hive Mind bleibt unverändert.
- Neue Phasen K1–K4 zwischen MVP und Ausbau.
- Kontextpaket, Suche, Entscheidungen und Fakten-Rückkanal sind Teil der BI-API.
- Zweiter Event-Typ `decision.v1` neben `insight.v1`.
- Lokale Inferenz (Ollama) läuft im eigenen Stack des BI-Systems.
- Die Verträge (`contracts/`) liegen jetzt in diesem Repo.
- Der Erweiterungsplan für Hive Mind entfällt.

## 1. Zweck und Einordnung

End-to-End Data/AI-System, das Kennzahlen und Organisationswissen an einer Stelle zusammenführt. Es sammelt Daten aus mehreren Quellen, berechnet KPIs, erkennt Auffälligkeiten und verknüpft sie mit dem, was die Organisation dazu weiß und beschlossen hat.

- **Primärziel:** Portfolio-Projekt, das den Einsatz in einem echten Unternehmen simuliert.
- **Rolle im Gesamtbild:** Kern des Company Brain. Der Central-Intelligence-Agent ist die Handlungsschicht darauf und liest ausschließlich über die API dieses Systems.
- **Leitprinzip:** domänenunabhängiger Kern. Referenz ist eine fiktive Firma ("Referenzunternehmen"), deren Zahlen die Olist-Daten sind und deren Organisationswissen synthetisch erzeugt wird. Keine Abstraktion, die das Referenzunternehmen nicht sofort nutzt.

**Abgrenzung zu Hive Mind:** Hive Mind bleibt ein eigenständiges System für wissenschaftliche Literatur. Kein Code, keine Datenbank, kein Index, kein Workflow und kein Modell-Endpunkt von Hive Mind wird geändert oder mitgenutzt. Gemeinsam genutzt wird nur Infrastruktur auf dem VPS: der Reverse Proxy (neue Route) und Keycloak (eigener Realm, siehe offene Punkte).

## 2. Festgelegte Entscheidungen

| Thema | Entscheidung |
|---|---|
| Repo-Name | `Business-Intelligence-System` |
| Domäne | E-Commerce, öffentlicher Olist-Datensatz plus synthetisches Organisationswissen |
| Warehouse | Postgres (Docker), identisch lokal und auf dem VPS |
| Wissensspeicher | Dieselbe Postgres-Instanz, eigenes Schema `knowledge`, Erweiterung pgvector |
| Suche | Postgres-Volltext + pgvector, zusammengeführt per Reciprocal Rank Fusion |
| Graph | Relationale Knoten- und Kantentabellen in Postgres |
| Transformation | dbt (dbt-postgres) |
| Orchestrierung | Dagster für Zahlen und Dokumente (Assets, Schedules, Sensoren, Asset Checks) |
| Extraktion | LLM mit strukturierter Ausgabe und Belegpflicht; kein Agenten-Framework in diesem Repo |
| Lokale Inferenz | Eigene Ollama-Instanz im BI-Stack (Extraktion, Embeddings, vertrauliche Prompts) |
| Backend / Frontend | FastAPI / React + Vite + TypeScript |
| Alerts | E-Mail als primärer Kanal |
| Deployment | vorhandener VPS, eigenes Compose-Projekt, Subdomains `business` und `auth` |
| Login | Eigenes Keycloak im BI-Stack (Realm `bis`), OIDC mit Scopes pro Client |
| Claude-Anbindung | MCP-Server (Streamable HTTP, OAuth über Keycloak) als Connector in claude.ai; nur `public`-Daten |
| MVP-KI | Anomalieerkennung + AI-Analyst; Wissensschicht in K1–K4; NL-Querying und Forecasting in Phase 2 |

**Warum kein Qdrant:** Der Korpus des Referenzunternehmens umfasst einige tausend Chunks. Dafür reicht pgvector, und es entfällt ein Datenbankdienst. Wechsel nur, wenn Messungen es verlangen.

## 3. Architektur

```
Strukturierte Quellen                                                 Nutzung
CSV · ERP-DB · Marketing-API · Excel ─> raw ─> dbt ─> marts ─┬──────> KPI-/Zeitreihen-API ─> Dashboard
                                                             │
                                                  KPI-Registry ─> Anomalien ─┐
                                                                             ▼
                                                              Verknüpfung Insight ↔ Wissen ─> Kontext-API
                                                                             ▲                    │
Unstrukturierte Quellen                                                      │                    ▼
Meetings · Decision Records · E-Mail/Chat · Dokumente ─> Parsing ─> Chunks ─> Extraktion ─> Graph   AI-Analyst
                                                        (Volltext + Vektor)  (Fakten, Provenienz)
                                                                                                   │
                                     Outbox: insight.v1 · decision.v1 ─> E-Mail · Webhooks <───────┘

Dagster orchestriert beide Stränge. Die LLM-Schicht leitet jeden Aufruf nach Datenklasse weiter.
```

| Schicht | Umsetzung |
|---|---|
| Ingestion (Zahlen) | Connector-Interface in Python (`extract()`, Inkrementlogik, Ladeprotokoll), ein Loader pro Quelle |
| Ingestion (Wissen) | Dagster-Sensor auf einen Eingangsordner, Parser je Format, Prüfsumme gegen Duplikate |
| Warehouse | Schemas `raw`, `staging`, `intermediate`, `marts`, `knowledge`, `ops` |
| Transformation | dbt-Modelle, Tests, Makros; in Dagster über `dagster-dbt` als Assets |
| Semantic Layer | KPI-Registry als YAML, per Pydantic validiert, per API lesbar |
| Analytik | STL-Zerlegung + robuster Z-Score (MAD), feste Schwellen; Phase 2: Forecast mit `statsforecast` |
| Suche | Volltext (`tsvector`) + Vektor (pgvector, mehrsprachiges Embedding-Modell), RRF |
| Extraktion | Entscheidungen, Aufgaben, Verantwortliche, Fristen, KPI- und Entitätsnennungen als JSON nach Schema, mit Belegstelle |
| Graph und Provenienz | Knoten, Kanten, Fakten mit Status `pending` → `verified` / `conflict`; Review-Queue |
| Verknüpfung | Insight ↔ Entscheidungen und Meetings über gemeinsame Entitäten, Zeitfenster und Suche |
| KI | Provider-agnostische LLM-Schicht mit Routing nach `data_class` |
| Events | Outbox `ops.events` + Dispatcher an eine Empfängerliste; E-Mail ist der erste Empfänger |
| Auth | OIDC (eigenes Keycloak im BI-Stack, Realm `bis`), Scopes pro Client |
| MCP | Lesende Tools über die API-Logik, eigener Client `bis-claude`, Token-Audience = MCP-Ressource |

## 4. Datenbasis und Quellen

### Strukturiert

| Quelltyp | Inhalt | Echt / synthetisch |
|---|---|---|
| CSV ("Legacy-Export") | Olist: Bewertungen, Geodaten, Kategorie-Übersetzung | echt |
| Datenbank ("ERP") | Olist in separatem Postgres-Schema: Bestellungen, Positionen, Zahlungen, Kunden, Verkäufer, Produkte | echt |
| REST-API ("Marketing") | Mock-API (FastAPI): Sessions und Werbeausgaben pro Tag und Kanal | synthetisch |
| Excel ("Controlling") | Monatsbudgets pro Kategorie | synthetisch |

### Unstrukturiert (Organisationswissen des Referenzunternehmens)

| Quelle | Format | Inhalt |
|---|---|---|
| Meetings | Markdown-Protokolle, Transkripte (VTT) | Teilnehmende, Themen, Beschlüsse, Aufgaben |
| Entscheidungen | Decision Records (Markdown mit Frontmatter) | Kontext, Optionen, Beschluss, Verantwortliche, Gültigkeit |
| Kommunikation | E-Mail-Export (`.eml`/mbox), Chat-Export (JSON) | Threads, Absprachen |
| Dokumente | PDF, DOCX, Markdown | Richtlinien, Berichte, Kampagnenpläne |

Grundsätze:

1. **Replay statt Echtzeit.** Die Olist-Daten sind historisch (ca. 2016–2018). Eine Simulationsuhr (`sim_date`) gibt pro Lauf einen weiteren Tag frei, für Zahlen und Dokumente gleichermaßen. Die Historie bis zum Starttag wird einmalig per Backfill geladen.
2. **Korpus-Generator mit Bezug zu den Daten.** Der Generator liest echte Auffälligkeiten aus den Marts und erzeugt passende Meetings und Beschlüsse kurz davor oder danach. Dazu kommen Dokumente ohne Bezug (Rauschen) und Gegenbeispiele für die Evals. Seed und Personenliste sind dokumentiert, der erzeugte Korpus wird committet.
3. **Synthetik kennzeichnen.** Sessions, Werbeausgaben, Budgets und das gesamte Organisationswissen sind erzeugt. README, KPI-Glossar und Oberfläche weisen das aus.
4. **Lizenz.** Olist steht meines Wissens unter CC BY-NC-SA 4.0. Vor dem Start prüfen. Olist-Daten nicht committen, stattdessen Download-Skript.

## 5. Datenmodell

### Zahlen

- **Fakten:** `fct_orders`, `fct_order_items`, `fct_payments`, `fct_marketing_daily`
- **Dimensionen:** `dim_customer`, `dim_product`, `dim_seller`, `dim_region`, `dim_date`
- **Marts:** `kpi_daily`, `kpi_monthly`, `budget_vs_actual`

Start-KPIs: Umsatz (GMV), Anzahl Bestellungen, Ø Warenkorbwert, Frachtkostenquote, Stornoquote, Ø Lieferzeit, Pünktlichkeitsquote, Ø Bewertung, Neukunden vs. Wiederkäufer (alle echt); Conversion Rate, ROAS, Budgetabweichung (teils synthetisch).

### Wissen (Schema `knowledge`)

| Tabelle | Inhalt |
|---|---|
| `documents` | Quelle, Typ, Titel, Zeitpunkt, `data_class`, Prüfsumme |
| `chunks` | Text, Position, Sprecher/Absender, `tsvector`, Embedding |
| `nodes` | Typ, Bezeichnung, `entity_id`, Eigenschaften, Status |
| `edges` | Quelle, Ziel, Typ, Konfidenz, Status, Beleg-Chunk |
| `aliases` | Bezeichnung im Text → `entity_id` |
| `review_queue` | Offene Fakten mit Vorschlag und Beleg |
| `access_log` | Wer hat welchen Kontext abgerufen |

**Knotentypen:** `person`, `team`, `meeting`, `decision`, `action_item`, `topic`, `kpi`, `insight`, `business_entity`

**Kantentypen:** `ATTENDED`, `DECIDED_IN`, `OWNS`, `AFFECTS_KPI`, `ABOUT_ENTITY`, `SUPERSEDES`, `EVIDENCED_BY`, `RELATED_TO` (Insight ↔ Wissen, vom Verknüpfer gesetzt), `TRIGGERED` (Insight oder Entscheidung hat Aufgabe, Ticket oder Workflow ausgelöst; geschrieben vom Agenten über den Fakten-Endpoint)

**Gemeinsamer Namensraum ohne Synchronisation:** `kpi`-Knoten entstehen direkt aus der Registry, `business_entity`-Knoten direkt aus den Dimensionen. IDs nach dem Muster `<typ>:<quellschlüssel>`, also `kpi:<registry-key>`, `region:SP`, `product:…`, `customer:…`, `seller:…`, `category:…`, `person:…`, `decision:…`.

**Provenienz:** Neue Fakten starten als `pending`. Sie werden `verified`, wenn mindestens zwei unabhängige Belege über der Konfidenzschwelle liegen oder ein Mensch sie in der Review-Queue bestätigt. Widersprechen sich Belege, wird der Fakt `conflict` und nie stillschweigend überschrieben.

## 6. KPI-Registry

```yaml
- key: delivery_time_avg_days
  label: Ø Lieferzeit (Tage)
  description: Mittlere Dauer von Bestellung bis Zustellung
  source: marts.kpi_daily
  grain: day
  unit: days
  direction: lower_is_better
  dimensions: [region, category]
  entity_type: region
  alert:
    method: stl_mad
    threshold: 3.5
    min_history_days: 56
  data_class: public
  owner: person:leitung-logistik
```

Alert-Methoden: `stl_mad` (Ausreißer in Zeitreihen) und `threshold` (feste Grenze, z. B. für die Budgetabweichung auf Monatsbasis). Der Block `alert` ist optional; ein KPI ohne Schwelle wird angezeigt, aber nicht überwacht. `owner` verweist auf einen `person`-Knoten im Graph.

## 7. Events, Verknüpfung und AI-Analyst

### Events

Alle Events landen in der Outbox `ops.events` und werden vom Dispatcher an eine konfigurierbare Empfängerliste zugestellt (Webhook mit HMAC-Signatur, Wiederholung mit Backoff, Idempotenz über die Event-ID). Empfänger im MVP ist der E-Mail-Consumer; später kommt der Central-Intelligence-Agent dazu, ohne Änderung am Dispatcher.

**`insight.v1`** (Anomalie, Briefing, Forecast-Abweichung, Datenqualität):

```json
{
  "schema_version": "insight.v1",
  "insight_id": "uuid",
  "source": "business-intelligence-system",
  "type": "anomaly | briefing | forecast_deviation | data_quality",
  "kpi": "delivery_time_avg_days",
  "period": {"start": "2018-03-12", "end": "2018-03-12", "grain": "day"},
  "severity": "info | warning | critical",
  "direction": "up | down",
  "observed": 14.2,
  "expected": 9.8,
  "deviation_pct": 44.9,
  "entity_refs": [{"type": "region", "id": "region:SP"}],
  "evidence": {"method": "stl_mad", "score": 4.7, "query_ref": "/api/v1/kpis/delivery_time_avg_days/series"},
  "context_ref": "/api/v1/context?insight_id=…",
  "summary": "Kurzbeschreibung in Klartext",
  "data_class": "public | internal | confidential",
  "created_at": "ISO-8601"
}
```

Das Feld `kpi` enthält den Registry-Schlüssel ohne Präfix; als Entitäts-ID lautet derselbe KPI `kpi:<registry-key>`.

**`decision.v1`** (wird ausgelöst, sobald eine Entscheidung `verified` ist):

```json
{
  "schema_version": "decision.v1",
  "decision_id": "decision:…",
  "title": "Wechsel des Versanddienstleisters für Region SP",
  "decided_at": "2018-02-20",
  "status": "verified",
  "owners": [{"type": "person", "id": "person:leitung-logistik"}],
  "affects": [{"type": "kpi", "id": "kpi:delivery_time_avg_days"}, {"type": "region", "id": "region:SP"}],
  "evidence": [{"document_id": "…", "chunk_id": "…"}],
  "data_class": "confidential",
  "created_at": "ISO-8601"
}
```

### Verknüpfung Insight ↔ Wissen

Für jedes Insight sucht der Verknüpfer Entscheidungen, Meetings und Aufgaben, die dieselben KPIs oder Entitäten betreffen und in einem Zeitfenster davor liegen (Start: 60 Tage), und ordnet sie zusätzlich per Suche über die Insight-Zusammenfassung. Treffer über der Schwelle werden als `RELATED_TO`-Kante mit Score gespeichert.

Die Oberfläche zeigt sie als "möglicher Kontext", nie als Ursache. Ob ein Zusammenhang kausal ist, beurteilt ein Mensch oder später der Agent mit Begründung.

### AI-Analyst

- Erhält berechnete Werte (KPIs, Abweichungen, Top-Treiber) und ab K3 den verknüpften Kontext.
- Liefert strukturiertes JSON: Zusammenfassung, Befunde mit Belegverweis, Handlungsvorschläge.
- **Zahlen-Leitplanke:** Jede Zahl im Text muss in den Eingabedaten vorkommen.
- **Beleg-Leitplanke:** Jede Aussage über Organisationswissen verweist auf einen Chunk. Fehlt der Verweis, wird das Briefing verworfen und neu erzeugt.

## 8. Datenklassen und LLM-Routing

| `data_class` | Beispiele | Erlaubte Modelle |
|---|---|---|
| `public` | Olist-Kennzahlen, Registry | Externe Provider (MVP: Anthropic) und lokal |
| `internal` | Briefings ohne Personenbezug | EU-Provider oder lokal (Festlegung in Phase 2) |
| `confidential` | Meetings, E-Mails, Entscheidungen, Personen | Nur lokal (Ollama im BI-Stack) |

- Pflichtfeld auf Dokumenten, Chunks, Knoten, Events und Registry-Einträgen, ab Woche 1 im Schema.
- Ein Prompt erbt die höchste Datenklasse seiner Bestandteile.
- Die LLM-Schicht erzwingt das Routing. Ein Test stellt sicher, dass ein vertraulicher Aufruf an einen externen Provider fehlschlägt.
- Der MCP-Server gilt als externer Empfänger (Claude): er gibt nur Daten der Klassen aus `BIS_MCP_DATA_CLASSES` heraus, Standard `public`.
- Für Demos lässt sich der synthetische Korpus per Schalter als `public` einstufen, um lokale und externe Modelle in den Evals zu vergleichen. Standard bleibt `confidential`.

## 9. API v1

| Endpoint | Zweck | Scope |
|---|---|---|
| `GET /api/v1/kpis` | Registry (Semantic Layer) | `read:kpi` |
| `GET /api/v1/kpis/{key}/series` | Zeitreihe, Parameter `from`, `to`, `grain`, `dim` | `read:kpi` |
| `GET /api/v1/insights` | Insights, Parameter `since`, `type`, `severity` | `read:kpi` |
| `GET /api/v1/briefings/latest` | Aktuelles Briefing | `read:kpi` |
| `GET /api/v1/search` | Hybride Suche im Wissen, Filter nach Quelle, Zeitraum, Entität, Datenklasse | `read:knowledge` |
| `GET /api/v1/decisions` | Entscheidungen nach KPI, Entität, Zeitraum, Status | `read:knowledge` |
| `GET /api/v1/graph/neighbors` | Nachbarschaft eines Knotens | `read:knowledge` |
| `GET /api/v1/context` | Kontextpaket (`context.v1`) zu Insight, KPI oder Entität und Zeitraum | `read:knowledge` |
| `POST /api/v1/facts` | Rückkanal: Aktionen und Ergebnisse als Fakten, Kante `TRIGGERED` | `write:facts` |
| `GET/POST /api/v1/review` | Review-Queue | `admin:review` |
| `POST /api/v1/query` | Fragen in natürlicher Sprache (Phase 2) | `read:kpi`, `read:knowledge` |
| `GET /api/v1/health` | Status, letzter erfolgreicher Lauf | – |
| `/mcp` | MCP-Server (Streamable HTTP) für Claude; Tools für Status, KPIs, Zeitreihen, Vergleiche, Insights, Briefing | `read:kpi` (Token für die MCP-Ressource) |

Die API liest über eine Datenbankrolle ohne Schreibrechte auf `marts` und `knowledge`. Schreibende Endpoints (`facts`, `review`) laufen über eine eigene Rolle mit Zugriff nur auf die betroffenen Tabellen. Jeder Abruf von `read:knowledge` wird in `knowledge.access_log` protokolliert.

## 10. Verträge

`contracts/` in diesem Repo ist die Quelle der Wahrheit: JSON Schema und Beispiel-Payloads für `insight.v1`, `decision.v1`, `context.v1`, `action.v1` und den Entitäts-Namensraum. Semantische Versionierung, innerhalb einer Hauptversion nur additive Änderungen. Der Central-Intelligence-Agent bindet eine getaggte Version ein und prüft in seiner CI dagegen.

## 11. Repo-Struktur

```
Business-Intelligence-System/
├── contracts/        # JSON Schemas, Beispiel-Payloads, Vertragstests
├── ingestion/        # Connector-Interface, Loader pro Quelle, Mock-API
├── dbt/              # staging, intermediate, marts, tests, Makros
├── registry/         # KPI-YAMLs, Pydantic-Schema, Validator
├── knowledge/
│   ├── generator/    # Korpus-Generator für das Referenzunternehmen
│   ├── corpus/       # Erzeugter Korpus (committet)
│   ├── parse/        # Parser je Format, Chunking
│   ├── index/        # Embeddings, Volltext, hybride Suche
│   ├── extract/      # Strukturierte Extraktion mit Belegstelle
│   ├── graph/        # Knoten, Kanten, Entitätsauflösung, Provenienz
│   └── link/         # Verknüpfung Insight ↔ Wissen, Kontextpaket
├── orchestration/    # Dagster: Assets, Schedules, Sensoren, Checks
├── analytics/        # Anomalie, Anomalie-Injektion, später Forecast
├── llm/              # Provider-Abstraktion, Routing nach Datenklasse, Leitplanken
├── events/           # Outbox, Dispatcher, E-Mail-Consumer
├── api/              # FastAPI
├── frontend/         # React: Dashboard, Kontext, Graph, Review
├── evals/            # Testfragen, markierte Dokumente, Szenarien
├── infra/            # docker-compose (lokal, VPS), .env.example
├── docs/             # Architektur, KPI-Glossar, ADRs
├── tests/
└── .github/workflows/
```

## 12. Phasen und Definition of Done

Zeitangaben in Vollzeit-Wochen. dbt und Dagster sind beide neu; bei Teilzeit entsprechend strecken.

### Woche 1 – Fundament
- Repo, Docker-Postgres mit pgvector, Download-Skript, Simulationsuhr
- Connector-Interface und vier Loader nach `raw`, Ladeprotokoll in `ops`
- dbt: Staging, Star-Schema, `kpi_daily`; dbt-Tests
- Dagster: Ingestion- und dbt-Assets
- KPI-Registry mit Validator; `data_class` und Entitäts-IDs in Schema und Dimensionen; `contracts/` mit Entwurf von `insight.v1`

**DoD:** Ein Befehl startet die Umgebung. Ein Materialisierungslauf füllt `raw` bis `marts` fehlerfrei. `dbt build` ist grün. Mindestens 8 KPIs stehen in Registry und `kpi_daily`. CI validiert Registry, dbt-Projekt und Schemas.

### Woche 2 – Pipeline und Dashboard
- Täglicher Schedule, Asset Checks für Aktualität und Zeilenzahlen, Wiederanlauf nach Fehlern
- FastAPI: Registry-, Series- und Health-Endpoints, Leserolle, pytest
- React: KPI-Cards, Trendcharts, Filter, Abweichungsansicht, alles aus Registry-Metadaten

**DoD:** Fünf simulierte Tage laufen ohne manuellen Eingriff durch. Ein neuer Registry-Eintrag erscheint ohne Frontend-Änderung. API-Tests sind grün.

### Woche 3 – Insights und Betrieb
- Anomalieerkennung als Asset (`stl_mad`, `threshold`), schreibt `insight.v1` in die Outbox
- Anomalie-Injektion als Testwerkzeug
- Dispatcher + E-Mail-Alert, AI-Analyst mit Zahlen-Leitplanke
- Login über Keycloak, Deployment auf dem VPS, CI baut Images, README
- MCP-Server für Claude (vorgezogen aus K4), tägliches Backup

**DoD:** Injizierte Anomalien werden erkannt und gemeldet (Startziel: ≥ 80 % Trefferquote, ≤ 2 Fehlalarme pro simuliertem Monat). Das Briefing besteht die Zahlen-Leitplanke, sobald ein LLM-Zugang konfiguriert ist; ohne Zugang wird es übersprungen. Das Dashboard ist nur nach Login erreichbar. Claude erreicht das System als Connector mit Login und sieht nur `public`-Daten.

**Meilenstein M1:** BI-MVP läuft, MCP-Connector für Claude ist nutzbar, `insight.v1` ist eingefroren.

### K1 – Wissensaufnahme (ca. 1 Woche)
- Korpus-Generator, gekoppelt an Simulationsuhr und echte Auffälligkeiten
- Parser für Protokolle, Transkripte, Decision Records, E-Mail- und Chat-Exporte, PDF/DOCX
- Chunking, Embeddings über das lokale Modell, Volltextindex, hybride Suche
- Dagster-Sensor auf den Eingangsordner, Ollama im Compose-Stack
- Routing-Test für vertrauliche Daten

**DoD:** Der Korpus ist durchsuchbar, Filter nach Quelle, Zeitraum und Datenklasse funktionieren. Auf 20 Testfragen steht die richtige Quelle bei mindestens 80 % in den Top 5. Der Routing-Test schlägt bei einem externen Aufruf mit vertraulichem Kontext fehl.

### K2 – Extraktion und Graph (1–1,5 Wochen)
- Strukturierte Extraktion mit lokalem Modell, Belegpflicht
- Entitätsauflösung gegen Registry, Dimensionen und Alias-Tabelle
- Provenienz-Status, Review-Queue im Frontend, Graph-Ansicht (z. B. react-force-graph)

**DoD:** Auf 30 handmarkierten Dokumenten erreichen Entscheidungen und Aufgaben das Startziel (Precision ≥ 0,8, Recall ≥ 0,7). Kein Fakt ohne Belegstelle. Ein Review ändert den Status nachvollziehbar.

### K3 – Verknüpfung und Kontext (ca. 1 Woche)
- Verknüpfer Insight ↔ Wissen, Kontextpaket `context.v1`
- Kontextbereich im Dashboard neben jeder Abweichung
- AI-Analyst mit Kontext und Beleg-Leitplanke (lokal bei vertraulichem Kontext)
- `decision.v1`-Events in der Outbox

**DoD:** In den drei Demo-Szenarien (siehe Plan des Central-Intelligence-Agent) enthält das Kontextpaket die passende Entscheidung. Im Gegenszenario ohne Zusammenhang erscheint kein Kontext über der Schwelle. Jede Kontextaussage im Briefing hat einen auflösbaren Beleg.

### K4 – Schnittstelle für Agenten (3–4 Tage)
- Keycloak-Scopes pro Client, Zugriffsprotokoll
- `POST /api/v1/facts` mit Kante `TRIGGERED`
- OpenAPI-Dokumentation, `context.v1` und `decision.v1` eingefroren
- MCP-Server (seit M1 vorhanden) um Suche, Entscheidungen und Kontextpakete erweitern

**DoD:** Ein Dienstkonto mit Lese-Scopes kann suchen und Kontextpakete abrufen; ohne Scope wird abgelehnt; jeder Abruf steht im Protokoll. Ein geschriebener Fakt erscheint als Kante im Graph.

**Meilenstein M2:** Wissensschicht fertig, Eintrittskriterien für den Central-Intelligence-Agent erfüllt.

### Phase 2 – Ausbau (ca. 3 Wochen)
- Ein Eingabefeld für Fragen: ein Router entscheidet zwischen SQL über die Marts (Prüfung mit `sqlglot`, nur `SELECT`, Zeilenlimit, Timeout) und Antwort aus dem Wissen mit Quellenangaben
- Forecasting mit Konfidenzband, Insight-Typ `forecast_deviation`
- Weitere LLM-Provider, eigener Schlüssel pro Nutzer
- Weitere Logins über Keycloak-Identity-Brokering (Google, GitHub; "Sign in with ChatGPT", falls die Registrierung für Einzelentwickler offen ist)
- Upload-Endpoint für Dokumente, Datenqualitätsansicht

### Phase 3 – Generalitätsnachweis (ca. 1 Woche)
Zweite Domäne (z. B. Superstore oder ein SaaS-Datensatz) mit neuen Loadern, Marts, Registry-Datei und einem kleinen neuen Korpus.

**DoD:** Kein Commit in `analytics/`, `llm/`, `events/`, `api/`, `frontend/`, `knowledge/parse|index|extract|graph|link` nötig.

## 13. Betrieb auf dem VPS

- Eigenes Compose-Projekt: `postgres` (mit pgvector; Warehouse, Wissen, Dagster-Metadaten und Keycloak in getrennten Datenbanken bzw. Schemas), `dagster-webserver`, `dagster-daemon` (Läufe), `api`, `mcp`, `frontend`, `keycloak`, `mock-marketing-api`, später `ollama`
- Anschluss an den bestehenden Reverse Proxy über zwei neue Routen (`business`, `auth`); Keycloak läuft im BI-Stack, die Admin-Konsole ist von außen gesperrt
- Betriebsdetails: [docs/deployment.md](docs/deployment.md)
- Dagster-Oberfläche nicht öffentlich, nur hinter Login oder per SSH-Tunnel
- **Ressourcen:** BI-Stack ohne Modell grob 2–3 GB RAM. Ein lokales 7–8B-Modell in 4-Bit-Quantisierung braucht zusätzlich etwa 5–6 GB, plus Embedding-Modell. Ohne GPU ist die Extraktion langsam; sie läuft deshalb als Nachtlauf. Vor K1 messen; bei Engpass kleineres Modell oder Demo-Korpus als `public` mit externem Modell
- Backups: tägliches `pg_dump` von `ops`, `marts` und `knowledge`; `raw` ist reproduzierbar, der Korpus liegt im Repo

## 14. Datenschutz

- Im Portfolio-Betrieb nur synthetische Personen und Inhalte
- Kommunikation nur aus ausdrücklich bereitgestellten Exporten, kein automatisches Abgreifen von Postfächern
- Aufbewahrungsfrist und Löschweg pro Quelle: Dokument, Chunks, Embeddings und abgeleitete Fakten werden gemeinsam gelöscht
- Zugriffe auf Wissen werden protokolliert
- Für einen realen Einsatz kämen Rechtsgrundlage, Zweckbindung, Beschäftigtendatenschutz und ggf. Mitbestimmung dazu; das ist vor echten Daten rechtlich zu klären und nicht Teil dieses Plans

## 15. Pre-Start-Checkliste

- [ ] Freie Ressourcen auf dem VPS messen, CPU-Tempo eines lokalen Modells testen
- [x] Route im bestehenden Reverse Proxy; Keycloak im BI-Stack (auf dem VPS gab es keins)
- [x] Subdomains `business` und `auth`, TLS über den bestehenden Caddy
- [ ] Olist-Lizenz gegenlesen
- [ ] SMTP-Anbieter wählen, Absenderdomain mit SPF/DKIM
- [ ] API-Schlüssel für den externen LLM-Provider, Ausgabenlimit setzen
- [ ] Lokales Extraktions- und Embedding-Modell auswählen
- [x] Versionen von Dagster, dbt, `dagster-dbt` und pgvector pinnen

## 16. Risiken

| Risiko | Gegenmaßnahme |
|---|---|
| Das Repo wird zu groß für eine Person | Wissensschicht erst nach dem MVP; jede K-Phase mit harter DoD; kein Start von K1 vor M1 |
| Lernkurve dbt + Dagster | Erst dbt allein lauffähig, dann in Dagster einhängen |
| Fehlalarme entwerten die Alerts | Schwellen pro KPI, Mindesthistorie, Test mit injizierten Anomalien |
| LLM erfindet Zahlen oder Fakten | Zahlen- und Beleg-Leitplanke, strukturierte Ausgabe |
| Lokales Modell zu langsam oder zu ungenau | Nachtlauf, Messung auf Testset, kleineres Modell oder Demo-Schalter auf `public` |
| Verknüpfung suggeriert Ursachen | Als "möglicher Kontext" kennzeichnen, Gegenszenario in den Evals |
| Doppelarbeit mit Hive Mind | Bewusste Trennung: Hive Mind für Forschungsliteratur, BI-System für Unternehmenswissen. Eine spätere Zusammenführung bleibt möglich |
| Synthetischer Korpus wirkt konstruiert | Aus echten Auffälligkeiten ableiten, Rauschen und Gegenbeispiele einbauen, offen kennzeichnen |

## 17. Offene Punkte

1. ~~Keycloak: eigener Realm oder getrennte Anmeldung~~ Entschieden (2.1): eigenes Keycloak im BI-Stack
2. Lokales Modell und ob die Hardware des VPS dafür reicht
3. Datenklasse des Demo-Korpus im Standardbetrieb
4. ~~Subdomain-Schema~~ Entschieden (2.1): `business`, `auth`
5. Zweite Domäne für Phase 3
6. Reihenfolge nach M2: Central-Intelligence-Agent oder zuerst Phase 2 (Empfehlung im Plan des Central-Intelligence-Agent)
