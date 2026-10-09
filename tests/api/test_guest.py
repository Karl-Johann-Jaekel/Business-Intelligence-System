"""Guest access: Turnstile -> guest token -> read-only, public data only, no escalation."""

import time

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ed25519, rsa
from fastapi.testclient import TestClient
from test_api import FakeRepository  # tests/api is on sys.path (rootdir import mode)

from api import guest
from api.auth import IssuerRouter, TokenVerifier, get_verifier
from api.main import app, get_repository

KEYCLOAK_ISSUER = "http://idp.test/realms/bis"
RSA_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
SETTINGS = guest.GuestSettings(
    enabled=True,
    site_key="site-key",
    turnstile_secret="turnstile-secret",
    signing_secret="a-long-random-guest-signing-secret",
    issuer="bis-guest",
    ttl_seconds=7200,
    per_client_per_hour=3,
    per_day=1000,
)
KEYS = guest.GuestKeys(SETTINGS.signing_secret)


class Turnstile:
    """Fake Cloudflare siteverify: accepts the token 'ok'."""

    def __init__(self):
        self.calls: list[dict] = []

    def client(self) -> httpx.Client:
        def handle(request: httpx.Request) -> httpx.Response:
            form = dict(httpx.QueryParams(request.content.decode()))
            self.calls.append(form)
            ok = form.get("secret") == SETTINGS.turnstile_secret and form.get("response") == "ok"
            return httpx.Response(200, json={"success": ok})

        return httpx.Client(transport=httpx.MockTransport(handle))


@pytest.fixture
def turnstile(monkeypatch):
    fake = Turnstile()
    monkeypatch.setattr(guest, "settings", lambda: SETTINGS)
    monkeypatch.setattr(guest, "keys", lambda: KEYS)
    limiter = guest.RateLimiter(SETTINGS.per_client_per_hour, SETTINGS.per_day)
    monkeypatch.setattr(guest, "limiter", lambda: limiter)
    monkeypatch.setattr(guest, "get_turnstile_client", fake.client)
    return fake


@pytest.fixture
def client(turnstile):
    keycloak = TokenVerifier(KEYCLOAK_ISSUER, "bis-api", key=RSA_KEY.public_key())
    router = IssuerRouter(
        {KEYCLOAK_ISSUER: keycloak, "bis-guest": guest.GuestTokenVerifier(KEYS, "bis-guest")}
    )
    repo = FakeRepository()
    app.dependency_overrides[get_verifier] = lambda: router
    app.dependency_overrides[get_repository] = lambda: repo
    yield TestClient(app)
    app.dependency_overrides.pop(get_repository, None)


def _session(client, token="ok", ip="203.0.113.7"):
    return client.post(
        "/api/v1/guest/session",
        json={"turnstile_token": token},
        headers={"X-Forwarded-For": f"{ip}, 172.18.0.1"},
    )


def _guest_token(client) -> str:
    response = _session(client)
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# --- entry ------------------------------------------------------------------------------------


def test_config_exposes_only_the_public_site_key(client):
    body = client.get("/api/v1/guest/config").json()
    assert body == {"enabled": True, "site_key": "site-key"}


def test_session_requires_a_valid_captcha(client, turnstile):
    assert _session(client, token="forged").status_code == 403
    assert turnstile.calls[-1]["secret"] == "turnstile-secret"


def test_session_issues_a_short_lived_read_only_token(client):
    body = _session(client).json()
    claims = jwt.decode(body["access_token"], KEYS.public, algorithms=["EdDSA"], audience="cia-api")
    assert body["expires_in"] == 7200 and claims["exp"] - claims["iat"] == 7200
    assert claims["aud"] == ["bis-api", "cia-api"] and claims["sub"].startswith("guest:")
    assert set(claims["scope"].split()) == {"read:kpi", "read:knowledge", "ask:guest"}


def test_jwks_lets_the_agent_system_verify_guest_tokens(client):
    token = _guest_token(client)
    jwk = jwt.PyJWK(client.get("/api/v1/guest/jwks").json()["keys"][0])
    claims = jwt.decode(token, jwk.key, algorithms=["EdDSA"], audience="cia-api", issuer="bis-guest")
    assert claims["role"] == "guest"


def test_rate_limit_per_client(client):
    for _ in range(SETTINGS.per_client_per_hour):
        assert _session(client).status_code == 200
    blocked = _session(client)
    assert blocked.status_code == 429 and blocked.headers["Retry-After"] == "3600"
    assert _session(client, ip="198.51.100.9").status_code == 200  # other client unaffected


def test_rate_limiter_windows_slide():
    now = [0.0]
    limiter = guest.RateLimiter(per_client_per_hour=1, per_day=2, clock=lambda: now[0])
    assert limiter.allow("a") is None
    assert limiter.allow("a") == "too many guest sessions from this client"
    now[0] = 3601
    assert limiter.allow("a") is None
    assert limiter.allow("b") == "daily guest limit reached"
    now[0] = 86402
    assert limiter.allow("b") is None


def test_disabled_guest_mode(client, monkeypatch):
    monkeypatch.setattr(
        guest, "settings", lambda: guest.GuestSettings(**(SETTINGS.__dict__ | {"enabled": False}))
    )
    assert _session(client).status_code == 404
    assert client.get("/api/v1/guest/config").json() == {"enabled": False, "site_key": ""}
    assert client.get("/api/v1/guest/jwks").json() == {"keys": []}


# --- what a guest may see and do ----------------------------------------------------------------


def test_guest_reads_public_data_only(client):
    headers = _auth(_guest_token(client))
    keys = {k["key"] for k in client.get("/api/v1/kpis", headers=headers).json()}
    assert "gmv" in keys and not keys & {"conversion_rate", "roas", "budget_deviation"}
    assert client.get("/api/v1/kpis/roas/series", headers=headers).status_code == 404
    me = client.get("/api/v1/me", headers=headers).json()
    assert me["guest"] is True and me["admin"] is False and me["username"] == "Gast"


def test_guest_cannot_reach_admin_views(client):
    response = client.get("/api/v1/admin/usage", headers=_auth(_guest_token(client)))
    assert response.status_code == 403


def test_guest_token_cannot_be_escalated(client):
    """Even a correctly signed guest token never carries more than the guest scopes."""
    now = int(time.time())
    claims = {
        "iss": "bis-guest",
        "aud": ["bis-api"],
        "sub": "guest:x",
        "role": "guest",
        "scope": "read:kpi admin:agents",
        "iat": now,
        "exp": now + 60,
    }
    token = jwt.encode(claims, KEYS.private, algorithm="EdDSA")
    assert client.get("/api/v1/admin/usage", headers=_auth(token)).status_code == 403


@pytest.mark.parametrize(
    "token",
    [
        pytest.param(
            lambda now: jwt.encode(
                {
                    "iss": "bis-guest",
                    "aud": "bis-api",
                    "sub": "guest:x",
                    "role": "guest",
                    "scope": "read:kpi",
                    "iat": now,
                    "exp": now + 60,
                },
                ed25519.Ed25519PrivateKey.generate(),
                algorithm="EdDSA",
            ),
            id="foreign-key",
        ),
        pytest.param(
            lambda now: jwt.encode(
                {
                    "iss": "bis-guest",
                    "aud": "bis-api",
                    "sub": "guest:x",
                    "role": "guest",
                    "scope": "read:kpi",
                    "iat": now - 7300,
                    "exp": now - 100,
                },
                KEYS.private,
                algorithm="EdDSA",
            ),
            id="expired",
        ),
        pytest.param(
            lambda now: jwt.encode(
                {
                    "iss": "bis-guest",
                    "aud": "bis-api",
                    "sub": "user-1",
                    "scope": "read:kpi",
                    "iat": now,
                    "exp": now + 60,
                },
                KEYS.private,
                algorithm="EdDSA",
            ),
            id="not-a-guest",
        ),
        pytest.param(
            lambda now: jwt.encode(
                {
                    "iss": "evil",
                    "aud": "bis-api",
                    "sub": "guest:x",
                    "scope": "read:kpi",
                    "iat": now,
                    "exp": now + 60,
                },
                KEYS.private,
                algorithm="EdDSA",
            ),
            id="unknown-issuer",
        ),
    ],
)
def test_forged_guest_tokens_are_rejected(client, token):
    assert client.get("/api/v1/kpis", headers=_auth(token(int(time.time())))).status_code == 401


def test_signed_in_users_still_see_everything(client):
    now = int(time.time())
    token = jwt.encode(
        {
            "iss": KEYCLOAK_ISSUER,
            "aud": "bis-api",
            "sub": "user-1",
            "scope": "read:kpi admin:agents",
            "iat": now,
            "exp": now + 60,
        },
        RSA_KEY,
        algorithm="RS256",
    )
    keys = {k["key"] for k in client.get("/api/v1/kpis", headers=_auth(token)).json()}
    assert "roas" in keys
    usage = client.get("/api/v1/admin/usage", headers=_auth(token)).json()
    assert usage["total_tokens"] == 1200 and usage["guests"]["sessions_last_24h"] == 0
    assert client.get("/api/v1/me", headers=_auth(token)).json()["admin"] is True


def test_signing_key_is_stable_and_needs_a_secret():
    assert guest.GuestKeys("same-secret-0123456789").jwk == guest.GuestKeys("same-secret-0123456789").jwk
    with pytest.raises(RuntimeError, match="BIS_GUEST_TOKEN_SECRET"):
        guest.GuestKeys("")


@pytest.mark.parametrize(
    ("env", "enabled"),
    [
        (
            {
                "BIS_GUEST_ENABLED": "true",
                "BIS_TURNSTILE_SECRET_KEY": "0x4AAA-real",
                "BIS_GUEST_TOKEN_SECRET": "x" * 32,
            },
            True,
        ),
        (
            {
                "BIS_GUEST_ENABLED": "false",
                "BIS_TURNSTILE_SECRET_KEY": "0x4AAA-real",
                "BIS_GUEST_TOKEN_SECRET": "x" * 32,
            },
            False,
        ),
        (
            {"BIS_GUEST_ENABLED": "true", "BIS_TURNSTILE_SECRET_KEY": "", "BIS_GUEST_TOKEN_SECRET": "x" * 32},
            False,
        ),
        (
            {
                "BIS_GUEST_ENABLED": "true",
                "BIS_TURNSTILE_SECRET_KEY": "0x4AAA-real",
                "BIS_GUEST_TOKEN_SECRET": "short",
            },
            False,
        ),
        (
            {
                "BIS_GUEST_ENABLED": "true",
                "BIS_TURNSTILE_SECRET_KEY": "1x0000000000000000000000000000000AA",
                "BIS_GUEST_TOKEN_SECRET": "x" * 32,
            },
            False,
        ),
        (
            {
                "BIS_GUEST_ENABLED": "true",
                "BIS_TURNSTILE_SECRET_KEY": "1x0000000000000000000000000000000AA",
                "BIS_GUEST_TOKEN_SECRET": "x" * 32,
                "BIS_GUEST_ALLOW_TEST_KEYS": "true",
            },
            True,
        ),
    ],
    ids=[
        "configured",
        "switched-off",
        "no-turnstile-secret",
        "short-signing-secret",
        "test-key-in-prod",
        "test-key-local",
    ],
)
def test_guest_mode_needs_real_configuration(monkeypatch, env, enabled):
    for key in ("BIS_GUEST_ALLOW_TEST_KEYS",):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    guest.settings.cache_clear()
    try:
        assert guest.settings().enabled is enabled
    finally:
        guest.settings.cache_clear()
