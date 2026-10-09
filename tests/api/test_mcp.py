import json
import time
from datetime import date, datetime

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from mcp.server.transport_security import TransportSecuritySettings
from starlette.testclient import TestClient

from api import mcp_server
from api.auth import TokenVerifier
from api.repository import PipelineStatus

ISSUER = "http://idp.test/realms/bis"
RESOURCE = "http://bi.test/mcp"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


class FakeRepo:
    def __init__(self):
        self.calls = []

    def status(self):
        return PipelineStatus(
            date(2018, 1, 8), date(2018, 1, 8), datetime(2026, 10, 9, 2, 0), None, datetime(2026, 10, 9)
        )

    def insights(self, since, types, min_rank, kpi, limit, classes=None):
        self.calls.append(("insights", since, types, min_rank, kpi, limit, classes))
        return [{"insight_id": "1", "type": "anomaly", "data_class": "public", "details": None}]

    def latest_briefing(self):
        return self.briefing

    briefing = None


@pytest.fixture
def repo(monkeypatch):
    fake = FakeRepo()

    class _Ctx:
        def __enter__(self):
            return fake

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(mcp_server, "_repository", lambda: _Ctx())
    return fake


# --- data class rule (plan section 8): only public data leaves through MCP -------------------


def test_internal_kpis_are_not_listed():
    keys = {k["key"] for k in mcp_server.kpis()}
    assert {"gmv", "delivery_time_avg_days"} <= keys
    assert not keys & {"conversion_rate", "roas", "budget_deviation"}  # internal


def test_internal_kpi_cannot_be_queried(repo):
    with pytest.raises(ValueError, match="Unknown KPI"):
        mcp_server.series("roas", None, None, None, None)
    with pytest.raises(ValueError, match="Unknown KPI"):
        mcp_server.insights(None, "conversion_rate", "warning", 10)


def test_insights_are_filtered_to_allowed_classes(repo):
    mcp_server.insights(None, None, "warning", 10)
    assert repo.calls[-1][-1] == ["public"]


def test_briefing_above_allowed_class_is_withheld(repo):
    repo.briefing = {"type": "briefing", "data_class": "internal", "details": {"briefing": {}}}
    assert mcp_server.briefing() is None
    repo.briefing = {"type": "briefing", "data_class": "public", "details": {"briefing": {}, "context": {}}}
    assert mcp_server.briefing() == {"type": "briefing", "data_class": "public", "details": {"briefing": {}}}


def test_status_reports_simulation_date(repo):
    assert mcp_server.status()["simulation_date"] == "2018-01-08"


# --- HTTP: discovery, authentication, protocol ----------------------------------------------


def _token(**overrides) -> str:
    now = int(time.time())
    claims = {
        "iss": ISSUER,
        "aud": RESOURCE,
        "sub": "user-1",
        "azp": "bis-claude",
        "scope": "openid read:kpi",
        "iat": now,
        "exp": now + 300,
    } | overrides
    return jwt.encode(claims, KEY, algorithm="RS256")


@pytest.fixture
def client(repo):
    verifier = mcp_server.KeycloakTokenVerifier(
        TokenVerifier(ISSUER, RESOURCE, key=KEY.public_key()), RESOURCE
    )
    app = mcp_server.build_server(verifier, ISSUER, RESOURCE).streamable_http_app(
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True, allowed_hosts=["testserver"]
        ),
    )
    with TestClient(app) as c:
        yield c


def _rpc(client, method: str, params: dict | None = None, token: str | None = None, rid: int = 1):
    headers = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = {"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}}
    return client.post("/mcp", headers=headers, content=json.dumps(body))


def test_protected_resource_metadata_points_to_keycloak(client):
    meta = client.get("/.well-known/oauth-protected-resource/mcp").json()
    assert meta["resource"] == RESOURCE
    assert meta["authorization_servers"][0].rstrip("/") == ISSUER
    assert "read:kpi" in meta.get("scopes_supported", [])


def test_request_without_token_gets_401_with_discovery_hint(client):
    response = _rpc(client, "tools/list")
    assert response.status_code == 401
    assert "resource_metadata" in response.headers["WWW-Authenticate"]


@pytest.mark.parametrize(
    ("claims", "status"),
    [({"aud": "bis-api"}, 401), ({"exp": int(time.time()) - 10}, 401), ({"scope": "openid"}, 403)],
    ids=["token-for-the-api-not-mcp", "expired", "missing-scope"],
)
def test_rejected_tokens(client, claims, status):
    assert _rpc(client, "tools/list", token=_token(**claims)).status_code == status


def test_valid_token_lists_and_calls_tools(client):
    token = _token()
    init = _rpc(
        client,
        "initialize",
        {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}},
        token,
    )
    assert init.status_code == 200, init.text
    tools = _rpc(client, "tools/list", token=token, rid=2).json()["result"]["tools"]
    names = {t["name"] for t in tools}
    assert names == {
        "get_status",
        "list_kpis",
        "get_kpi_series",
        "compare_kpi",
        "list_insights",
        "get_latest_briefing",
    }
    assert all(t["annotations"]["readOnlyHint"] for t in tools)

    call = _rpc(client, "tools/call", {"name": "get_status", "arguments": {}}, token, rid=3).json()["result"]
    assert call["isError"] is False
    assert "2018-01-08" in json.dumps(call)


def test_foreign_host_header_is_rejected(client):
    """DNS-rebinding protection: only the configured public host is served."""
    response = client.post(
        "/mcp",
        headers={
            "Host": "evil.test",
            "Authorization": f"Bearer {_token()}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
        content=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}),
    )
    assert response.status_code == 421
