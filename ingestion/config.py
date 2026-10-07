"""Runtime settings from environment variables.

Defaults match infra/docker-compose.yml and are meant for local development only.
"""

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.getenv("BIS_DATA_DIR", REPO_ROOT / "data"))
OLIST_DIR = DATA_DIR / "olist"
SYNTHETIC_DIR = DATA_DIR / "synthetic"
CONTROLLING_DIR = DATA_DIR / "controlling"

MARKETING_API_URL = os.getenv("BIS_MARKETING_API_URL", "http://127.0.0.1:8101")

# Fixed seed for all synthetic data so every environment produces identical numbers.
SYNTHETIC_SEED = 42


def pg_dsn(database: str) -> str:
    host = os.getenv("BIS_PG_HOST", "127.0.0.1")
    port = os.getenv("BIS_PG_PORT", "55432")
    user = os.getenv("BIS_PG_USER", "bis")
    password = os.getenv("BIS_PG_PASSWORD", "bis_dev")
    return f"postgresql://{user}:{password}@{host}:{port}/{database}"


API_DB_PASSWORD = os.getenv("BIS_API_DB_PASSWORD", "bis_api_dev")

WAREHOUSE_DSN = pg_dsn("warehouse")
ERP_DSN = pg_dsn("erp")
