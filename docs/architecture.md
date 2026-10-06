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
Dagster: ein Multi-Asset je Quelle → dbt-Assets → Asset Check "kpi_registry_coverage"
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
