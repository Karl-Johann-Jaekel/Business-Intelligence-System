"""Runtime settings from environment variables.

Secrets have no defaults in code. Locally they live in infra/.env (git-ignored), which
`bis setup` creates with random passwords and which is loaded here for every entry point
(CLI, Dagster, tests). Variables already set in the environment take precedence.
"""

import os
import secrets
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = REPO_ROOT / "infra" / ".env"
ENV_TEMPLATE = REPO_ROOT / "infra" / ".env.example"
GENERATED_SECRET = "generated-by-bis-setup"


def load_env_file(path: Path = ENV_FILE) -> None:
    """Minimal KEY=VALUE reader (no interpolation); never overrides the real environment."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def _materialise(line: str) -> str:
    if line.endswith(f"={GENERATED_SECRET}"):
        return line.replace(GENERATED_SECRET, secrets.token_urlsafe(24))
    return line


def ensure_env_file(path: Path = ENV_FILE, template: Path = ENV_TEMPLATE) -> list[str]:
    """Create infra/.env from the template, or append keys the template gained since; every
    secret placeholder becomes a random value. Existing values are never changed.
    Returns the keys that were added."""
    template_lines = template.read_text(encoding="utf-8").splitlines()
    if not path.exists():
        path.write_text("\n".join(_materialise(line) for line in template_lines) + "\n", encoding="utf-8")
        return [line.split("=", 1)[0] for line in template_lines if "=" in line and not line.startswith("#")]
    existing = {
        line.split("=", 1)[0].strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if "=" in line and not line.lstrip().startswith("#")
    }
    missing = [
        line
        for line in template_lines
        if "=" in line and not line.startswith("#") and line.split("=", 1)[0] not in existing
    ]
    if missing:
        with path.open("a", encoding="utf-8") as fh:
            fh.write("\n".join(_materialise(line) for line in missing) + "\n")
    return [line.split("=", 1)[0] for line in missing]


load_env_file()

DATA_DIR = Path(os.getenv("BIS_DATA_DIR", REPO_ROOT / "data"))
OLIST_DIR = DATA_DIR / "olist"
SYNTHETIC_DIR = DATA_DIR / "synthetic"
CONTROLLING_DIR = DATA_DIR / "controlling"

MARKETING_API_URL = os.getenv("BIS_MARKETING_API_URL", "http://127.0.0.1:8101")

# Fixed seed for all synthetic data so every environment produces identical numbers.
SYNTHETIC_SEED = 42


class MissingSecretError(RuntimeError):
    pass


def require_secret(name: str) -> str:
    value = os.getenv(name)
    if not value or value == GENERATED_SECRET:
        raise MissingSecretError(f"{name} is not set. Run `bis setup` (creates infra/.env) or export it.")
    return value


def pg_dsn(database: str, user: str | None = None, password_var: str = "BIS_PG_PASSWORD") -> str:
    host = os.getenv("BIS_PG_HOST", "127.0.0.1")
    port = os.getenv("BIS_PG_PORT", "55432")
    user = user or os.getenv("BIS_PG_USER", "bis")
    return f"postgresql://{user}:{require_secret(password_var)}@{host}:{port}/{database}"


def warehouse_dsn() -> str:
    return pg_dsn("warehouse")


def erp_dsn() -> str:
    return pg_dsn("erp")
