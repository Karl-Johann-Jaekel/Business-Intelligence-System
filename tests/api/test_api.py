from datetime import date, datetime

import pytest
from fastapi.testclient import TestClient

from api.main import app, get_optional_repository, get_repository
from api.periods import previous_window
from api.repository import Aggregate, PipelineStatus, Point, Series

SIM_DATE = date(2018, 3, 31)


class FakeRepository:
    def __init__(self, status: PipelineStatus | None = None, aggregates=None):
        self._status = status or PipelineStatus(
            SIM_DATE, SIM_DATE, datetime(2026, 10, 7, 2, 0), None, datetime(2026, 10, 7, 2, 5)
        )
        # {(start, end): [Aggregate]}
        self._aggregates = aggregates or {}
        self.calls: list[tuple] = []

    def status(self):
        return self._status

    def series(self, kpi, grain, dimension, start, end, values, top):
        self.calls.append(("series", kpi, grain, dimension, start, end, values, top))
        return [Series("all", f"kpi:{kpi}", [Point(start, 1.0), Point(end, 2.0)])]

    def aggregate(self, kpi, grain, dimension, start, end):
        self.calls.append(("aggregate", kpi, grain, dimension, start, end))
        return self._aggregates.get((start, end), [])

    briefing: dict | None = None

    def insights(self, since, types, min_rank, kpi, limit):
        self.calls.append(("insights", since, types, min_rank, kpi, limit))
        return [{"insight_id": "1", "type": "anomaly", "details": None}]

    def latest_briefing(self):
        return self.briefing


@pytest.fixture
def repo():
    return FakeRepository()


@pytest.fixture
def client(repo):
    app.dependency_overrides[get_repository] = lambda: repo
    app.dependency_overrides[get_optional_repository] = lambda: repo
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_lists_registry(client):
    body = client.get("/api/v1/kpis").json()
    keys = {k["key"] for k in body}
    assert {"gmv", "delivery_time_avg_days", "budget_deviation"} <= keys
    gmv = next(k for k in body if k["key"] == "gmv")
    assert gmv["unit"] == "BRL" and gmv["dimensions"] == ["region", "category"]


def test_unknown_kpi_is_404(client):
    assert client.get("/api/v1/kpis/nope").status_code == 404
    assert client.get("/api/v1/kpis/nope/series").status_code == 404


def test_series_defaults_to_last_90_days(client, repo):
    body = client.get("/api/v1/kpis/gmv/series").json()
    assert body["window"] == {"start": "2018-01-01", "end": "2018-03-31"}
    assert body["dimension"] == "total"
    assert repo.calls[-1] == ("series", "gmv", "day", "total", date(2018, 1, 1), SIM_DATE, None, 5)


def test_series_passes_dimension_members(client, repo):
    client.get("/api/v1/kpis/gmv/series?dim=region&value=SP&value=RJ&from=2018-02-01&to=2018-02-10")
    assert repo.calls[-1][3:7] == ("region", date(2018, 2, 1), date(2018, 2, 10), ["SP", "RJ"])


def test_series_rejects_dimension_not_in_registry(client):
    response = client.get("/api/v1/kpis/conversion_rate/series?dim=region")
    assert response.status_code == 400
    assert "no dimension" in response.json()["detail"]


def test_monthly_kpi_rejects_daily_grain_and_defaults_to_12_months(client):
    assert client.get("/api/v1/kpis/budget_deviation/series?grain=day").status_code == 400
    body = client.get("/api/v1/kpis/budget_deviation/series").json()
    assert body["grain"] == "month"
    assert body["window"] == {"start": "2017-04-01", "end": "2018-03-01"}


def test_inverted_window_is_400(client):
    assert client.get("/api/v1/kpis/gmv/series?from=2018-03-01&to=2018-02-01").status_code == 400


def test_breakdown_compares_with_previous_window():
    current = (date(2018, 3, 1), date(2018, 3, 31))
    previous = previous_window("day", *current)
    repo = FakeRepository(
        aggregates={
            current: [Aggregate("SP", "region:SP", 120.0), Aggregate("RJ", "region:RJ", 50.0)],
            previous: [Aggregate("SP", "region:SP", 100.0), Aggregate("RJ", "region:RJ", 100.0)],
        }
    )
    app.dependency_overrides[get_repository] = lambda: repo
    try:
        body = (
            TestClient(app).get("/api/v1/kpis/gmv/breakdown?dim=region&from=2018-03-01&to=2018-03-31").json()
        )
    finally:
        app.dependency_overrides.clear()

    assert body["previous_window"] == {"start": "2018-01-29", "end": "2018-02-28"}
    rj, sp = body["rows"]  # sorted by absolute change
    assert (rj["dimension_value"], rj["change_pct"], rj["change_abs"]) == ("RJ", -50.0, -50.0)
    assert (sp["dimension_value"], sp["change_pct"]) == ("SP", 20.0)


def test_breakdown_handles_missing_previous_value():
    window = (date(2018, 3, 1), date(2018, 3, 31))
    repo = FakeRepository(aggregates={window: [Aggregate("all", "kpi:gmv", 10.0)]})
    app.dependency_overrides[get_repository] = lambda: repo
    try:
        rows = TestClient(app).get("/api/v1/kpis/gmv/breakdown?from=2018-03-01&to=2018-03-31").json()["rows"]
    finally:
        app.dependency_overrides.clear()
    assert rows == [
        {
            "dimension_value": "all",
            "entity_id": "kpi:gmv",
            "current": 10.0,
            "previous": None,
            "change_abs": None,
            "change_pct": None,
        }
    ]


def test_previous_window_for_months():
    assert previous_window("month", date(2018, 1, 1), date(2018, 3, 1)) == (
        date(2017, 10, 1),
        date(2017, 12, 1),
    )


def test_health_ok_and_stale(client, repo):
    assert client.get("/api/v1/health").json()["status"] == "ok"
    repo._status = PipelineStatus(SIM_DATE, date(2018, 3, 30), None, None, datetime(2026, 10, 7))
    assert client.get("/api/v1/health").json()["status"] == "stale"


def test_health_down_without_database():
    app.dependency_overrides[get_optional_repository] = lambda: None
    try:
        response = TestClient(app).get("/api/v1/health")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 503
    assert response.json() == {"status": "down"}


def test_insights_passes_filters(client, repo):
    body = client.get(
        "/api/v1/insights?since=2018-01-01&type=anomaly&severity=warning&kpi=gmv&limit=10"
    ).json()
    assert body == [{"insight_id": "1", "type": "anomaly", "details": None}]
    assert repo.calls[-1] == ("insights", date(2018, 1, 1), ["anomaly"], 1, "gmv", 10)


def test_insights_rejects_unknown_type(client):
    assert client.get("/api/v1/insights?type=gossip").status_code == 422


def test_latest_briefing_hides_internal_context(client, repo):
    assert client.get("/api/v1/briefings/latest").status_code == 404
    repo.briefing = {"type": "briefing", "details": {"briefing": {"summary": "x"}, "context": {"secret": 1}}}
    body = client.get("/api/v1/briefings/latest").json()
    assert body["details"] == {"briefing": {"summary": "x"}}


def test_missing_database_config_is_reported_as_down_not_500(monkeypatch):
    """Regression (CI run of PR #4): without BIS_API_DB_PASSWORD /health crashed with 500."""
    monkeypatch.delenv("BIS_API_DB_PASSWORD", raising=False)
    client = TestClient(app)  # real dependencies, no overrides
    response = client.get("/api/v1/health")
    assert response.status_code == 503 and response.json() == {"status": "down"}
    assert client.get("/api/v1/kpis/gmv/series").status_code == 503
