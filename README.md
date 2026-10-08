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
| Week 2 – Pipeline & dashboard | Daily schedule with retries, asset checks, read-only FastAPI, React dashboard | done |
| Week 3 – Insights | Anomaly detection (calibrated), outbox + dispatcher, email alerts, AI analyst with number guardrail | done |
| Week 3 – Operations | Keycloak login (local), CI image builds, no secrets in the repo | done |
| Week 3 – VPS deployment | Reverse-proxy route, Keycloak realm, subdomain | open (needs VPS details) |
| K1–K4 – Knowledge layer | Plan v2; starts after milestone M1 | open |

## Quick start

Requirements: Docker, Python 3.11–3.13.

```bash
python -m venv .venv
.venv/Scripts/pip install -e ".[dev]"     # Linux/macOS: .venv/bin/pip
.venv/Scripts/bis up                      # containers + data bootstrap + Dagster UI on :3000
```

`bis up` starts Postgres (`127.0.0.1:55432`), the mock marketing API (`127.0.0.1:8101`) and the
read-only BIS API (`127.0.0.1:8102`),
downloads Olist, seeds the ERP database, generates synthetic data, sets the simulation clock
to 2018-01-01 and launches `dagster dev`. In the UI, materialize all assets once to backfill.

Dashboard (Vite dev server, proxies `/api` to the API container):

```bash
cd frontend && npm install && npm run dev   # http://127.0.0.1:5173
```

Unattended replay: the Dagster schedule `simulated_day` advances the clock by one day per tick.
It is off by default; enable it with `BIS_SCHEDULE_ENABLED=true` (and e.g.
`BIS_SCHEDULE_CRON="*/3 * * * *"` to fast-forward).

Without the UI:

```bash
bis up --no-dagster
bis materialize          # ingestion + dbt build for the current simulation date
bis tick --days 5        # advance the clock one day at a time and run the pipeline
bis clock show
```

## Insights

- Anomalies per registry rule (`stl_mad`, `threshold`); evaluation with injected anomalies:
  86 % hit rate, 1.6 false alarms per KPI and simulated month
  ([docs/anomaly-evaluation.md](docs/anomaly-evaluation.md)).
- Every finding is an `insight.v1` event in the outbox `ops.events`, delivered by the dispatcher
  to the consumers in `events/consumers.yaml` (email; webhooks with HMAC signature).
- Local alert emails go to Mailpit: http://127.0.0.1:8025
- Daily AI briefing via Anthropic (`ANTHROPIC_API_KEY`); every number must occur in the computed
  input, otherwise the draft is discarded and regenerated. Without credentials it is skipped.

## Login and secrets

- The dashboard (`http://127.0.0.1:8103`, or Vite on `:5173`) requires a login via Keycloak
  (`http://127.0.0.1:8180`, realm `bis`). The API checks the token and the scope `read:kpi`
  per endpoint; `/api/v1/health` is open.
- No passwords live in the repository. `bis up` / `bis setup` create the git-ignored
  `infra/.env` from [infra/.env.example](infra/.env.example) with random values, including the
  demo user `demo` (password: `BIS_DEMO_PASSWORD` in `infra/.env`).
- LLM calls are routed by data class: the external provider only receives `public` data.

## Contracts

Event and ID formats for other systems: [contracts/](contracts/README.md) (JSON Schema,
examples, versioning rules).

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
pytest -q                          # unit + API tests (API integration tests need the warehouse)
docker compose -f infra/docker-compose.yml exec api pytest -q tests/api   # API tests in the container
cd frontend && npm test && npm run lint && npm run build
ruff check . && ruff format .      # lint / format
python -m registry.validate        # registry schema + consistency with dbt
cd dbt && dbt build --profiles-dir .   # requires the running warehouse
```

## Data license

The Olist dataset is published under CC BY-NC-SA 4.0 by Olist on Kaggle. It is downloaded at
setup time and never committed to this repository.
