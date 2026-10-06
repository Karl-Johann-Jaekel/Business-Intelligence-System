# Business-Intelligence-System

End-to-end BI platform for data ingestion, ELT, KPI analytics and (from week 2) dashboards,
anomaly detection and AI briefings. Reference domain: the public Olist e-commerce dataset,
replayed day by day through a simulation clock.

Plan and decisions: [plan.md](plan.md) · Architecture: [docs/architecture.md](docs/architecture.md) ·
KPI glossary: [docs/kpi-glossary.md](docs/kpi-glossary.md) ·
Company Brain contract: [docs/company-brain-interface.md](docs/company-brain-interface.md)

## Status

| Phase | Scope | State |
|---|---|---|
| Week 1 – Foundation | Postgres, 4 connectors, dbt star schema + KPI marts, Dagster, KPI registry, CI | done |
| Week 2 – Pipeline & dashboard | Schedule, asset checks, FastAPI, React | open |
| Week 3 – Insights & operations | Anomaly detection, alerts, AI analyst, Keycloak, VPS | open |

## Quick start

Requirements: Docker, Python 3.11–3.13.

```bash
python -m venv .venv
.venv/Scripts/pip install -e ".[dev]"     # Linux/macOS: .venv/bin/pip
.venv/Scripts/bis up                      # containers + data bootstrap + Dagster UI on :3000
```

`bis up` starts Postgres (`127.0.0.1:55432`) and the mock marketing API (`127.0.0.1:8101`),
downloads Olist, seeds the ERP database, generates synthetic data, sets the simulation clock
to 2018-01-01 and launches `dagster dev`. In the UI, materialize all assets once to backfill.

Without the UI:

```bash
bis up --no-dagster
bis materialize          # ingestion + dbt build for the current simulation date
bis tick --days 5        # advance the clock one day at a time and run the pipeline
bis clock show
```

## Sources

| Source | Type | Content | Data |
|---|---|---|---|
| ERP | Postgres database `erp` | orders, items, payments, customers, sellers, products | real (Olist) |
| Legacy export | CSV | reviews, geolocation, category translation | real (Olist) |
| Marketing | REST API (mock) | sessions and ad spend per day and channel | synthetic |
| Controlling | Excel | monthly budget per category | synthetic |

Synthetic data is generated with a fixed seed and labelled per KPI in the registry
(`data_origin`). See [docs/kpi-glossary.md](docs/kpi-glossary.md).

## Development

```bash
pytest -q                          # unit tests
ruff check . && ruff format .      # lint / format
python -m registry.validate        # registry schema + consistency with dbt
cd dbt && dbt build --profiles-dir .   # requires the running warehouse
```

## Data license

The Olist dataset is published under CC BY-NC-SA 4.0 by Olist on Kaggle. It is downloaded at
setup time and never committed to this repository.
