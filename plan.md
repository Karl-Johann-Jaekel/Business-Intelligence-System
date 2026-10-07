# PLAN.md – Business-Intelligence-System

Stand: 2026-10-06 · Status: Woche 1 und 2 umgesetzt, Woche 3 offen

## 1. Zweck und Einordnung

End-to-End Data/AI-System, das Daten aus mehreren Quellen sammelt, transformiert, zu Business-Kennzahlen verdichtet, analysiert, visualisiert und Auffälligkeiten selbstständig meldet.

- **Primärziel:** Portfolio-Projekt, das den Einsatz in einem echten Unternehmen simuliert.
- **Rolle im Gesamtbild:** quantitatives Organ des späteren Company Brain (Repo `Central-Intelligence-Agent`). Das qualitative Organ ist Hive Mind.
- **Leitprinzip:** domänenunabhängiger Kern, Olist (E-Commerce) als Referenzdomäne. Keine Abstraktion, die Olist nicht sofort nutzt.

## 2. Festgelegte Entscheidungen

| Thema | Entscheidung |
|---|---|
| Repo-Name | `Business-Intelligence-System` |
| Domäne | E-Commerce, öffentlicher Olist-Datensatz |
| Warehouse | Postgres (Docker), identisch lokal und auf dem VPS |
| Transformation | dbt (dbt-postgres) |
| Orchestrierung | Dagster (Assets, Schedules, Sensoren, Asset Checks) |
| Backend / Frontend | FastAPI / React + Vite + TypeScript |
| Alerts | E-Mail als primärer Kanal |
| Deployment | vorhandener VPS, auf dem Hive Mind bereits läuft |
| MVP-KI | Anomalieerkennung + AI-Analyst; NL-Querying und Forecasting in Phase 2 |
| Company Brain | separates Repo, Zusammenführung später über einen dokumentierten Vertrag |

## 3. Architektur

```
Quellen             Ingestion        Warehouse (Postgres)                       Nutzung
CSV  ─┐
DB   ─┼─> Connectoren ─> raw ─> dbt: staging ─> intermediate ─> marts ─┬─> FastAPI ─> React-Dashboard
API  ─┤                                                  │             ├─> Anomalie / Forecast
XLSX ─┘                                            KPI-Registry ───────┼─> AI-Analyst (LLM-Schicht)
                                                                       └─> Outbox ─> Webhook / E-Mail

Dagster orchestriert alle Schritte als Assets (Schedule, Sensoren, Asset Checks).
```

| Schicht | Umsetzung |
|---|---|
| Ingestion | Connector-Interface in Python (`extract()`, Inkrementlogik, Ladeprotokoll), ein Loader pro Quelle |
| Warehouse | Schemas `raw`, `staging`, `intermediate`, `marts`, `ops` (Ladeprotokoll, Outbox) |
| Transformation | dbt-Modelle, Tests, Makros; in Dagster über `dagster-dbt` als Assets eingebunden |
| Semantic Layer | KPI-Registry als YAML, per Pydantic validiert, per API lesbar |
| Analytik | STL-Zerlegung + robuster Z-Score (MAD) auf Residuen; Phase 2: Forecast mit `statsforecast` |
| KI | Provider-agnostische LLM-Schicht; MVP mit einem Provider (Anthropic), Phase 2: OpenAI, Mistral, Ollama |
| Events | Outbox-Tabelle `ops.insights` + Dispatcher; E-Mail ist der erste Consumer |
| Auth | OIDC gegen das Keycloak des Hive Mind (eigene Clients `bis-frontend`, `bis-api`) |

## 4. Datenbasis und Quellen

| Quelltyp | Inhalt | Echt / synthetisch |
|---|---|---|
| CSV ("Legacy-Export") | Olist: Bewertungen, Geodaten, Kategorie-Übersetzung | echt |
| Datenbank ("ERP") | Olist in separatem Postgres-Schema: Bestellungen, Positionen, Zahlungen, Kunden, Verkäufer, Produkte | echt |
| REST-API ("Marketing") | Mock-API (FastAPI): Sessions und Werbeausgaben pro Tag und Kanal | synthetisch |
| Excel ("Controlling") | Monatsbudgets pro Kategorie | synthetisch |

Drei Punkte, die den Plan prägen:

1. **Replay statt Echtzeit.** Die Olist-Daten sind historisch (ca. 2016–2018). Eine Simulationsuhr (`sim_date`) gibt pro Pipeline-Lauf einen weiteren Tag frei. Die Historie bis zum Starttag wird einmalig per Backfill geladen. Für Demos gibt es einen Schnellvorlauf.
2. **Synthetik klar kennzeichnen.** Olist enthält keine Besuchs- und keine Einkaufspreisdaten. Conversion Rate (Bestellungen / Sessions), ROAS und Budgetabweichung beruhen deshalb auf den synthetischen Quellen. Im README und im KPI-Glossar wird das je Kennzahl ausgewiesen.
3. **Lizenz.** Olist steht meines Wissens unter CC BY-NC-SA 4.0. Vor dem Start prüfen, Daten nicht ins Repo committen, stattdessen Download-Skript.

## 5. Datenmodell

- **Fakten:** `fct_orders`, `fct_order_items`, `fct_payments`, `fct_marketing_daily`
- **Dimensionen:** `dim_customer`, `dim_product`, `dim_seller`, `dim_region`, `dim_date`
- **Marts:** `kpi_daily` (eine Zeile pro Tag und KPI, optional pro Dimension), `kpi_monthly`, `budget_vs_actual`

Start-KPIs (alle in der Registry):

| KPI | Quelle |
|---|---|
| Umsatz (GMV) | echt |
| Anzahl Bestellungen | echt |
| Ø Warenkorbwert | echt |
| Frachtkostenquote | echt |
| Stornoquote | echt |
| Ø Lieferzeit, Pünktlichkeitsquote | echt |
| Ø Bewertung | echt |
| Neukunden vs. Wiederkäufer | echt |
| Conversion Rate, ROAS | teils synthetisch |
| Budgetabweichung | teils synthetisch |

## 6. KPI-Registry

Ein Eintrag beschreibt eine Kennzahl so, dass Dashboard, Anomalieerkennung, AI-Analyst und später Agenten ohne KPI-spezifischen Code auskommen.

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
  owner: operations
```

Alert-Methoden: `stl_mad` (Ausreißer in Zeitreihen) und `threshold` (feste Grenze, z. B. für die Budgetabweichung auf Monatsbasis). Der Block `alert` ist optional; ein KPI ohne Schwelle wird angezeigt, aber nicht überwacht.

## 7. Insights und Events

Jede Anomalie, jedes Briefing und später jede Forecast-Abweichung wird als Event in `ops.insights` geschrieben und vom Dispatcher an eine konfigurierbare Liste von Empfängern zugestellt (Webhook mit HMAC-Signatur, Wiederholung mit Backoff, Idempotenz über `insight_id`). Empfänger im MVP ist der E-Mail-Consumer; später kommen Hive Mind und der Central-Intelligence-Agent als weitere Einträge dazu, ohne Änderung am Dispatcher.

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
  "summary": "Kurzbeschreibung in Klartext",
  "data_class": "public | internal | confidential",
  "created_at": "ISO-8601"
}
```

**Entitäts-IDs:** `<typ>:<quellschlüssel>`, also `customer:…`, `product:…`, `seller:…`, `region:SP`, `category:…`, `kpi:<registry-key>`. Diese IDs sind der gemeinsame Namensraum mit Hive Mind. Das Feld `kpi` im Event enthält den Registry-Schlüssel ohne Präfix; als Entitäts-ID lautet derselbe KPI `kpi:<registry-key>`.

**AI-Analyst:** erhält ausschließlich berechnete Werte (KPIs, Abweichungen, Top-Treiber nach Dimension), liefert strukturiertes JSON (Zusammenfassung, Befunde mit Belegverweis, Handlungsvorschläge). Leitplanke: Jede Zahl im Text muss in den Eingabedaten vorkommen, sonst wird das Briefing verworfen und neu erzeugt.

## 8. API v1

| Endpoint | Zweck |
|---|---|
| `GET /api/v1/kpis` | Registry (Semantic Layer) |
| `GET /api/v1/kpis/{key}/series` | Zeitreihe, Parameter `from`, `to`, `grain`, `dim` |
| `GET /api/v1/insights` | Insights, Parameter `since`, `type`, `severity` |
| `GET /api/v1/briefings/latest` | Aktuelles Briefing |
| `POST /api/v1/query` | NL-Querying (Phase 2) |
| `GET /api/v1/health` | Status, letzter erfolgreicher Lauf |

Die API liest über eine Read-only-Datenbankrolle, die nur `marts` und `ops.insights` sieht.

## 9. Repo-Struktur

```
Business-Intelligence-System/
├── ingestion/        # Connector-Interface, Loader pro Quelle, Mock-API
├── dbt/              # staging, intermediate, marts, tests, Makros
├── registry/         # KPI-YAMLs, Pydantic-Schema, Validator
├── orchestration/    # Dagster: Assets, Schedules, Sensoren, Checks
├── analytics/        # Anomalie, Anomalie-Injektion für Tests, später Forecast
├── llm/              # Provider-Abstraktion, Prompt-Builder, Zahlen-Leitplanke
├── events/           # Outbox, Dispatcher, E-Mail-Consumer
├── api/              # FastAPI
├── frontend/         # React
├── infra/            # docker-compose (lokal, VPS), .env.example
├── docs/             # Architektur, KPI-Glossar, company-brain-interface.md, ADRs
├── tests/
└── .github/workflows/
```

## 10. Phasen und Definition of Done

dbt und Dagster sind beide neu. Der MVP ist auf drei Wochen in Vollzeit ausgelegt; bei Teilzeit entsprechend strecken.

### Woche 1 – Fundament
- Repo, Docker-Postgres, Download-Skript, Simulationsuhr
- Connector-Interface und vier Loader nach `raw`, Ladeprotokoll in `ops`
- dbt: Staging, Star-Schema, `kpi_daily`; dbt-Tests (unique, not_null, relationships, accepted_values)
- Dagster: Ingestion-Assets + dbt-Assets, lokal mit `dagster dev`
- KPI-Registry mit Validator; `docs/company-brain-interface.md` als Entwurf

**DoD:** Ein Befehl startet die Umgebung. Ein Materialisierungslauf in Dagster füllt `raw` bis `marts` fehlerfrei. `dbt build` ist grün. Mindestens 8 KPIs stehen in Registry und `kpi_daily`. CI validiert Registry und dbt-Projekt.

### Woche 2 – Pipeline und Dashboard
- Täglicher Schedule, Asset Checks für Aktualität und Zeilenzahlen, Wiederanlauf nach Fehlern
- FastAPI: Registry-, Series- und Health-Endpoints, Read-only-Rolle, pytest
- React: KPI-Cards, Trendcharts, Zeitraum- und Dimensionsfilter, Abweichungsansicht, alles aus Registry-Metadaten gerendert

**DoD:** Fünf simulierte Tage laufen ohne manuellen Eingriff durch. Ein neuer Registry-Eintrag erscheint ohne Frontend-Änderung im Dashboard. API-Tests sind grün.

### Woche 3 – Insights und Betrieb
- Anomalieerkennung als Asset (Methoden `stl_mad` und `threshold`), schreibt `insight.v1` in die Outbox
- Anomalie-Injektion als Testwerkzeug, Auswertung von Trefferquote und Fehlalarmen
- Dispatcher + E-Mail-Alert (HTML: KPI, Abweichung, Link ins Dashboard)
- AI-Analyst: tägliches Briefing im Dashboard und per Mail
- Login über Keycloak, Deployment auf dem VPS, CI baut Images
- README mit Architekturdiagramm, Screenshots, KPI-Glossar

**DoD:** Injizierte Anomalien werden erkannt und per Mail gemeldet (Startziel: mindestens 80 % Trefferquote, höchstens 2 Fehlalarme pro simuliertem Monat; danach kalibrieren). Das Briefing besteht die Zahlen-Leitplanke. Das Dashboard ist unter einer Subdomain nur nach Login erreichbar.

### Phase 2 – Ausbau (ca. 3 Wochen)
- NL-Querying: Registry und Schema als Kontext, SQL-Erzeugung, Prüfung mit `sqlglot` (nur `SELECT` auf `marts`), Zeilenlimit, Statement-Timeout, Ergebnis mit Chart
- Forecasting mit Konfidenzband, Insight-Typ `forecast_deviation`
- LLM-Schicht vollständig: OpenAI, Mistral, Ollama, Routing nach `data_class`, eigener Schlüssel pro Nutzer
- Weitere Logins über Keycloak-Identity-Brokering (Google, GitHub; "Sign in with ChatGPT", falls OpenAI die Client-Registrierung für Einzelentwickler öffnet)
- Datenqualitätsansicht aus dbt-Tests und Asset Checks

### Phase 3 – Generalitätsnachweis (ca. 1 Woche)
Zweite Domäne (z. B. Superstore oder ein SaaS-Datensatz) nur über neue Loader, neue Marts und eine neue Registry-Datei.

**DoD:** Kein Commit in `analytics/`, `llm/`, `events/`, `api/`, `frontend/` für die zweite Domäne nötig.

### Phase 4 – Company Brain
Siehe `PLAN.md` im Repo `Central-Intelligence-Agent`. Voraussetzung aus diesem Repo: Woche 3 abgeschlossen, Vertrag `insight.v1` eingefroren.

## 11. Betrieb auf dem VPS

- Eigenes Compose-Projekt, eigener Postgres-Container (Warehouse + Dagster-Metadaten in getrennten Datenbanken); keine geteilte Datenbank mit Hive Mind
- Dienste: `postgres`, `dagster-webserver`, `dagster-daemon`, Code-Location, `api`, `frontend`, `mock-marketing-api`
- Anschluss an den bestehenden Reverse Proxy und das bestehende Keycloak über ein gemeinsames Docker-Netz
- Dagster-Oberfläche nicht öffentlich, nur hinter Login oder per SSH-Tunnel
- Backups: tägliches `pg_dump` der `ops`- und `marts`-Schemas; `raw` ist aus den Quellen reproduzierbar

## 12. Pre-Start-Checkliste

- [ ] Freie Ressourcen auf dem VPS prüfen (`docker stats`); grobe Schätzung für dieses System: 2–3 GB RAM zusätzlich
- [ ] Welcher Reverse Proxy läuft für Hive Mind, und läuft Keycloak bereits produktiv?
- [ ] Subdomain und TLS-Zertifikat
- [ ] Olist-Lizenz gegenlesen
- [ ] SMTP-Anbieter wählen (z. B. Brevo oder Resend), Absenderdomain mit SPF/DKIM
- [ ] API-Schlüssel für den LLM-Provider, Ausgabenlimit setzen
- [x] Aktuelle Versionen von Dagster, dbt und `dagster-dbt` festlegen und pinnen (`pyproject.toml`: Dagster 1.13.25, dagster-dbt 0.29.25, dbt-core 1.12.5, dbt-postgres 1.11.0)

## 13. Risiken

| Risiko | Gegenmaßnahme |
|---|---|
| Lernkurve dbt + Dagster sprengt Woche 1 | Erst dbt allein lauffähig, dann in Dagster einhängen; Partitionierung erst nach dem MVP |
| Zu früh verallgemeinert | Regel: Abstraktion nur, wenn Olist sie heute nutzt |
| Fehlalarme entwerten die Alerts | Schwellen pro KPI in der Registry, Mindesthistorie, Auswertung mit injizierten Anomalien |
| LLM erfindet Zahlen | Nur berechnete Werte als Eingabe, Zahlen-Leitplanke, strukturierte Ausgabe |
| VPS zu knapp | Vor dem Start messen; notfalls Dagster-Läufe nachts und Ollama zeitlich entkoppeln |
| Synthetische Daten wirken unglaubwürdig | Transparent kennzeichnen, Generator mit Saisonalität und Rauschen, Seed dokumentieren |

## 14. Offene Punkte

1. Subdomain-Schema für BI-System, Hive Mind und später den Central-Intelligence-Agent
2. Zweite Domäne für Phase 3
3. Reihenfolge nach dem MVP: Phase 2 dieses Repos oder zuerst die Hive-Mind-Erweiterung (Empfehlung im Plan des Central-Intelligence-Agent)
