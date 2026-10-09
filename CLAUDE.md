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
- Anomalie-Auswertung: `.venv/Scripts/python -m analytics.evaluate --start 2017-06-01` (~1 min)
- Anomalie-Backfill: `.venv/Scripts/python -m analytics.detect --from 2017-10-01 --to 2018-01-11`
- Mails ansehen: Mailpit http://127.0.0.1:8025
- Dashboard (Container): http://127.0.0.1:8103 · Keycloak: http://127.0.0.1:8180 (Login `demo`, Passwort in `infra/.env`)
- MCP lokal: http://127.0.0.1:8103/mcp · Connector-Daten: `bis claude-connector` (gibt ein Secret aus)
- DB-Shell: `docker exec -it bis-postgres-1 psql -U bis -d warehouse`

## Fallstricke

- Host `127.0.0.1`, nicht `localhost` (IPv6-Connect hängt auf Windows).
- Dagster-Storage braucht `postgresql+psycopg2` (SQLAlchemy 2.1 nimmt sonst psycopg 3).
- dagster-dbt keyt Modelle mit Schema-Präfix: `AssetKey(["marts", "kpi_daily"])`.
- Neuer KPI: Eintrag in `registry/kpis/*.yaml` **und** in `accepted_values` von `kpi_key`
  in `dbt/models/marts/_marts.yml`; `registry.validate` prüft beides.
- Olist-Daten nie committen (`data/` ist ignoriert).
- Keine Passwort-Defaults in Code oder Compose; neue Secrets als `generated-by-bis-setup` in
  `infra/.env.example`, `bis setup` ergänzt `infra/.env`. Deren Inhalt nie ausgeben.
- LLM-Aufrufe immer mit `data_class`; externer Provider nur `public` (`LLMRoutingError`).
- Event-Formate ändern = `contracts/` zuerst, `tests/test_contracts.py` muss grün bleiben.
- MCP: nur `public`-Daten (Admin-Token: bis `internal`); nginx muss `Host $http_host` (mit Port) weiterreichen, sonst 421.
- Gäste sehen nur `public`. Turnstile-Test-Secrets nur lokal (`BIS_GUEST_ALLOW_TEST_KEYS=true`), sonst bleibt der Gastmodus aus.
- Admin-MFA hängt am Realm-Flow `browser-bis`; Admin-Scopes nur mit Rolle `bis-admin`. Keycloak-Nutzer brauchen eine E-Mail, sonst fragt der Login danach.
- Python-Cookiejar schickt keine Cookies an `127.0.0.1` zurück (Keycloak-Tests: Header setzen).
- Schwellen in der Registry nur mit `analytics.evaluate` ändern (Bericht in docs/ committen).
- SQL-Kommentare in psycopg-Strings: kein `%` (wird als Platzhalter gelesen).
- Ohne LLM-Zugangsdaten ist `insights/briefing` „skipped“, das ist kein Fehler.
- Registry-Änderung → API-Image neu bauen (`up -d --build api`), die Registry liegt im Image.
- Headless-Edge-Screenshots: Fenster ist min. ~490 px breit; Mobilbreite per iframe auf
  derselben Origin testen.
