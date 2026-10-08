"""Runs against the local warehouse with the read-only role; skipped when it is not reachable."""

import psycopg
import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.settings import api_dsn


def _reachable() -> bool:
    try:
        with psycopg.connect(api_dsn()) as conn:
            conn.execute("SELECT 1 FROM marts.pipeline_status")
        return True
    except (psycopg.Error, RuntimeError):  # RuntimeError: no BIS_API_DB_PASSWORD configured
        return False


pytestmark = pytest.mark.skipif(not _reachable(), reason="warehouse with pipeline_status not reachable")


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


def test_api_role_is_read_only_and_limited_to_marts():
    with psycopg.connect(api_dsn(), autocommit=True) as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("SELECT * FROM ops.load_log LIMIT 1")
    with psycopg.connect(api_dsn(), autocommit=True) as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("SELECT * FROM raw.erp__orders LIMIT 1")
    with psycopg.connect(api_dsn(), autocommit=True) as conn:
        conn.execute("SELECT count(*) FROM ops.events")  # the outbox is readable
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("SELECT * FROM ops.event_deliveries LIMIT 1")
    with psycopg.connect(api_dsn(), autocommit=True) as conn:
        with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
            conn.execute("CREATE TABLE marts.should_fail (x int)")


def test_health_reports_current_sim_date(client):
    body = client.get("/api/v1/health").json()
    assert body["status"] in {"ok", "stale"}
    assert body["sim_date"] is not None


def test_every_daily_kpi_has_a_total_series(client):
    for kpi in client.get("/api/v1/kpis").json():
        response = client.get(f"/api/v1/kpis/{kpi['key']}/series")
        assert response.status_code == 200, kpi["key"]
        series = response.json()["series"]
        assert len(series) == 1 and series[0]["points"], kpi["key"]


def test_region_breakdown_matches_total_for_additive_kpi(client):
    total = client.get("/api/v1/kpis/gmv/breakdown").json()["rows"][0]["current"]
    regions = client.get("/api/v1/kpis/gmv/breakdown?dim=region").json()["rows"]
    assert len(regions) > 20
    assert sum(r["current"] or 0 for r in regions) == pytest.approx(total, rel=1e-9)
