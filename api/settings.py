"""API settings. The API connects with the read-only role `bis_api`, never as the owner."""

import os


def api_dsn() -> str:
    host = os.getenv("BIS_PG_HOST", "127.0.0.1")
    port = os.getenv("BIS_PG_PORT", "55432")
    user = os.getenv("BIS_API_DB_USER", "bis_api")
    password = os.getenv("BIS_API_DB_PASSWORD")
    if not password:
        raise RuntimeError("BIS_API_DB_PASSWORD is not set (see infra/.env.example)")
    return f"postgresql://{user}:{password}@{host}:{port}/warehouse?connect_timeout=5"
