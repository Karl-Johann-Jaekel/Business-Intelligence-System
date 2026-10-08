import hashlib
import hmac
import json
from datetime import date, timedelta

import httpx
import psycopg
import pytest

from events import dispatch
from events.consumers import ConsumerConfig, WebhookSender, build_sender, signature
from events.email import dashboard_link, render_email
from events.insight import EntityRef, Evidence, Insight, Period, save
from ingestion import clock
from ingestion.db import connect, ensure_ops_schema


def _payload(**overrides) -> dict:
    insight = Insight(
        type="anomaly",
        kpi="delivery_time_avg_days",
        period=Period(start=date(2018, 3, 12), end=date(2018, 3, 12), grain="day"),
        severity="critical",
        direction="up",
        observed=14.2,
        expected=9.8,
        deviation_pct=44.9,
        entity_refs=[
            EntityRef(type="region", id="region:SP"),
            EntityRef(type="kpi", id="kpi:delivery_time_avg_days"),
        ],
        evidence=Evidence(method="stl_mad", score=6.1),
        summary="Ø Lieferzeit (Region SP) <script>alert(1)</script>",
        data_class="public",
    )
    return insight.model_dump(mode="json") | overrides


def test_email_contains_kpi_values_and_deep_link_and_escapes_text():
    subject, html, text = render_email(_payload(), "http://dash.local")
    assert subject == "[Kritisch] Ø Lieferzeit (Tage) (Region SP) – Auffälligkeit 12.03.2018"
    assert "Score +6,1" in html
    assert "14,2 Tage" in html and "9,8 Tage" in html and "+44,9 %" in html
    assert "<script>" not in html and "&lt;script&gt;" in html
    assert "kpi=delivery_time_avg_days&amp;dim=region&amp;from=2018-02-11&amp;to=2018-03-12" in html
    assert "Dashboard: http://dash.local/?kpi=delivery_time_avg_days&dim=region" in text


def test_dashboard_link_for_monthly_insight_spans_a_year():
    payload = _payload(
        kpi="budget_deviation", period={"start": "2018-01-01", "end": "2018-01-31", "grain": "month"}
    )
    assert "from=2017-02-01&to=2018-01-31" in dashboard_link(payload, "http://d")


def test_webhook_signs_raw_body():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = request.content
        seen["headers"] = request.headers
        return httpx.Response(204)

    payload = _payload()
    WebhookSender("http://hook", "s3cret", httpx.Client(transport=httpx.MockTransport(handler))).send(
        payload["insight_id"], payload
    )
    expected = "sha256=" + hmac.new(b"s3cret", seen["body"], hashlib.sha256).hexdigest()
    assert seen["headers"]["X-BIS-Signature"] == expected == signature("s3cret", seen["body"])
    assert seen["headers"]["X-BIS-Event-Id"] == payload["insight_id"]
    assert seen["headers"]["X-BIS-Event-Type"] == "insight.v1"
    assert json.loads(seen["body"])["schema_version"] == "insight.v1"


def test_consumer_is_inactive_without_its_environment():
    email = ConsumerConfig(name="email", type="email", types=["anomaly"], to_env="X_TO")
    hook = ConsumerConfig(name="h", type="webhook", types=["anomaly"], url_env="X_URL", secret_env="X_SECRET")
    assert build_sender(email, {}) is None
    assert build_sender(email, {"X_TO": "a@b.c"}) is not None
    assert build_sender(hook, {"X_URL": "http://x"}) is None


# --- dispatcher against the local warehouse --------------------------------------------------


def _db_available() -> bool:
    try:
        with connect() as conn:
            ensure_ops_schema(conn)
        return True
    except (psycopg.Error, RuntimeError):  # RuntimeError: no secrets configured
        return False


needs_db = pytest.mark.skipif(not _db_available(), reason="warehouse not reachable")
CONSUMER = "test-consumer"


class FlakySender:
    def __init__(self, failures: int):
        self.failures = failures
        self.sent: list[str] = []

    def send(self, event_id: str, payload: dict) -> None:
        if self.failures > 0:
            self.failures -= 1
            raise ConnectionError("smtp down")
        self.sent.append(event_id)


@pytest.fixture
def conn():
    with connect() as conn:
        yield conn
        conn.execute("DELETE FROM ops.event_deliveries WHERE consumer = %s", (CONSUMER,))
        conn.execute("DELETE FROM ops.events WHERE dedup_key LIKE 'anomaly:test_%%'")
        conn.commit()


def _insight(
    kpi: str, severity: str = "warning", day: date = date(2018, 1, 5), data_class: str = "public"
) -> Insight:
    return Insight(
        type="anomaly",
        kpi=kpi,
        period=Period(start=day, end=day, grain="day"),
        severity=severity,
        evidence=Evidence(method="stl_mad", score=5.0),
        summary="test",
        data_class=data_class,
    )


@needs_db
def test_save_is_idempotent_per_finding(conn):
    assert save(conn, _insight("test_kpi_a")) is True
    assert save(conn, _insight("test_kpi_a", severity="critical")) is False
    conn.commit()


@needs_db
def test_dispatch_filters_retries_and_never_resends(conn, monkeypatch):
    monkeypatch.setattr(dispatch, "BASE_BACKOFF", dispatch.timedelta(0))
    # Other insights in the outbox may be delivered to the fake sender as well; assertions only
    # look at the test rows.
    today = clock.get_sim_date(conn)
    save(conn, _insight("test_kpi_warn", "warning", today))
    save(conn, _insight("test_kpi_info", "info", today))
    save(conn, _insight("test_kpi_old", "critical", today - timedelta(days=30)))  # outside max_age
    save(conn, _insight("test_kpi_secret", "critical", today, data_class="confidential"))
    conn.commit()
    consumer = ConsumerConfig(
        name=CONSUMER, type="webhook", types=["anomaly"], min_severity="warning", max_age_days=1
    )
    sender = FlakySender(failures=1)

    first = dispatch.run(conn, [consumer], {CONSUMER: sender})
    statuses = dict(
        conn.execute(
            """
            SELECT i.kpi, d.status FROM ops.event_deliveries d JOIN ops.events i USING (event_id)
            WHERE d.consumer = %s AND i.kpi LIKE 'test_%%'
            """,
            (CONSUMER,),
        ).fetchall()
    )
    assert statuses["test_kpi_info"] == "skipped"
    assert statuses["test_kpi_old"] == "skipped"
    assert statuses["test_kpi_secret"] == "skipped"  # above the consumer's max_data_class
    assert first.retrying >= 1  # the first delivery attempt failed

    dispatch.run(conn, [consumer], {CONSUMER: sender})  # retry is due immediately (backoff 0)
    dispatch.run(conn, [consumer], {CONSUMER: sender})  # nothing left to send
    test_ids = {
        str(r[0])
        for r in conn.execute("SELECT event_id FROM ops.events WHERE kpi = 'test_kpi_warn'").fetchall()
    }
    assert [i for i in sender.sent if i in test_ids] == list(test_ids)  # delivered exactly once
    status, attempts = conn.execute(
        """
        SELECT d.status, d.attempts FROM ops.event_deliveries d JOIN ops.events i USING (event_id)
        WHERE d.consumer = %s AND i.kpi = 'test_kpi_warn'
        """,
        (CONSUMER,),
    ).fetchone()
    assert status == "delivered" and attempts >= 1
