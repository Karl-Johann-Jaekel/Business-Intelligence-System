import base64
import hashlib
import os
import re
import secrets
import time
from html import unescape
from urllib.parse import parse_qs, urlencode, urlparse

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from api.auth import TokenVerifier, get_verifier
from api.main import app

ISSUER = "http://idp.test/realms/bis"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _token(key=KEY, **overrides) -> str:
    now = int(time.time())
    claims = {
        "iss": ISSUER,
        "aud": "bis-api",
        "sub": "user-1",
        "preferred_username": "demo",
        "azp": "bis-frontend",
        "scope": "openid profile read:kpi",
        "iat": now,
        "exp": now + 300,
    } | overrides
    return jwt.encode(claims, key, algorithm="RS256")


@pytest.fixture
def client():
    app.dependency_overrides[get_verifier] = lambda: TokenVerifier(ISSUER, "bis-api", key=KEY.public_key())
    yield TestClient(app)


def _get(client, token: str | None):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return client.get("/api/v1/kpis", headers=headers)


def test_valid_token_with_scope_is_accepted(client):
    assert _get(client, _token()).status_code == 200


def test_missing_token_is_401_with_challenge(client):
    response = _get(client, None)
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"].startswith("Bearer")


@pytest.mark.parametrize(
    "token",
    [
        _token(key=OTHER_KEY),  # forged signature
        _token(exp=int(time.time()) - 10),  # expired
        _token(aud="someone-else"),  # not addressed to the API
        _token(iss="http://evil.test/realms/bis"),  # other issuer
        "not-a-jwt",
    ],
    ids=["signature", "expired", "audience", "issuer", "garbage"],
)
def test_invalid_tokens_are_401(client, token):
    assert _get(client, token).status_code == 401


def test_missing_scope_is_403(client):
    response = _get(client, _token(scope="openid profile read:knowledge"))
    assert response.status_code == 403
    assert "insufficient_scope" in response.headers["WWW-Authenticate"]


def test_health_needs_no_token(client):
    assert client.get("/api/v1/health").status_code in (200, 503)


# --- real login against the local Keycloak (skipped when it is not running) ------------------

KEYCLOAK = f"http://127.0.0.1:{os.getenv('BIS_KEYCLOAK_PORT', '8180')}"
API = f"http://127.0.0.1:{os.getenv('BIS_API_PORT', '8102')}"
REDIRECT = f"http://127.0.0.1:{os.getenv('BIS_FRONTEND_PORT', '8103')}/"


def _keycloak_up() -> bool:
    try:
        return (
            httpx.get(f"{KEYCLOAK}/realms/bis/.well-known/openid-configuration", timeout=2).status_code == 200
        )
    except httpx.HTTPError:
        return False


def _login_pkce(username: str, password: str) -> str:
    """Authorization code flow with PKCE, as the browser dashboard does it. Returns the access token."""
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    with httpx.Client(follow_redirects=False, timeout=15) as browser:
        page = browser.get(
            f"{KEYCLOAK}/realms/bis/protocol/openid-connect/auth?"
            + urlencode(
                {
                    "client_id": "bis-frontend",
                    "response_type": "code",
                    "scope": "openid",
                    "redirect_uri": REDIRECT,
                    "code_challenge": challenge,
                    "code_challenge_method": "S256",
                    "state": "s",
                }
            )
        )
        action = unescape(re.search(r'action="([^"]+)"', page.text).group(1))
        # http.cookiejar does not send cookies back to bare-IP hosts like 127.0.0.1; a browser does.
        cookie = "; ".join(f"{name}={value}" for name, value in browser.cookies.items())
        answer = browser.post(
            action, data={"username": username, "password": password}, headers={"Cookie": cookie}
        )
        assert answer.status_code == 302, "login failed"
        code = parse_qs(urlparse(answer.headers["location"]).query)["code"][0]
        tokens = browser.post(
            f"{KEYCLOAK}/realms/bis/protocol/openid-connect/token",
            data={
                "grant_type": "authorization_code",
                "client_id": "bis-frontend",
                "code": code,
                "redirect_uri": REDIRECT,
                "code_verifier": verifier,
            },
        )
        tokens.raise_for_status()
        return tokens.json()["access_token"]


@pytest.mark.skipif(not _keycloak_up(), reason="local Keycloak not running")
def test_dashboard_login_grants_read_kpi_against_running_api():
    password = os.getenv("BIS_DEMO_PASSWORD")
    if not password:
        pytest.skip("BIS_DEMO_PASSWORD not set (bis setup)")
    token = _login_pkce(os.getenv("BIS_DEMO_USER", "demo"), password)
    claims = jwt.decode(token, options={"verify_signature": False})
    assert "read:kpi" in claims["scope"].split() and "bis-api" in claims["aud"]

    assert httpx.get(f"{API}/api/v1/kpis", timeout=10).status_code == 401
    ok = httpx.get(f"{API}/api/v1/kpis", headers={"Authorization": f"Bearer {token}"}, timeout=10)
    assert ok.status_code == 200 and len(ok.json()) >= 8


@pytest.mark.skipif(not _keycloak_up(), reason="local Keycloak not running")
def test_wrong_password_is_rejected_by_keycloak():
    with pytest.raises(AssertionError, match="login failed"):
        _login_pkce(os.getenv("BIS_DEMO_USER", "demo"), "definitely-wrong")
