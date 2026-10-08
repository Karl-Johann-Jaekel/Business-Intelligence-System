import pytest

from api.auth import get_verifier
from api.main import app


@pytest.fixture(autouse=True)
def auth_disabled_by_default():
    """Endpoint tests run without authentication; test_auth.py installs its own verifier."""
    app.dependency_overrides[get_verifier] = lambda: None
    yield
    app.dependency_overrides.pop(get_verifier, None)
