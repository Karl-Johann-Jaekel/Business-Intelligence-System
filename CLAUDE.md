# Business-Intelligence-System

Plan: `plan.md`. Architektur: `docs/architecture.md`. Python 3.13 venv in `.venv`.

## Befehle

- Setup: `py -3.13 -m venv .venv && .venv/Scripts/pip install -e ".[dev]"`
- Umgebung: `.venv/Scripts/bis up --no-dagster` (Docker Desktop muss laufen)
- Pipeline einmal: `.venv/Scripts/bis materialize` (dauert einige Minuten)
- Tag vorspulen: `.venv/Scripts/bis tick --days N`
- Tests: `.venv/Scripts/python -m pytest -q`
- Lint: `.venv/Scripts/ruff check . && .venv/Scripts/ruff format --check .`
- Registry: `.venv/Scripts/python -m registry.validate`
- dbt direkt: `cd dbt && ../.venv/Scripts/dbt build --profiles-dir .`
- API-Tests im Container: `docker compose -f infra/docker-compose.yml exec api pytest -q tests/api`
- Frontend: `cd frontend && npm run dev` (Port 5173) · `npm test` · `npm run lint` · `npm run build`
- DB-Shell: `docker exec -it bis-postgres-1 psql -U bis -d warehouse`

## Fallstricke

- Host `127.0.0.1`, nicht `localhost` (IPv6-Connect hängt auf Windows).
- Dagster-Storage braucht `postgresql+psycopg2` (SQLAlchemy 2.1 nimmt sonst psycopg 3).
- dagster-dbt keyt Modelle mit Schema-Präfix: `AssetKey(["marts", "kpi_daily"])`.
- Neuer KPI: Eintrag in `registry/kpis/*.yaml` **und** in `accepted_values` von `kpi_key`
  in `dbt/models/marts/_marts.yml`; `registry.validate` prüft beides.
- Olist-Daten nie committen (`data/` ist ignoriert).
- Registry-Änderung → API-Image neu bauen (`up -d --build api`), die Registry liegt im Image.
- Headless-Edge-Screenshots: Fenster ist min. ~490 px breit; Mobilbreite per iframe auf
  derselben Origin testen.
