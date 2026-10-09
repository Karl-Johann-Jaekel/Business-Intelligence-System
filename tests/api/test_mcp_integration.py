"""The Claude connector flow against the local stack (Keycloak + nginx + MCP container).
Skipped when the stack is not running."""

import base64
import hashlib
import json
import os
import re
import secrets
from html import unescape
from urllib.parse import parse_qs, urlencode, urlparse

import httpx
import pytest

KEYCLOAK = f"http://127.0.0.1:{os.getenv('BIS_KEYCLOAK_PORT', '8180')}"
SITE = f"http://127.0.0.1:{os.getenv('BIS_FRONTEND_PORT', '8103')}"
MCP = f"{SITE}/mcp"
CALLBACK = "https://claude.ai/api/mcp/auth_callback"


def _up() -> bool:
    try:
        return httpx.get(f"{SITE}/.well-known/oauth-protected-resource/mcp", timeout=2).status_code == 200
    except httpx.HTTPError:
        return False


pytestmark = pytest.mark.skipif(
    not (_up() and os.getenv("BIS_DEMO_PASSWORD")), reason="local stack not running"
)


def _authorize(client_id: str, redirect_uri: str, client_secret: str | None = None) -> str:
    """Authorization code + PKCE as the demo user; returns the access token."""
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    with httpx.Client(follow_redirects=False, timeout=15) as browser:
        page = browser.get(
            f"{KEYCLOAK}/realms/bis/protocol/openid-connect/auth?"
            + urlencode(
                {
                    "client_id": client_id,
                    "response_type": "code",
                    "scope": "openid",
                    "redirect_uri": redirect_uri,
                    "code_challenge": challenge,
                    "code_challenge_method": "S256",
                    "state": "s",
                }
            )
        )
        action = unescape(re.search(r'action="([^"]+)"', page.text).group(1))
        cookie = "; ".join(f"{k}={v}" for k, v in browser.cookies.items())  # cookiejar skips bare IPs
        answer = browser.post(
            action,
            data={
                "username": os.getenv("BIS_DEMO_USER", "demo"),
                "password": os.environ["BIS_DEMO_PASSWORD"],
            },
            headers={"Cookie": cookie},
        )
        assert answer.status_code == 302 and answer.headers["location"].startswith(redirect_uri)
        code = parse_qs(urlparse(answer.headers["location"]).query)["code"][0]
        form = {
            "grant_type": "authorization_code",
            "client_id": client_id,
            "code": code,
            "redirect_uri": redirect_uri,
            "code_verifier": verifier,
        }
        if client_secret:
            form["client_secret"] = client_secret
        tokens = browser.post(f"{KEYCLOAK}/realms/bis/protocol/openid-connect/token", data=form)
        tokens.raise_for_status()
        return tokens.json()["access_token"]


def _mcp(token: str, method: str, params: dict | None = None, rid: int = 1) -> httpx.Response:
    return httpx.post(
        MCP,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        },
        content=json.dumps({"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}}),
        timeout=30,
    )


@pytest.fixture(scope="module")
def mcp_token() -> str:
    from orchestration.keycloak_setup import mcp_client_credentials

    client_id, secret = mcp_client_credentials()
    return _authorize(client_id, CALLBACK, secret)


def test_discovery_chain_reaches_keycloak():
    meta = httpx.get(f"{SITE}/.well-known/oauth-protected-resource/mcp").json()
    issuer = meta["authorization_servers"][0].rstrip("/")
    assert meta["resource"] == MCP and issuer == f"{KEYCLOAK}/realms/bis"
    # RFC 8414 path-insertion form, as MCP clients look it up
    as_meta = httpx.get(f"{KEYCLOAK}/.well-known/oauth-authorization-server/realms/bis").json()
    assert as_meta["issuer"] == issuer and "S256" in as_meta["code_challenge_methods_supported"]


def test_unauthenticated_request_points_to_metadata():
    response = httpx.post(MCP, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert response.status_code == 401
    assert "resource_metadata" in response.headers["WWW-Authenticate"]


def test_claude_connector_flow_end_to_end(mcp_token):
    init = _mcp(
        mcp_token,
        "initialize",
        {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "it", "version": "1"}},
    )
    assert init.status_code == 200, init.text
    status = _mcp(mcp_token, "tools/call", {"name": "get_status", "arguments": {}}, 2).json()["result"]
    assert status["isError"] is False and "simulation_date" in json.dumps(status)
    kpis = _mcp(mcp_token, "tools/call", {"name": "list_kpis", "arguments": {}}, 3).json()["result"]
    text = json.dumps(kpis)
    assert "gmv" in text and "conversion_rate" not in text  # internal KPI stays inside
    series = _mcp(
        mcp_token,
        "tools/call",
        {"name": "get_kpi_series", "arguments": {"key": "gmv", "dimension": "region", "members": ["SP"]}},
        4,
    ).json()["result"]
    assert series["isError"] is False and "region:SP" in json.dumps(series)


def test_tokens_are_not_interchangeable(mcp_token):
    # A token for MCP is not accepted by the REST API ...
    assert (
        httpx.get(f"{SITE}/api/v1/kpis", headers={"Authorization": f"Bearer {mcp_token}"}).status_code == 401
    )
    # ... and a dashboard token is not accepted by MCP.
    dashboard_token = _authorize("bis-frontend", f"{SITE}/")
    assert _mcp(dashboard_token, "tools/list").status_code == 401
