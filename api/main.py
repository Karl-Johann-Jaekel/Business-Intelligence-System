"""BIS API v1: KPI registry (semantic layer), KPI series and comparisons, insights, guest access,
admin views, health."""

from collections.abc import Iterator
from datetime import date, datetime, timedelta
from functools import lru_cache
from typing import Annotated, Literal

import psycopg
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from api import guest
from api.auth import Principal, require_scope
from api.periods import default_window, normalise, previous_window
from api.repository import Grain, Repository, WarehouseRepository
from api.settings import ConfigError, api_dsn
from registry import Kpi, load_registry

app = FastAPI(title="Business-Intelligence-System API", version="1.0")
app.include_router(guest.router)

# Scopes per endpoint (plan section 10); /health and the guest entry stay open.
# One dependency object per scope, so FastAPI verifies the token once per request.
_read_kpi = require_scope("read:kpi")
READ_KPI = Depends(_read_kpi)
ReaderDep = Annotated[Principal, Depends(_read_kpi)]
ADMIN_AGENTS = Depends(require_scope("admin:agents"))
ALL_CLASSES = ["public", "internal", "confidential"]


def visible_classes(principal: Principal) -> list[str]:
    """Guests are external recipients like the MCP server: public data only (plan section 8)."""
    return ["public"] if principal.guest else ALL_CLASSES


# --- dependencies -------------------------------------------------------------------------


@lru_cache
def registry() -> dict[str, Kpi]:
    return {kpi.key: kpi for kpi in load_registry()}


def get_registry(principal: ReaderDep) -> dict[str, Kpi]:
    classes = visible_classes(principal)
    return {key: kpi for key, kpi in registry().items() if kpi.data_class in classes}


def get_repository() -> Iterator[Repository]:
    try:
        conn = psycopg.connect(api_dsn())
    except (psycopg.OperationalError, ConfigError) as exc:
        raise HTTPException(503, "Warehouse unavailable") from exc
    try:
        yield WarehouseRepository(conn)
    finally:
        conn.close()


def get_optional_repository() -> Iterator[Repository | None]:
    """Like get_repository, but yields None when the warehouse is unreachable (health checks)."""
    try:
        conn = psycopg.connect(api_dsn())
    except (psycopg.OperationalError, ConfigError):
        yield None
        return
    try:
        yield WarehouseRepository(conn)
    finally:
        conn.close()


RegistryDep = Annotated[dict[str, Kpi], Depends(get_registry)]
RepoDep = Annotated[Repository, Depends(get_repository)]
OptionalRepoDep = Annotated[Repository | None, Depends(get_optional_repository)]


# --- response models ----------------------------------------------------------------------


class Window(BaseModel):
    start: date
    end: date


class PointOut(BaseModel):
    period: date
    value: float | None


class SeriesOut(BaseModel):
    dimension_value: str
    entity_id: str
    points: list[PointOut]


class SeriesResponse(BaseModel):
    kpi: str
    grain: Grain
    dimension: str
    window: Window
    series: list[SeriesOut]


class BreakdownRow(BaseModel):
    dimension_value: str
    entity_id: str
    current: float | None
    previous: float | None
    change_abs: float | None
    change_pct: float | None


class BreakdownResponse(BaseModel):
    kpi: str
    grain: Grain
    dimension: str
    current_window: Window
    previous_window: Window
    rows: list[BreakdownRow]


class HealthResponse(BaseModel):
    status: Literal["ok", "stale", "down"]
    sim_date: date | None = None
    latest_kpi_date: date | None = None
    last_successful_load_at: datetime | None = None
    last_failed_load_at: datetime | None = None
    built_at: datetime | None = None


# --- helpers ------------------------------------------------------------------------------


def _kpi(key: str, kpis: dict[str, Kpi]) -> Kpi:
    if key not in kpis:
        raise HTTPException(404, f"Unknown KPI '{key}'")
    return kpis[key]


def _resolve(
    kpi: Kpi, repo: Repository, grain: Grain | None, dim: str | None, start: date | None, end: date | None
) -> tuple[Grain, str, date, date]:
    grain = grain or kpi.grain
    if kpi.grain == "month" and grain == "day":
        raise HTTPException(400, f"KPI '{kpi.key}' is only available per month")
    if dim is not None and dim not in kpi.dimensions:
        raise HTTPException(400, f"KPI '{kpi.key}' has no dimension '{dim}'. Allowed: {kpi.dimensions}")
    if start is None or end is None:
        status = repo.status()
        if status is None:
            raise HTTPException(503, "Pipeline has not produced data yet")
        default_start, default_end = default_window(grain, status.sim_date)
        start, end = start or default_start, end or default_end
    start, end = normalise(grain, start, end)
    if start > end:
        raise HTTPException(400, "'from' must not be after 'to'")
    return grain, dim or "total", start, end


def _change(current: float | None, previous: float | None) -> tuple[float | None, float | None]:
    if current is None or previous is None:
        return None, None
    pct = None if previous == 0 else round((current - previous) / abs(previous) * 100, 2)
    return round(current - previous, 6), pct


# --- routes -------------------------------------------------------------------------------


@app.get("/api/v1/kpis", response_model=list[Kpi], dependencies=[READ_KPI])
def list_kpis(kpis: RegistryDep) -> list[Kpi]:
    return list(kpis.values())


@app.get("/api/v1/kpis/{key}", response_model=Kpi, dependencies=[READ_KPI])
def get_kpi(key: str, kpis: RegistryDep) -> Kpi:
    return _kpi(key, kpis)


@app.get("/api/v1/kpis/{key}/series", response_model=SeriesResponse, dependencies=[READ_KPI])
def kpi_series(
    key: str,
    kpis: RegistryDep,
    repo: RepoDep,
    start: Annotated[date | None, Query(alias="from")] = None,
    end: Annotated[date | None, Query(alias="to")] = None,
    grain: Grain | None = None,
    dim: str | None = None,
    value: Annotated[list[str] | None, Query(description="Dimension members; default: top N")] = None,
    top: Annotated[int, Query(ge=1, le=30)] = 5,
) -> SeriesResponse:
    kpi = _kpi(key, kpis)
    grain, dimension, start, end = _resolve(kpi, repo, grain, dim, start, end)
    series = repo.series(kpi.key, grain, dimension, start, end, value, top)
    return SeriesResponse(
        kpi=kpi.key,
        grain=grain,
        dimension=dimension,
        window=Window(start=start, end=end),
        series=[
            SeriesOut(
                dimension_value=s.dimension_value,
                entity_id=s.entity_id,
                points=[PointOut(period=p.period, value=p.value) for p in s.points],
            )
            for s in series
        ],
    )


@app.get("/api/v1/kpis/{key}/breakdown", response_model=BreakdownResponse, dependencies=[READ_KPI])
def kpi_breakdown(
    key: str,
    kpis: RegistryDep,
    repo: RepoDep,
    start: Annotated[date | None, Query(alias="from")] = None,
    end: Annotated[date | None, Query(alias="to")] = None,
    grain: Grain | None = None,
    dim: str | None = None,
) -> BreakdownResponse:
    """KPI per dimension member for a window, compared with the equally long previous window."""
    kpi = _kpi(key, kpis)
    grain, dimension, start, end = _resolve(kpi, repo, grain, dim, start, end)
    prev_start, prev_end = previous_window(grain, start, end)
    current = {a.dimension_value: a for a in repo.aggregate(kpi.key, grain, dimension, start, end)}
    previous = {a.dimension_value: a for a in repo.aggregate(kpi.key, grain, dimension, prev_start, prev_end)}

    rows = []
    for member in sorted(current.keys() | previous.keys()):
        cur, prev = current.get(member), previous.get(member)
        cur_value, prev_value = (cur.value if cur else None), (prev.value if prev else None)
        change_abs, change_pct = _change(cur_value, prev_value)
        rows.append(
            BreakdownRow(
                dimension_value=member,
                entity_id=(cur or prev).entity_id,
                current=cur_value,
                previous=prev_value,
                change_abs=change_abs,
                change_pct=change_pct,
            )
        )
    rows.sort(key=lambda r: (r.change_pct is None, -abs(r.change_pct or 0)))
    return BreakdownResponse(
        kpi=kpi.key,
        grain=grain,
        dimension=dimension,
        current_window=Window(start=start, end=end),
        previous_window=Window(start=prev_start, end=prev_end),
        rows=rows,
    )


SEVERITY_RANK = {"info": 0, "warning": 1, "critical": 2}
InsightType = Literal["anomaly", "briefing", "forecast_deviation", "data_quality"]


def _public(payload: dict) -> dict:
    """insight.v1 as delivered to consumers; the analyst's raw input context stays internal."""
    details = payload.get("details")
    if details and "context" in details:
        payload = payload | {"details": {k: v for k, v in details.items() if k != "context"}}
    return payload


@app.get("/api/v1/insights", dependencies=[READ_KPI])
def list_insights(
    repo: RepoDep,
    principal: ReaderDep,
    since: date | None = None,
    type: Annotated[list[InsightType] | None, Query()] = None,  # noqa: A002 - public API name
    severity: Literal["info", "warning", "critical"] = "info",
    kpi: str | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[dict]:
    """insight.v1 events, newest period first. `severity` is the minimum level."""
    classes = None if not principal.guest else visible_classes(principal)
    rows = repo.insights(since, list(type) if type else None, SEVERITY_RANK[severity], kpi, limit, classes)
    return [_public(r) for r in rows]


@app.get("/api/v1/briefings/latest", dependencies=[READ_KPI])
def latest_briefing(repo: RepoDep, principal: ReaderDep) -> dict:
    payload = repo.latest_briefing(None if not principal.guest else visible_classes(principal))
    if payload is None:
        raise HTTPException(404, "No briefing yet")
    return _public(payload)


class MeResponse(BaseModel):
    subject: str
    username: str | None
    guest: bool
    admin: bool
    scopes: list[str]


@app.get("/api/v1/me", response_model=MeResponse)
def me(principal: ReaderDep) -> MeResponse:
    """Who the portal is talking to: guest or signed-in user, and which areas to show."""
    return MeResponse(
        subject=principal.subject,
        username=principal.username,
        guest=principal.guest,
        admin=any(s.startswith("admin:") for s in principal.scopes),
        scopes=sorted(principal.scopes),
    )


@app.get("/api/v1/admin/usage", dependencies=[ADMIN_AGENTS])
def admin_usage(repo: RepoDep, days: Annotated[int, Query(ge=1, le=365)] = 30) -> dict:
    """LLM usage of the BI system and guest sessions (in-memory counters of this API process)."""
    rows = repo.llm_usage(date.today() - timedelta(days=days - 1))
    return {
        "days": days,
        "llm": rows,
        "total_cost_eur": round(sum(r["cost_eur"] for r in rows), 6),
        "total_tokens": sum(r["tokens_in"] + r["tokens_out"] for r in rows),
        "guests": guest.limiter().stats() if guest.settings().enabled else None,
    }


@app.get("/api/v1/health", response_model=HealthResponse)
def health(repo: OptionalRepoDep):
    try:
        status = repo.status() if repo is not None else None
    except psycopg.Error:
        status = None
    if status is None:
        return JSONResponse(status_code=503, content={"status": "down"})
    fresh = status.latest_kpi_date == status.sim_date
    return HealthResponse(status="ok" if fresh else "stale", **status.__dict__)
