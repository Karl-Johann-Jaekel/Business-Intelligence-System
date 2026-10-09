"""`bis` command line: start the environment, bootstrap data, drive the simulation clock."""

import argparse
import os
import subprocess
import sys
from datetime import date

from ingestion.config import REPO_ROOT

DEFAULT_START_DATE = date(2018, 1, 1)
COMPOSE_FILE = REPO_ROOT / "infra" / "docker-compose.yml"
DBT_DIR = REPO_ROOT / "dbt"

ENV_DEFAULTS = {
    # 127.0.0.1, not localhost: the port is bound to IPv4 only and an IPv6 attempt can hang on Windows.
    "BIS_PG_HOST": "127.0.0.1",
    "BIS_PG_PORT": "55432",
    "BIS_PG_USER": "bis",
    "DAGSTER_HOME": str(REPO_ROOT / "orchestration" / "dagster_home"),
    # Local alerts go to the Mailpit test inbox (http://127.0.0.1:8025).
    "BIS_ALERT_TO": "team@bis.local",
}


def _ensure_env_file() -> None:
    """Create infra/.env with random secrets on first use and load it."""
    from ingestion.config import ENV_FILE, ensure_env_file, load_env_file

    if os.getenv("BIS_ENV_FROM_COMPOSE") == "true":
        return  # in a container all settings come from the compose environment

    added = ensure_env_file()
    if added:
        # Only key names are printed, never values.
        print(f"{ENV_FILE.relative_to(REPO_ROOT)}: added {', '.join(added)} (random secrets)", flush=True)
    load_env_file()


def _env() -> dict[str, str]:
    for key, value in ENV_DEFAULTS.items():
        os.environ.setdefault(key, value)
    scripts = os.path.dirname(sys.executable)
    if scripts not in os.environ.get("PATH", "").split(os.pathsep):
        os.environ["PATH"] = scripts + os.pathsep + os.environ.get("PATH", "")
    return os.environ.copy()


def _bin(name: str) -> str:
    """Executable from the active virtualenv (works on Windows and POSIX)."""
    scripts = os.path.dirname(sys.executable)
    for candidate in (os.path.join(scripts, name), os.path.join(scripts, name + ".exe")):
        if os.path.exists(candidate):
            return candidate
    return name


def _run(cmd: list[str]) -> None:
    print(f"$ {' '.join(cmd)}", flush=True)
    subprocess.run(cmd, check=True, env=_env(), cwd=REPO_ROOT)


def _dbt_parse() -> None:
    _run([_bin("dbt"), "parse", "--project-dir", str(DBT_DIR), "--profiles-dir", str(DBT_DIR)])


def cmd_setup(args: argparse.Namespace) -> None:
    from ingestion import clock
    from ingestion.config import require_secret
    from ingestion.db import connect, ensure_api_role, ensure_ops_schema
    from ingestion.setup import download, seed_erp, synthetic

    _ensure_env_file()
    print("Olist dataset ...", flush=True)
    download.download()
    if args.force or not seed_erp.is_seeded():
        print("Seeding ERP database ...", flush=True)
        print(seed_erp.seed())
    if args.force or not synthetic.is_generated():
        print("Generating synthetic marketing and budget data ...", flush=True)
        print(synthetic.generate_all())
    with connect() as conn:
        ensure_ops_schema(conn)
        ensure_api_role(conn, require_secret("BIS_API_DB_PASSWORD"))
        current = clock.get_sim_date(conn)
        if current is None or args.start_date:
            current = clock.set_sim_date(conn, args.start_date or DEFAULT_START_DATE)
    print(f"Simulation date: {current}")
    _dbt_parse()
    _provision_keycloak()


def _provision_keycloak() -> None:
    import httpx

    from orchestration.keycloak_setup import provision

    try:
        for line in provision():
            print(f"Keycloak {line}", flush=True)
    except httpx.HTTPError as exc:
        print(f"Keycloak not provisioned ({exc.__class__.__name__}); is the container running?", flush=True)


def cmd_up(args: argparse.Namespace) -> None:
    _ensure_env_file()  # docker compose needs the secrets before the first start
    _run(["docker", "compose", "-f", str(COMPOSE_FILE), "up", "-d", "--build", "--wait"])
    cmd_setup(argparse.Namespace(force=False, start_date=None))
    if not args.no_dagster:
        _run([_bin("dagster"), "dev", "-p", str(args.port)])


def cmd_down(args: argparse.Namespace) -> None:
    cmd = ["docker", "compose", "-f", str(COMPOSE_FILE), "down"]
    if args.volumes:
        cmd.append("-v")
    _run(cmd)


def cmd_materialize(args: argparse.Namespace) -> None:
    # Outside `dagster dev` the manifest is not refreshed automatically; a stale one breaks
    # dagster-dbt as soon as a model or test name changes.
    _dbt_parse()
    _run([_bin("dagster"), "job", "execute", "-m", "orchestration.definitions", "-j", "daily_pipeline"])


def cmd_clock(args: argparse.Namespace) -> None:
    from ingestion import clock
    from ingestion.db import connect, ensure_ops_schema

    with connect() as conn:
        ensure_ops_schema(conn)
        if args.action == "set":
            value = clock.set_sim_date(conn, date.fromisoformat(args.value))
        elif args.action == "advance":
            value = clock.advance(conn, int(args.value or 1))
        else:
            value = clock.get_sim_date(conn)
    print(f"Simulation date: {value}")


def cmd_claude_connector(args: argparse.Namespace) -> None:
    """For the person setting up the connector in claude.ai. Prints a secret by design."""
    from orchestration.keycloak_setup import mcp_client_credentials

    client_id, secret = mcp_client_credentials()
    print(f"MCP server URL:      {os.getenv('BIS_MCP_RESOURCE_URL', 'http://127.0.0.1:8103/mcp')}")
    print(f"OAuth Client ID:     {client_id}")
    print(f"OAuth Client Secret: {secret}")


def cmd_tick(args: argparse.Namespace) -> None:
    """Advance the clock by one day and run the pipeline, `days` times."""
    for _ in range(args.days):
        cmd_clock(argparse.Namespace(action="advance", value="1"))
        cmd_materialize(args)


def main(argv: list[str] | None = None) -> None:
    _env()
    parser = argparse.ArgumentParser(prog="bis", description="Business-Intelligence-System")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("up", help="Start containers, bootstrap data, launch Dagster UI")
    p.add_argument("--no-dagster", action="store_true", help="Do not start `dagster dev`")
    p.add_argument("--port", type=int, default=3000)
    p.set_defaults(func=cmd_up)

    p = sub.add_parser("down", help="Stop containers")
    p.add_argument("-v", "--volumes", action="store_true", help="Also delete the database volume")
    p.set_defaults(func=cmd_down)

    p = sub.add_parser("setup", help="Download Olist, seed ERP, generate synthetic data, init clock")
    p.add_argument("--force", action="store_true", help="Re-seed ERP and regenerate synthetic data")
    p.add_argument("--start-date", type=date.fromisoformat, default=None)
    p.set_defaults(func=cmd_setup)

    p = sub.add_parser("materialize", help="Run the full pipeline once (ingestion + dbt build)")
    p.set_defaults(func=cmd_materialize)

    p = sub.add_parser("clock", help="Show, set or advance the simulation date")
    p.add_argument("action", choices=["show", "set", "advance"], nargs="?", default="show")
    p.add_argument("value", nargs="?", help="ISO date for `set`, number of days for `advance`")
    p.set_defaults(func=cmd_clock)

    p = sub.add_parser(
        "claude-connector",
        help="Print URL, client id and secret for the Claude MCP connector (contains a secret!)",
    )
    p.set_defaults(func=cmd_claude_connector)

    p = sub.add_parser("tick", help="Advance one simulated day and run the pipeline (repeatable)")
    p.add_argument("--days", type=int, default=1)
    p.set_defaults(func=cmd_tick)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
