"""MCP server: read access to the BI system for Claude (claude.ai custom connector, Claude Desktop,
Claude Code) over Streamable HTTP, authorised by Keycloak (realm `bis`).

- Tools reuse the API's logic (same read-only database role, same validation).
- Claude is an external provider: only data classes in BIS_MCP_DATA_CLASSES (default `public`)
  leave the system (plan section 8).
- Tokens must be issued for this server: audience = BIS_MCP_RESOURCE_URL (RFC 8707), scope
  `read:kpi`. The server publishes its protected-resource metadata so clients find Keycloak.

Run: uvicorn api.mcp_server:app --host 0.0.0.0 --port 8001
"""

import os
from collections.abc import Callable
from contextlib import contextmanager
from datetime import date
from functools import lru_cache
from typing import Any

import anyio
import jwt
import psycopg
from fastapi import HTTPException
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations

from api import main as api
from api.auth import TokenVerifier
from api.repository import WarehouseRepository
from api.settings import api_dsn
from registry import Kpi

READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=False)
SEVERITY_RANK = {"info": 0, "warning": 1, "critical": 2}

INSTRUCTIONS = """Business-Intelligence-System of a reference e-commerce company (real Olist order data
2016-2018, replayed day by day; marketing sessions/spend and budgets are synthetic).
Start with get_status (current simulation date) and list_kpis (definitions, units, dimensions).
Ratios are fractions (0.05 = 5 %), changes of ratios are best reported in percentage points.
Insights are statistical anomalies, not causes; say so when you explain them."""


def allowed_classes() -> list[str]:
    raw = os.getenv("BIS_MCP_DATA_CLASSES", "public")
    return [c.strip() for c in raw.split(",") if c.strip()]


def _public_kpis() -> dict[str, Kpi]:
    classes = set(allowed_classes())
    return {key: kpi for key, kpi in api.registry().items() if kpi.data_class in classes}


@contextmanager
def _repository():
    conn = psycopg.connect(api_dsn())
    try:
        yield WarehouseRepository(conn)
    finally:
        conn.close()


def _call(fn: Callable[..., Any], *args, **kwargs) -> Any:
    """Run API logic and turn its HTTP errors into tool errors Claude can read."""
    try:
        return fn(*args, **kwargs)
    except HTTPException as exc:
        raise ValueError(str(exc.detail)) from exc


def _dump(value: Any) -> Any:
    return value.model_dump(mode="json") if hasattr(value, "model_dump") else value


# --- tool implementations (synchronous; run in a worker thread) -----------------------------


def status() -> dict:
    with _repository() as repo:
        s = repo.status()
    if s is None:
        return {"status": "down"}
    return {
        "simulation_date": s.sim_date.isoformat(),
        "latest_kpi_date": s.latest_kpi_date.isoformat() if s.latest_kpi_date else None,
        "data_current": s.latest_kpi_date == s.sim_date,
        "last_successful_load_at": s.last_successful_load_at.isoformat()
        if s.last_successful_load_at
        else None,
    }


def kpis() -> list[dict]:
    return [
        {
            "key": k.key,
            "label": k.label,
            "description": k.description,
            "unit": k.unit,
            "grain": k.grain,
            "direction": k.direction,
            "dimensions": k.dimensions,
            "data_origin": k.data_origin,
            "owner": k.owner,
        }
        for k in _public_kpis().values()
    ]


def series(
    key: str, start: date | None, end: date | None, dimension: str | None, members: list[str] | None
) -> dict:
    with _repository() as repo:
        result = _call(api.kpi_series, key, _public_kpis(), repo, start, end, None, dimension, members, 5)
    return _dump(result)


def compare(key: str, start: date | None, end: date | None, dimension: str | None) -> dict:
    with _repository() as repo:
        result = _call(api.kpi_breakdown, key, _public_kpis(), repo, start, end, None, dimension)
    return _dump(result)


def insights(since: date | None, kpi: str | None, severity: str, limit: int) -> list[dict]:
    if kpi is not None and kpi not in _public_kpis():
        raise ValueError(f"Unknown KPI '{kpi}'")
    with _repository() as repo:
        rows = repo.insights(since, ["anomaly"], SEVERITY_RANK[severity], kpi, limit, allowed_classes())
    return [api._public(r) for r in rows]


def briefing() -> dict | None:
    with _repository() as repo:
        payload = repo.latest_briefing()
    if payload is None or payload.get("data_class") not in allowed_classes():
        return None
    return api._public(payload)


# --- MCP server -----------------------------------------------------------------------------


class KeycloakTokenVerifier:
    """Adapts the API's JWT verification (signature via JWKS, issuer, audience, expiry)."""

    def __init__(self, verifier: TokenVerifier, resource_url: str):
        self.verifier = verifier
        self.resource_url = resource_url

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            claims = await anyio.to_thread.run_sync(self.verifier.decode, token)
        except jwt.PyJWTError:
            return None
        return AccessToken(
            token=token,
            client_id=claims.get("azp", ""),
            scopes=claims.get("scope", "").split(),
            expires_at=claims.get("exp"),
            resource=self.resource_url,  # decode() already required this audience
            subject=claims.get("sub"),
        )


@lru_cache
def settings() -> dict:
    issuer = os.environ["BIS_OIDC_ISSUER"]
    resource = os.environ["BIS_MCP_RESOURCE_URL"]
    return {
        "issuer": issuer,
        "resource": resource,
        "jwks": os.getenv("BIS_OIDC_JWKS_URL", f"{issuer}/protocol/openid-connect/certs"),
        "hosts": [h.strip() for h in os.getenv("BIS_MCP_ALLOWED_HOSTS", "").split(",") if h.strip()],
    }


def build_server(token_verifier: Any, issuer: str, resource: str) -> MCPServer:
    server = MCPServer(
        name="business-intelligence-system",
        title="Business-Intelligence-System",
        instructions=INSTRUCTIONS,
        token_verifier=token_verifier,
        auth=AuthSettings(
            issuer_url=issuer,
            resource_server_url=resource,
            required_scopes=["read:kpi"],
            validate_token_resource=True,
        ),
    )

    @server.tool(annotations=READ_ONLY)
    async def get_status() -> dict:
        """Current simulation date and whether the KPI data is up to date."""
        return await anyio.to_thread.run_sync(status)

    @server.tool(annotations=READ_ONLY)
    async def list_kpis() -> list[dict]:
        """KPI definitions from the registry: key, label, unit, grain, direction, dimensions."""
        return await anyio.to_thread.run_sync(kpis)

    @server.tool(annotations=READ_ONLY)
    async def get_kpi_series(
        key: str,
        start: date | None = None,
        end: date | None = None,
        dimension: str | None = None,
        members: list[str] | None = None,
    ) -> dict:
        """Time series of one KPI. Default window: the 90 days (12 months for monthly KPIs) up to
        the simulation date. With `dimension` (region, category) the largest members or the given
        `members` are returned, e.g. dimension="region", members=["SP", "RJ"]."""
        return await anyio.to_thread.run_sync(series, key, start, end, dimension, members)

    @server.tool(annotations=READ_ONLY)
    async def compare_kpi(
        key: str, start: date | None = None, end: date | None = None, dimension: str | None = None
    ) -> dict:
        """KPI value in a window compared with the equally long window before, in total or per
        dimension member, sorted by the size of the change."""
        return await anyio.to_thread.run_sync(compare, key, start, end, dimension)

    @server.tool(annotations=READ_ONLY)
    async def list_insights(
        since: date | None = None, kpi: str | None = None, severity: str = "warning", limit: int = 20
    ) -> list[dict]:
        """Detected anomalies (insight.v1), newest first. `severity` is the minimum level
        (info, warning, critical)."""
        if severity not in SEVERITY_RANK:
            raise ValueError("severity must be info, warning or critical")
        return await anyio.to_thread.run_sync(insights, since, kpi, severity, max(1, min(limit, 100)))

    @server.tool(annotations=READ_ONLY)
    async def get_latest_briefing() -> dict | None:
        """The latest AI briefing (numbers verified against the data), if one exists."""
        return await anyio.to_thread.run_sync(briefing)

    return server


def create_app():
    cfg = settings()
    verifier = KeycloakTokenVerifier(
        TokenVerifier(cfg["issuer"], audience=cfg["resource"], jwks_url=cfg["jwks"]), cfg["resource"]
    )
    server = build_server(verifier, cfg["issuer"], cfg["resource"])
    security = TransportSecuritySettings(
        enable_dns_rebinding_protection=bool(cfg["hosts"]), allowed_hosts=cfg["hosts"]
    )
    # Stateless + JSON: every request is self-contained, nothing to keep per session.
    return server.streamable_http_app(stateless_http=True, json_response=True, transport_security=security)


app = create_app() if os.getenv("BIS_MCP_RESOURCE_URL") else None
