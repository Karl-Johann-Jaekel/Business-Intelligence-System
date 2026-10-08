"""Load infra/.env (if present) so integration tests find the local secrets."""

import ingestion.config  # noqa: F401 - import side effect: loads infra/.env
