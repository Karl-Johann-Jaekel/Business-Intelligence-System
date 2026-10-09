# PLAN.md – Business-Intelligence-System

Stand: 2026-10-09 · Version 3 · ersetzt Version 2.1 vom selben Tag (Änderungen siehe §0)
Gegenstück: Plan des Central-Intelligence-Agent (CIA), Version 3 – [docs/central-intelligence-agent-plan.md](docs/central-intelligence-agent-plan.md)

## 0. Änderungen

### Version 3 (2026-10-09), Agentic BI über zwei Systeme

- **Gesamtbild Agentic BI:** Das BI-System ist das Fundament (Daten, Simulation, Kennzahlen, Wissen, geprüfte Analysewerkzeuge, Portal). Der Central-Intelligence-Agent (eigenes Repo) ist das Agentensystem: zentraler Agent, Bereichs-Agenten, kontrolliertes Spawning, Maßnahmen. Leitsatz: **Das BI-System weiß, der CIA denkt und handelt.**
- **Unternehmenssimulation mit zehn Bereichen** statt nur Vertrieb, Marketing und Controlling (§4); Olist bleibt die echte Grundlage, alles andere wird kausal daran gekoppelt simuliert. Produktion & Operations wird als Fulfillment simuliert.
- **Ein Portal:** Das BI-Frontend ist die einzige Oberfläche. Agenten-Seiten lesen die CIA-API; Freigaben von Maßnahmen liegen im Admin-Bereich.
- **Zwei Zugänge:** Gast („Als Gast fortfahren“ mit Captcha, nur lesen, kleines Fragekontingent) und privater Admin mit MFA, Agenten- und Simulationssteuerung, eigenem LLM und vollem Claude-Connector (§9).
- **Monitoring der Agenten:** neuer Bereich „AI Operations“. Der CIA erfasst Fehler, Kosten, Laufzeiten, Delegationstiefe, falsche Befunde und offene Tasks; das BI-System lädt die Tageswerte als Quelle und überwacht sie wie jede andere Abteilung (§7).
- **Kein lokales Modell auf dem VPS** (Messung 2026-10-09: 4 vCPU, 4,2 GB frei). LLM-Provider ist Mistral (EU, kostenlose Stufe); die ganze Simulation und der Korpus sind `public` (offener Punkt 3 entschieden). Suche zuerst über Postgres-Volltext.
- **Neue Phasen A0–A5** ersetzen K1–K4 und sind mit den CIA-Phasen C0–C5 verzahnt (§13).

### Version 2.1 (2026-10-09)

Eigenes Keycloak im BI-Stack (Realm `bis`), Subdomains `business` und `auth`; Claude über MCP-Connector statt API-Schlüssel (Teil von M1); Briefing ohne LLM-Zugang wird übersprungen.

### Version 2 (2026-10-08)

Wissensschicht wird Teil des BI-Systems; `contracts/` liegt in diesem Repo; `decision.v1` neben `insight.v1`.

## 1. Zweck und Einordnung

Fundament eines agentischen BI-Systems für ein simuliertes Unternehmen. Es führt Kennzahlen aller Unternehmensbereiche und das Organisationswissen zusammen, erkennt Auffälligkeiten, stellt geprüfte Analysewerkzeuge bereit und ist das Portal, über das Gäste und Admin alles sehen, auch die Arbeit der Agenten.

- **Primärziel:** Portfolio-Projekt, öffentlich als Gast begehbar, das den Einsatz in einem echten Unternehmen glaubwürdig simuliert.
- **Zweitziel:** privates Werkzeug für mich (Admin), auch über Claude.
- **Leitprinzipien:**
  1. *Rechnen vor Raten.* Zahlen, Abweichungen und Treiber berechnet der Code. Agenten bekommen geprüfte Werkzeuge, kein freies SQL.
  2. *Lesen und Handeln getrennt.* Das BI-System hat keinen Schreibzugriff nach außen. Agenten und Maßnahmen leben im CIA; zurück kommt nur, was über protokollierte Endpunkte geschrieben wird.
  3. *Alles nachvollziehbar.* Herkunft der Daten (echt/simuliert), Belege zu jeder Aussage, Agentenläufe als Zeitleiste.
  4. *Domänenunabhängiger Kern.* Bereiche, KPIs und Simulation sind Konfiguration; Phase 3 beweist das mit einer zweiten Domäne.

**Abgrenzung zu Hive Mind:** unverändert eigenständig (Forschungsliteratur). Gemeinsam genutzt wird nur der Reverse Proxy auf dem VPS.

## 2. Festgelegte Entscheidungen

| Thema | Entscheidung |
|---|---|
| Repo-Name | `Business-Intelligence-System` |
| Domäne | Onlinehändler („Referenzunternehmen“): Verkäufe aus Olist (echt), übrige Bereiche simuliert |
| Warehouse | Postgres 16 + pgvector (Docker), identisch lokal und auf dem VPS |
| Transformation / Orchestrierung | dbt / Dagster (Assets, Schedules, Sensoren, Checks) |
| Simulation | Eigene Engine in Python: Treibermodell als YAML, fester Seed, Szenarien mit Ground Truth |
| Agenten | Nicht in diesem Repo, sondern im CIA. Das BI-System liefert Werkzeuge, Ereignisse und Oberfläche |
| LLM | Provider-agnostisch mit Routing nach `data_class`. Mistral (kostenlose Stufe) für Briefing und Extraktion; Admin kann einen eigenen Provider setzen |
| Lokale Inferenz | Keine auf dem VPS. Optional kleines ONNX-Embedding-Modell im Prozess |
| Suche | Postgres-Volltext (deutsch); Vektor + RRF nur, wenn die Evals es verlangen |
| Graph | Relationale Knoten- und Kantentabellen in Postgres |
| Backend / Frontend | FastAPI / React + Vite + TypeScript; ein Portal für BI und Agenten |
| Login | Keycloak (Realm `bis`) für Admin mit MFA und für Dienstkonten; Gäste per Cloudflare Turnstile und Gast-Token der API, gültig für BI- und CIA-API |
| Claude-Anbindung | MCP-Server; Rechte und Datenklassen nach Token (Admin voll, sonst nur `public`) |
| Alerts | E-Mail an Admin |
| Deployment | vorhandener VPS, eigenes Compose-Projekt, Subdomains `business` und `auth`; CIA als zweites Compose-Projekt hinter derselben Subdomain |

## 3. Architektur

```
Quellen (echt + simuliert)                      BI-System                                    Portal (BI-Frontend)
Olist-ERP · CSV ─────────────┐                                                               Startseite · Bereiche
Marketing-API · Excel ───────┼─> raw ─> dbt ─> marts (10 Bereiche + AI Ops) ─> KPI-API ────> GF-Cockpit · Wissen
Simulations-Engine ──────────┤      ▲                        │                               Agenten (liest CIA-API)
CIA-Metriken (AI Ops) ───────┘      │ Simulationsuhr          ├─> Anomalien ─> insight.v1    Admin: Simulation,
                                    │ + Szenarien             │                              Freigaben, Kosten
Organisationswissen ─> Parser ─> Chunks ─> Extraktion ─> Graph┴─> Werkzeug-API · Kontext · MCP
                                                                      ▲        │
                         Outbox ops.events: insight.v1 · daily_snapshot.v1 · decision.v1
                                                                      │        ▼ Webhook (HMAC)
                                         ┌──────────── Central-Intelligence-Agent ────────────┐
                                         │ Zentraler Agent · Bereichs-Agenten · Spawn-Policy   │
                                         │ Maßnahmen mit Freigabe · Traces · Metriken · Evals  │
                                         └──── Fakten / Maßnahmen-Ergebnisse (POST /facts) ────┘
```

| Schicht | Umsetzung |
|---|---|
| Ingestion | Connector-Interface, ein Loader pro Quelle, Ladeprotokoll in `ops` (vorhanden); neu: Simulations-Engine, CIA-Metriken |
| Simulation | `simulation/`: Treiber aus Olist-Marts → Bereichsgrößen über ein kausales Modell mit Rauschen, Saisonalität und Verzögerung; schreibt pro Simulationstag nach `raw.sim_*` |
| Warehouse | Schemas `raw`, `staging`, `intermediate`, `marts`, `knowledge`, `ops` |
| Semantic Layer | KPI-Registry (YAML, Pydantic) mit Pflichtfeld `department` |
| Analytik | `stl_mad` und `threshold` (vorhanden); neu: Treiberzerlegung, Bereichs-Ampel |
| Werkzeug-API | Geprüfte, parametrisierte Analysefunktionen für Agenten (REST und MCP), Rechte je Scope und Bereich |
| Wissen | Parser, Chunks, Volltext, Extraktion, Graph mit Provenienz |
| KI | LLM-Schicht mit Routing nach Datenklasse und Kostenzählung (Briefing, Extraktion) |
| Events | Outbox + Dispatcher (vorhanden); CIA ist ein weiterer Empfänger (nur Konfiguration) |
| Zugang | Keycloak (Admin, Dienstkonten), Gast-Token (Gäste) |

## 4. Unternehmensbereiche und Datenbasis

Das Referenzunternehmen ist ein brasilianischer Onlinehändler, dessen Bestellungen, Zahlungen, Bewertungen und Lieferungen die echten Olist-Daten sind. Jeder Bereich hat eine eigene Seite, 3–6 KPIs zum Start, eine verantwortliche Person (synthetisch) und im CIA einen eigenen Agenten.

| Bereich (`department`) | Inhalte und Beispiel-KPIs | Herkunft |
|---|---|---|
| `marketing` – Marketing & Marketing Automation | Sessions, Spend, Conversion, ROAS, CAC, E-Mail-Strecken | simuliert (Mock-API, ausgebaut) |
| `sales` – Vertrieb & Sales | GMV, Bestellungen, Warenkorb, Kategorien, Regionen, Händler | echt |
| `finance` – Finanzen & Controlling | Umsatz, Zahlungsarten, Fracht, Budget vs. Ist, Deckungsbeitrag, Cashflow | gemischt |
| `customer` – Kundenmanagement & Customer Success | Bewertung, Wiederkaufrate, Tickets, Erstlösungsquote, Lösungszeit | gemischt |
| `supply` – Einkauf, Beschaffung & Supply Chain | Lieferanten (Olist-Seller), Lieferzeit, Pünktlichkeit, Bestand | gemischt |
| `operations` – Produktion & Operations (Fulfillment) | Durchsatz, Kommissionierfehler, Lagerauslastung, Retouren | simuliert |
| `hr` – Personalwesen & HR | Kopfzahl, Einstellungen, Fluktuation, Krankenquote, Überstunden | simuliert |
| `projects` – Projektmanagement & Ressourcenplanung | Projekte, Meilensteintreue, Auslastung, Budgetverbrauch | simuliert |
| `it` – IT & IT-Service-Management | Incidents, SLA-Erfüllung, Verfügbarkeit, Changes; Tickets aus Agenten-Maßnahmen | gemischt |
| `management` – Geschäftsführung & Strategie | OKRs, Cockpit über alle Bereiche, Beschlüsse | abgeleitet |
| `ai_ops` – AI Operations | Fehlerrate, Kosten, Laufzeit, Delegationstiefe, Falschbefunde, offene Tasks der Agenten | echt (aus dem CIA) |

### Grundsätze der Simulation

1. **Replay statt Echtzeit.** Die Simulationsuhr (`ops.sim_clock`) gibt pro Lauf einen Tag frei, für Olist, simulierte Bereiche und Dokumente gleichermaßen (vorhanden).
2. **Kausal gekoppelt.** Ein Treibermodell (`simulation/model.yaml`) leitet Bereichsgrößen aus echten Größen ab, z. B. Bestellvolumen → Kommissionierlast → Überstunden → Krankenquote; Lieferverzug → Tickets → Bewertung. So entstehen bereichsübergreifende Geschichten, die die Agenten aufdecken können.
3. **Szenarien.** Störungen sind injizierbar (Lieferantenausfall, Kampagnenstart, Systemausfall, Krankheitswelle, Preisänderung): vom Admin von Hand oder von einem Szenario-Plan mit festem Seed, damit das System auch ohne Eingriff regelmäßig etwas zu finden hat. Jede Injektion ist Ground Truth in `ops.scenarios`. **Agenten sehen sie nie**; nur der Evaluator des CIA liest sie über einen eigenen Scope.
4. **Reproduzierbar.** Fester Seed, versionierte Modellparameter.
5. **Synthetik kennzeichnen.** Herkunft steht in Registry, Oberfläche und README.
6. **Lizenz.** Olist vermutlich CC BY-NC-SA 4.0, vor öffentlichem Betrieb prüfen. Olist-Daten nie committen.

### Organisationswissen (synthetisch)

| Quelle | Format | Inhalt |
|---|---|---|
| Meetings | Markdown-Protokolle, Transkripte (VTT) | Teilnehmende, Themen, Beschlüsse, Aufgaben |
| Entscheidungen | Decision Records (Markdown mit Frontmatter) | Kontext, Optionen, Beschluss, Verantwortliche |
| Kommunikation | E-Mail (`.eml`), Chat (JSON) | Threads, Absprachen |
| Dokumente | PDF, DOCX, Markdown | Richtlinien, Berichte, Kampagnenpläne |

Der Korpus-Generator (Deutsch, vorlagenbasiert, fester Seed) leitet Meetings und Beschlüsse aus echten Auffälligkeiten und Szenarien ab, ergänzt Rauschen und Gegenbeispiele. Der erzeugte Korpus wird committet.

## 5. Datenmodell

### Zahlen

- Vorhanden: `fct_orders`, `fct_order_items`, `fct_payments`, `fct_marketing_daily`, Dimensionen, `kpi_daily`, `kpi_monthly`, `budget_vs_actual`
- Neu: `raw.sim_<bereich>` aus der Engine und `raw.cia_agent_metrics` aus dem CIA; je Bereich Staging- und Faktenmodelle; `kpi_daily` nimmt alle Bereiche auf
- `ops.scenarios`: Szenarien mit Zeitraum, Parametern und betroffenen KPIs (Ground Truth)
- `ops.sim_tickets`: Aufgaben und Tickets im simulierten Unternehmen; Ziel von Agenten-Maßnahmen, sichtbar in `it` und `projects`

### Wissen (Schema `knowledge`)

| Tabelle | Inhalt |
|---|---|
| `documents` | Quelle, Typ, Titel, Zeitpunkt, Bereich, `data_class`, Prüfsumme |
| `chunks` | Text, Position, Sprecher/Absender, `tsvector`, optional Embedding |
| `nodes` / `edges` / `aliases` | Graph mit Provenienz (`pending` → `verified` / `conflict`) |
| `review_queue` | Offene Fakten mit Vorschlag und Beleg |
| `access_log` | Wer hat welches Wissen abgerufen |

**Knotentypen:** `person`, `team`, `department`, `meeting`, `decision`, `action_item`, `topic`, `kpi`, `insight`, `business_entity`, `agent_task`

**Kantentypen:** `ATTENDED`, `DECIDED_IN`, `OWNS`, `AFFECTS_KPI`, `ABOUT_ENTITY`, `SUPERSEDES`, `EVIDENCED_BY`, `RELATED_TO`, `TRIGGERED` (Maßnahme des CIA, über `POST /facts`), `INVESTIGATED_BY` (Insight → Agentenauftrag)

**Namensraum:** `<typ>:<quellschlüssel>`, z. B. `kpi:gmv`, `region:SP`, `department:hr`, `person:leitung-logistik`.

### Zugang (Schema `ops`)

- `guest_sessions`: Token-ID, Zeitpunkt, gekürzter IP-Hash, Ablauf
- `llm_usage`: Aufrufe, Tokens und Kosten der BI-eigenen LLM-Nutzung (Briefing, Extraktion)

## 6. KPI-Registry

```yaml
- key: delivery_time_avg_days
  label: Ø Lieferzeit (Tage)
  department: supply
  origin: real            # real | simulated | mixed
  source: marts.kpi_daily
  grain: day
  unit: days
  direction: lower_is_better
  dimensions: [region, category]
  alert: {method: stl_mad, threshold: 3.5, min_history_days: 56}
  data_class: public
  owner: person:leitung-logistik
```

Neu sind `department` (Pflicht, feste Liste) und `origin`. `registry.validate` prüft zusätzlich, dass jeder Bereich mindestens drei KPIs und einen Owner hat. Alerts auf `ai_ops`-KPIs gehen nur an den Admin, nicht an den CIA (keine Selbstuntersuchung in Schleife).

## 7. Anbindung an das Agentensystem (CIA)

Details zum Agentensystem selbst: [CIA-Plan](docs/central-intelligence-agent-plan.md). Hier steht, was das BI-System dafür bereitstellt.

### Was der CIA vom BI-System bekommt

| Weg | Inhalt |
|---|---|
| Webhook (Outbox) | `insight.v1` (vorhanden), `daily_snapshot.v1` (Tagesabschluss: Simulationsdatum, Ampel je Bereich, offene Insights), später `decision.v1` |
| Werkzeug-API | `departments`, `kpis`, `series`, `breakdown`, `drivers`, `insights`, `search`, `decisions`, `context`; alle lesend, parametrisiert, mit Bereichs-Filter |
| Dienstkonten (Keycloak, Client Credentials) | `cia-agent`: `read:kpi`, `read:knowledge`, `write:facts`, `write:actions` · `cia-eval`: zusätzlich `read:eval` (Ground Truth) |

Der CIA beschränkt jeden Bereichs-Agenten auf die Werkzeuge und den Bereich seines Auftrags. Das BI-System prüft Scopes; die Werkzeuge nehmen nur feste Parameter an.

### Was das BI-System vom CIA bekommt

| Weg | Inhalt |
|---|---|
| CIA-API (gelesen vom Portal) | Läufe, Aufträge, Schritte, Befunde, Lagebericht, Freigabe-Queue, Live-Monitoring |
| `agent_metrics.v1` (gezogen vom Loader `cia_metrics`, täglich) | Tageswerte je Agentenrolle → Bereich `ai_ops` |
| `POST /api/v1/facts` | Ergebnisse als Fakten, Kante `TRIGGERED` |
| `POST /api/v1/actions/sim-ticket` | freigegebene Maßnahme legt ein Ticket im simulierten Unternehmen an (`ops.sim_tickets`) |

### Monitoring der Agenten (Bereich `ai_ops`)

KPIs aus `agent_metrics.v1`: Fehlerrate, Kosten pro Lauf, p95-Laufzeit, mittlere und maximale Delegationstiefe, abgelehnte Spawns (nach Grund), Budgetabbrüche, Falschbefund-Quote (Evaluator gegen Ground Truth), überfällige und nicht abgeschlossene Tasks, Verstöße gegen Leitplanken. Sie laufen durch dieselbe Anomalieerkennung wie jede Abteilung; die Seite ist auch für Gäste sichtbar. Live-Werte (laufende Läufe, Queue) liest das Portal direkt aus der CIA-API.

### Verknüpfung Insight ↔ Wissen

Für jedes Insight sucht der Verknüpfer Entscheidungen, Meetings und Aufgaben zu denselben KPIs oder Entitäten im Zeitfenster davor (Start: 60 Tage) und ordnet sie per Suche. Treffer über der Schwelle werden als `RELATED_TO` gespeichert und im Kontextpaket `context.v1` ausgeliefert, immer als „möglicher Kontext“, nie als Ursache.

### Briefing

Das vorhandene KPI-Briefing (Zahlen-Leitplanke) läuft über Mistral weiter und ist der Ausfallmodus. Sobald der CIA einen Lagebericht liefert, zeigt das Cockpit diesen an erster Stelle.

## 8. Datenklassen und LLM-Routing

| `data_class` | Beispiele | Erlaubte Modelle |
|---|---|---|
| `public` | gesamte Simulation, Olist-Kennzahlen, synthetischer Korpus, Agentenläufe | alle konfigurierten Provider |
| `internal` | Admin-Einstellungen, Kosten, Zugriffsprotokolle | EU-Provider des Admins |
| `confidential` | echte Unternehmensdaten (heute keine) | nur lokal; ohne lokales Modell gesperrt |

- Pflichtfeld auf Dokumenten, Chunks, Knoten, Events und Registry-Einträgen.
- Ein Prompt erbt die höchste Datenklasse seiner Bestandteile; die LLM-Schicht erzwingt das Routing (`LLMRoutingError`, vorhanden). Der CIA wendet dieselbe Regel an.
- **Mistral kostenlose Stufe:** Eingaben können zum Training genutzt werden; deshalb nur `public`. Bedingungen vor dem Einbau prüfen.
- **MCP:** Datenklassen und Werkzeuge hängen am Token. Admin: bis `internal`; sonst nur `public` (heutiges Verhalten).

## 9. Zugänge und Rollen

| | Gast | Admin |
|---|---|---|
| Einstieg | Startseite → „Als Gast fortfahren“ → Turnstile-Prüfung im Backend → Gast-Token (2 h, RS256, Schlüssel per JWKS veröffentlicht, Audience BI- und CIA-API) | Keycloak-Login mit MFA (TOTP), keine Selbstregistrierung |
| Sieht | alle Bereiche, Cockpit, AI Ops, Agentenläufe, Lageberichte, Wissen | alles, dazu Kosten, Protokolle, Einstellungen |
| Darf | lesen; wenige Fragen an den zentralen Agenten (Kontingent im CIA, Start: 5 pro Gast und Tag) | Simulation vorspulen und Szenarien injizieren, Maßnahmen freigeben, Agenten konfigurieren und starten (über CIA-API), Schwellen ändern |
| LLM | – (Fragen beantwortet der CIA mit Mistral) | eigener Provider und Schlüssel (Server-`.env`, nie im UI) |
| Claude/MCP | nein | ja, Connector mit Admin-Scopes |
| Scopes | `read:kpi`, `read:knowledge`, `ask:guest` | zusätzlich `admin:simulation`, `admin:agents`, `admin:actions`, `admin:review` |

- Missbrauchsschutz: Turnstile, Rate-Limit pro IP-Hash und Token, globales Tageslimit; Gastfragen laufen im CIA nur mit Lesewerkzeugen.
- Eine Startseite erklärt das Projekt für Portfolio-Besucher: Idee, Architektur beider Systeme, was echt und was simuliert ist, Links zu den Repos.

## 10. API v1

| Endpoint | Zweck | Scope |
|---|---|---|
| `POST /api/v1/guest/session`, `GET /api/v1/guest/jwks` | Turnstile prüfen, Gast-Token ausstellen; öffentlicher Schlüssel für den CIA | – |
| `GET /api/v1/departments` | Bereiche mit Ampel, Owner, Herkunft | `read:kpi` |
| `GET /api/v1/kpis`, `/kpis/{key}/series`, `/kpis/{key}/breakdown` | Registry und Zeitreihen (vorhanden), Filter `department` | `read:kpi` |
| `GET /api/v1/kpis/{key}/drivers` | Treiberzerlegung nach Dimension | `read:kpi` |
| `GET /api/v1/insights`, `/briefings/latest` | vorhanden | `read:kpi` |
| `GET /api/v1/search`, `/decisions`, `/graph/neighbors`, `/context` | Wissen und Kontextpaket | `read:knowledge` |
| `GET /api/v1/eval/scenarios` | Ground Truth der Szenarien | `read:eval` (nur `cia-eval`) |
| `POST /api/v1/admin/simulation/tick`, `/admin/scenarios` | Vorspulen, Szenario injizieren | `admin:simulation` |
| `POST /api/v1/facts` | Rückkanal, Kante `TRIGGERED` | `write:facts` |
| `POST /api/v1/actions/sim-ticket` | Ticket im simulierten Unternehmen | `write:actions` |
| `GET/POST /api/v1/review` | Review-Queue | `admin:review` |
| `GET /api/v1/health` | vorhanden | – |
| `/mcp` | MCP-Server, Werkzeuge je Token-Rolle | `read:kpi` (+ Admin-Scopes) |
| `/cia/…` | Weiterleitung des Frontend-nginx an die CIA-API (gleiche Origin) | Scopes des CIA |

Die API liest über eine Rolle ohne Schreibrechte auf `marts` und `knowledge`. Rückkanal und Admin-Endpunkte schreiben über eigene Rollen mit Zugriff nur auf ihre Tabellen.

## 11. Verträge

`contracts/` in diesem Repo ist die Quelle der Wahrheit für beide Systeme. Der CIA bindet eine getaggte Version ein und prüft in seiner CI dagegen. Innerhalb einer Hauptversion nur additive Änderungen.

| Vertrag | Richtung | Stand |
|---|---|---|
| `insight.v1` | BI → CIA | eingefroren (Tag `contracts-insight.v1`) |
| `daily_snapshot.v1` | BI → CIA | neu, A0 |
| `task.v1`, `finding.v1` | CIA intern, BI liest (Portal) | neu, A0 |
| `action.v1` | CIA → BI | neu, A0 |
| `agent_metrics.v1` | CIA → BI | neu, A0 |
| `decision.v1`, `context.v1` | BI → CIA | A4 |
| Entitäts-Namensraum | beide | vorhanden |

## 12. Repo-Struktur

```
Business-Intelligence-System/
├── contracts/        # JSON Schemas, Beispiele, Vertragstests (für BI und CIA)
├── ingestion/        # Connector-Interface, Loader (inkl. cia_metrics), Mock-API
├── simulation/       # Treibermodell (YAML), Engine, Szenarien, Szenario-Plan
├── dbt/              # staging, intermediate, marts
├── registry/         # KPI-YAMLs je Bereich, Schema, Validator
├── analytics/        # Anomalie, Injektion, Treiberzerlegung, später Forecast
├── knowledge/        # generator, corpus, parse, index, extract, graph, link
├── llm/              # Provider (Mistral, Anthropic, …), Routing, Leitplanken
├── events/           # Outbox, Dispatcher, E-Mail
├── orchestration/    # Dagster
├── api/              # FastAPI, Werkzeug-API, MCP-Server
├── frontend/         # Portal: Startseite, Bereiche, Cockpit, Agenten, AI Ops, Admin
├── evals/            # Suche, Extraktion, Anomalie-Szenarien
├── infra/            # Compose lokal/VPS, Backup
└── docs/             # Architektur, CIA-Plan, KPI-Glossar
```

## 13. Phasen und Definition of Done

Zeitangaben in Vollzeit-Wochen, bei Teilzeit strecken. Jede Phase endet mit Deploy, Smoke-Test und aktualisiertem Plan. Die CIA-Phasen stehen im CIA-Plan; die Abhängigkeiten zeigt die gemeinsame Roadmap am Ende dieses Abschnitts.

### Erledigt: Woche 1–3 (Meilenstein M1, 2026-10-09)

Pipeline, Registry, Dashboard, Anomalieerkennung, Outbox und E-Mail, Briefing mit Zahlen-Leitplanke, Keycloak, VPS-Deployment, MCP-Connector (nur `public`), tägliches Backup mit geprüftem Restore, `insight.v1` eingefroren.

### A0 – Verträge für das Agentensystem (2–3 Tage) – erledigt 2026-10-09

- `daily_snapshot.v1`, `task.v1`, `finding.v1`, `action.v1`, `agent_metrics.v1` als JSON Schema mit Beispielen und Vertragstests
- Tag `contracts-v3-draft` für den Start des CIA

**DoD:** Alle Beispiele validieren, ein absichtlich gebrochenes Payload lässt den Test fehlschlagen. Der CIA kann die getaggte Version einbinden.

### A1 – Zugang und Portal (ca. 1 Woche)

- Startseite; „Als Gast fortfahren“ mit Turnstile; Gast-Token (RS256, JWKS) und Rollen in der API
- Admin-Rolle mit Pflicht-MFA; Admin-Bereich im Frontend (vorerst: Simulation vorspulen, Kosten)
- Mistral-Provider in der LLM-Schicht, `ops.llm_usage`; Briefing läuft live
- MCP: Rechte nach Token-Rolle; Admin-Connector sieht `internal`

**DoD:** Ein Besucher ist ohne Konto in unter 10 s im Portal; ohne gültige Turnstile-Prüfung gibt es kein Token. Ein Gast-Token kann nichts schreiben und läuft ab. Admin-Login ohne MFA ist nicht möglich. Das Briefing besteht die Zahlen-Leitplanke live. Ein `confidential`-Prompt an Mistral scheitert.

### A2 – Unternehmenssimulation (2–3 Wochen)

- Simulations-Engine mit Treibermodell, Seed, Verzögerungen, Rauschen; Backfill bis zum aktuellen Simulationstag
- Alle zehn Bereiche mit 3–6 KPIs in Registry und Marts; Felder `department`, `origin`
- Szenarien mit Ground Truth (`ops.scenarios`), Admin-Endpunkt, Szenario-Plan
- `GET /departments` mit Ampel; `daily_snapshot.v1` in der Outbox
- Portal: Navigation nach Bereichen, Bereichsseite aus Registry-Metadaten, GF-Cockpit

**DoD:** Alle zehn Bereiche zeigen plausible Zeitreihen ohne Frontend-Sonderfälle. Ein neuer Bereich ist nur Konfiguration (YAML + dbt-Modell). Gleicher Seed ergibt gleiche Daten. Fünf Szenarien wirken sichtbar in mindestens zwei Bereichen; die Anomalieerkennung findet ≥ 80 % davon.

### A3 – Werkzeug-API und Agenten im Portal (ca. 1 Woche)

- Werkzeug-API (`drivers`, Bereichs-Filter), Dienstkonten `cia-agent` und `cia-eval`, `GET /eval/scenarios`
- CIA als Dispatcher-Empfänger; nginx-Route `/cia/`; Gast-Token gilt in der CIA-API
- Portal: Agenten-Seiten (Lagebericht, Läufe als Zeitleiste, Befunde mit Belegen), Freigabe-Queue im Admin-Bereich
- Loader `cia_metrics` und Bereich `ai_ops`; `POST /actions/sim-ticket`, `ops.sim_tickets`

**DoD:** Ein Dienstkonto ohne `read:eval` bekommt keine Ground Truth. Ein CIA-Lauf erscheint im Portal mit allen Schritten und Belegen. AI-Ops-KPIs werden täglich geladen und von der Anomalieerkennung überwacht; ihre Alerts gehen nur an den Admin. Eine freigegebene Maßnahme erzeugt genau ein Ticket.

**Meilenstein M2 (mit CIA C2):** öffentlich vorzeigbares Agentic BI: Gast sieht zehn Bereiche, Lagebericht des zentralen Agenten und die Arbeit der Bereichs-Agenten.

### A4 – Wissen als Kontext (ca. 2 Wochen)

- Korpus-Generator (Deutsch) an Simulation und Szenarien gekoppelt; Parser; Chunking; Volltextsuche; optional Embeddings nach Messung
- Extraktion über Mistral, Entitätsauflösung, Provenienz, Review-Queue
- Verknüpfung Insight ↔ Wissen, `context.v1`, `decision.v1`; Werkzeuge `search`, `decisions`, `context`
- Dagster-Sensor, Backup um `knowledge` erweitert

**DoD:** Auf 20 Testfragen steht die richtige Quelle bei ≥ 80 % in den Top 5. Extraktion auf 30 markierten Dokumenten: Precision ≥ 0,8, Recall ≥ 0,7, kein Fakt ohne Beleg. In den CIA-Szenario-Evals verbessert der Kontext die Ursachen-Treffer messbar.

### A5 – Admin-Werkzeuge und Rückkanal (ca. 1 Woche)

- MCP für Admin um Szenarien, Suche, Kontext und CIA-Steuerung erweitern
- `POST /facts`, Review im UI, `decision.v1`, `context.v1` und die A0-Verträge einfrieren

**DoD:** Über Claude kann ich als Admin ein Szenario injizieren, einen CIA-Lauf starten und den Befund lesen; ein Gast-Token kann das nicht. Ein geschriebener Fakt erscheint im Graph.

**Meilenstein M3 (mit CIA C5):** vollständiges Agentic BI mit Wissen, Spawning, Monitoring und Maßnahmen.

### Phase 2 – Ausbau

- Geschlossener Kreis: angenommene Maßnahmen wirken als Szenario auf die Simulation
- Fragen in natürlicher Sprache über SQL (sqlglot, nur `SELECT`) und Wissen
- Forecasting mit Konfidenzband (`forecast_deviation`)
- Weitere Logins (Google, GitHub), Dokument-Upload

### Phase 3 – Generalitätsnachweis

Zweite Domäne mit eigenem Treibermodell, Registry und Korpus. **DoD:** kein Commit in `analytics/`, `llm/`, `events/`, `api/`, `frontend/`, `knowledge/` und im CIA nötig.

### Gemeinsame Roadmap

| Schritt | BI-System | CIA | Voraussetzung |
|---|---|---|---|
| 1 | A0 Verträge | – | M1 |
| 2 | A1 Zugang und Portal | C0 Gerüst, C1 zentraler Agent (gegen vorhandene API) | A0 |
| 3 | A2 Simulation | C1 fertigstellen | A1 / C0 |
| 4 | A3 Werkzeug-API, Agenten im Portal | C2 Bereichs-Agenten | A2 |
| | **M2** | | |
| 5 | – | C3 Spawning, C4 Monitoring und Evals | A3 |
| 6 | A4 Wissen | – | A3 |
| 7 | A5 Admin und Rückkanal | C5 Maßnahmen mit Freigabe | A4, C4 |
| | **M3** | | |

## 14. Betrieb auf dem VPS

- Compose-Projekt `bis`: `postgres`, `dagster-webserver`, `dagster-daemon`, `api`, `mcp`, `frontend`, `keycloak`, `mock-marketing-api`. Kein Ollama.
- Compose-Projekt `cia` (eigenes Repo): `cia-api`, `cia-worker`; Datenbank `cia` auf der BI-Postgres-Instanz mit eigener Rolle ohne Zugriff auf `warehouse`; gemeinsames internes Docker-Netz nur für Postgres und die API-Aufrufe. n8n erst, wenn der RAM es zulässt.
- Ressourcen (Messung 2026-10-09): 4 vCPU, 7,6 GB RAM, davon 4,2 GB frei bei laufendem Stack. Jeder neue Dienst mit Speicherlimit; Budget für den CIA: höchstens 1 GB.
- Caddy mit zwei Routen (`business`, `auth`); der CIA ist nur über das Frontend-nginx (`/cia/`) erreichbar. Keycloak-Admin-Konsole von außen gesperrt, Dagster nur per SSH-Tunnel.
- Backup täglich (`ops`, `marts`, ab A4 `knowledge`, Datenbanken `keycloak` und `cia`), Restore geprüft.
- Details: [docs/deployment.md](docs/deployment.md)

## 15. Datenschutz

- Im Portfolio-Betrieb nur synthetische Personen und Inhalte; Gäste hinterlassen keine Konten, nur gekürzte IP-Hashes für das Rate-Limit (Aufbewahrung 7 Tage).
- Gastfragen werden mit Antwort für Kontingent und Missbrauchsprüfung gespeichert (30 Tage); die Startseite weist darauf hin.
- Turnstile und Mistral in der Datenschutzerklärung der Portfolioseite nennen.
- Für echte Daten gilt weiter: Rechtsgrundlage, Zweckbindung, Beschäftigtendatenschutz vorab klären; nicht Teil dieses Plans.

## 16. Checkliste vor A1

- [x] Ressourcen auf dem VPS gemessen; Entscheidung: kein lokales Modell
- [x] Route, Subdomains, TLS, Keycloak
- [ ] Mistral-Konto (kostenlose Stufe), Nutzungsbedingungen und Limits prüfen
- [ ] Cloudflare-Turnstile-Widget für die Subdomain `business` anlegen
- [ ] Olist-Lizenz gegenlesen (öffentlicher Betrieb)
- [ ] SMTP-Anbieter für Admin-Alerts
- [ ] Datenschutzhinweis auf der Portfolioseite ergänzen

## 17. Risiken

| Risiko | Gegenmaßnahme |
|---|---|
| Umfang zu groß für eine Person | Generisches Bereichsmodell statt zehn Sonderlösungen; jede Phase mit harter DoD und eigenem Deploy; CIA startet erst nach A0 |
| Verträge driften zwischen den Repos | Quelle nur in `contracts/` hier, getaggte Versionen, Vertragstests in beiden CIs |
| Simulation wirkt konstruiert | Aus echten Olist-Treibern ableiten, Verzögerung und Rauschen, offen kennzeichnen |
| Agenten sehen die Lösung | Ground Truth nur über `read:eval`, nur für das Evaluator-Konto |
| Kostenlose LLM-Stufe begrenzt oder entfällt | Läufe nachts und gecacht; Ausfallmodus ohne LLM; Provider austauschbar |
| Gäste missbrauchen das Kontingent | Turnstile, Rate-Limit, globales Tageslimit, nur Lesewerkzeuge |
| Admin-Zugang kompromittiert | MFA, keine Selbstregistrierung, Admin-Konsole gesperrt, Schlüssel nur in der Server-`.env` |
| Agenten untersuchen sich selbst in Schleife | `ai_ops`-Alerts nur an den Admin |
| RAM reicht nicht für zwei Stacks | Speicherlimits, CIA ohne n8n, gemeinsame Postgres-Instanz |

## 18. Offene Punkte

1. Embeddings: nur wenn die Volltextsuche in A4 die DoD verfehlt
2. Zweite Domäne für Phase 3
3. Domain der Portfolioseite und Einbindung (Link oder eingebettete Vorschau)
4. Echte Ticket-Ziele (z. B. GitHub Issues) zusätzlich zum simulierten Ticket-System, siehe CIA-Plan
