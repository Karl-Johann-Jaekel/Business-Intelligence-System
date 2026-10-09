# Deployment auf dem VPS

Eigenes Compose-Projekt `bis` ([infra/docker-compose.vps.yml](../infra/docker-compose.vps.yml)),
angebunden an den bestehenden Reverse Proxy (Caddy) über das externe Docker-Netz `web`.
Hostnamen, Secrets und Zugangsdaten stehen ausschließlich in `infra/.env` auf dem Server
(git-ignoriert, Rechte 600).

## Dienste

| Dienst | Erreichbar | Speicherlimit |
|---|---|---|
| `frontend` (nginx: SPA + `/api`-Proxy) | `https://$BIS_PUBLIC_HOST` via Caddy (Alias `bis-web`) | 64 MB |
| `keycloak` (Realm `bis`, Datenbank `keycloak`) | `https://$BIS_AUTH_HOST` via Caddy (Alias `bis-auth`); `/admin` von außen gesperrt | 900 MB |
| `api` | nur intern, über das Frontend | 384 MB |
| `postgres` (pgvector; `warehouse`, `erp`, `dagster`, `keycloak`) | nur intern | 1 GB |
| `dagster-webserver` | nur `127.0.0.1:$BIS_DAGSTER_PORT` (SSH-Tunnel) | 768 MB |
| `dagster-daemon` (Schedule `simulated_day`, Läufe) | – | 2 GB |
| `mcp` (MCP-Server für Claude) | `https://$BIS_PUBLIC_HOST/mcp` über das Frontend-nginx | 256 MB |
| `mock-marketing-api` | nur intern | 128 MB |
| `app` (Profil `tools`, Einmalaufgaben) | – | 2 GB |

## Erstinstallation

```bash
# 1. Code auf den Server (Git-Checkout oder tar der getrackten Dateien)
# 2. Secrets erzeugen und VPS-Werte setzen
cd business-intelligence-system
python3 -c "from ingestion.config import ensure_env_file; ensure_env_file()"
#    in infra/.env: BIS_PUBLIC_HOST, BIS_AUTH_HOST setzen; BIS_ALERT_TO leer lassen, bis SMTP steht
chmod 600 infra/.env
# 3. Images bauen und Basisdienste starten
cd infra
docker compose -f docker-compose.vps.yml --env-file .env build
docker compose -f docker-compose.vps.yml --env-file .env up -d postgres mock-marketing-api api frontend keycloak
# 4. Bootstrap: Daten, ERP, Synthetik, Rollen, Simulationsuhr, Keycloak-Scopes/Origins/Demo-Nutzer
docker compose -f docker-compose.vps.yml --env-file .env run --rm app bis setup
docker compose -f docker-compose.vps.yml --env-file .env run --rm app bis materialize
docker compose -f docker-compose.vps.yml --env-file .env run --rm app python -m analytics.detect --from 2017-10-01 --to 2018-01-01
# 5. Dagster starten (Schedule läuft nachts, ein simulierter Tag pro Nacht)
docker compose -f docker-compose.vps.yml --env-file .env up -d
```

Reverse Proxy: die Blöcke aus [infra/caddy/bis.Caddyfile.example](../infra/caddy/bis.Caddyfile.example)
mit den echten Hostnamen an das Caddyfile **anhängen** (es ist als Datei in den Container
gemountet; ersetzen trennt den Mount), vorher Backup, dann `caddy validate` (Exit-Code prüfen)
und `caddy reload`.

## Betrieb

| Aufgabe | Befehl (in `infra/`) |
|---|---|
| Status | `docker compose -f docker-compose.vps.yml --env-file .env ps` |
| Dagster-Oberfläche | lokal: `ssh -L 3070:127.0.0.1:3070 <user>@<server>`, dann `http://127.0.0.1:3070` |
| Demo-Passwort | `BIS_DEMO_PASSWORD` in `infra/.env` (nur auf dem Server lesen) |
| Admin-Startpasswort | `BIS_ADMIN_INITIAL_PASSWORD` in `infra/.env`; gilt nur bis zum ersten Login (dann neues Passwort und OTP) |
| Update | Code aktualisieren, `build`, `up -d`; bei dbt-Änderungen läuft `dbt parse` im Image-Build |
| Stoppen | `docker compose -f docker-compose.vps.yml --env-file .env stop` (Daten bleiben) |

## Claude-Connector einrichten

1. Auf dem Server: `docker compose -f docker-compose.vps.yml --env-file .env run --rm app bis claude-connector`
   (gibt URL, Client-ID und **Secret** aus, nur selbst ausführen).
2. claude.ai → Einstellungen → Connectors → *Add custom connector*: URL eintragen, unter
   *Advanced settings* Client-ID und Secret.
3. Beim Verbinden öffnet sich der Keycloak-Login (Realm `bis`).

## Gastzugang und Mistral einschalten (A1)

1. Cloudflare-Dashboard → Turnstile → *Add widget*: Hostname = öffentlicher Host, Modus *Managed*,
   Pre-Clearance *No*. Site-Key und Secret notieren.
2. In `infra/.env` (nur auf dem Server):
   ```
   BIS_GUEST_ENABLED=true
   BIS_TURNSTILE_SITE_KEY=<Site-Key>
   BIS_TURNSTILE_SECRET_KEY=<Secret>
   BIS_LLM_PROVIDER=mistral
   BIS_MISTRAL_API_KEY=<Schlüssel>
   ```
   `BIS_GUEST_TOKEN_SECRET` und `BIS_ADMIN_INITIAL_PASSWORD` ergänzt
   `python3 -c "from ingestion.config import ensure_env_file; ensure_env_file()"` (im Repo-Verzeichnis).
3. `build`, `up -d`, dann `run --rm app bis setup` (Schema `ops.llm_usage`, Rechte, Admin-Rolle,
   OTP-Flow, Admin-Nutzer).
4. Prüfen: `/api/v1/guest/config` liefert `enabled: true`; ohne Turnstile gibt es kein Gast-Token.
   Test-Secrets von Cloudflare werden auf dem Server abgelehnt (Gastmodus bleibt aus).

## Backup

`infra/backup.sh` sichert täglich um 03:30 (Cron des Server-Nutzers) die Schemas `ops` und
`marts` (ab A3 auch `agents`, ab A4 `knowledge`) sowie die Keycloak-Datenbank nach `~/backups/bis`, 14 Tage.
`infra/backup-verify.sh` spielt die neueste Sicherung in eine Wegwerf-Datenbank ein und prüft
die Kerntabellen; zuletzt erfolgreich am 2026-10-09.

## Offen

- SMTP-Anbieter für Alerts
- Uptime-Kuma-Monitore für Dashboard und Login
