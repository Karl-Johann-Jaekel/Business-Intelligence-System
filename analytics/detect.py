"""Run the registry's alert rules for one simulation date and write insight.v1 events."""

from dataclasses import dataclass, replace
from datetime import date, timedelta

import pandas as pd
import psycopg
from psycopg import sql

from analytics import anomaly
from analytics.text import format_signed_pct, format_value
from events.insight import EntityRef, Evidence, Insight, Period, save
from registry import Kpi, load_registry

# Dimension members are noisy when small; only the largest members (by volume) are monitored,
# the same set the dashboard shows by default.
TOP_MEMBERS = 5
# Single regions/categories are much noisier day to day than the total; their alerts need a
# stronger deviation (measured on 2017-10..2018-01: ~3 alerts per member series and month at 1x).
MEMBER_THRESHOLD_FACTOR = 1.5

DIMENSION_LABELS = {"region": "Region", "category": "Kategorie"}


@dataclass(frozen=True)
class Target:
    dimension: str  # "total" or the entity_type
    member: str  # "all" or the dimension value
    entity_id: str


# grain table -> date column; the only identifiers ever interpolated into SQL here.
_TABLES = {"kpi_daily": "kpi_date", "kpi_monthly": "month_start"}


def _targets(conn: psycopg.Connection, kpi: Kpi, table: str, start: date, end: date) -> list[Target]:
    date_col = _TABLES[table]
    targets = [Target("total", "all", f"kpi:{kpi.key}")]
    if kpi.entity_type:
        query = sql.SQL(
            """
            SELECT dimension_value, entity_id FROM marts.{table}
            WHERE kpi_key = %(kpi)s AND dimension = %(dim)s AND {date_col} BETWEEN %(start)s AND %(end)s
            GROUP BY dimension_value, entity_id
            -- Daily ratios of single members (on-time rate of one region, ...) are too noisy to
            -- alert on; they are monitored on the total only. Measured on 2017-10..2018-01:
            -- several false alarms per day, also with a minimum-volume filter.
            HAVING %(ratio_members)s OR bool_and(aggregation = 'sum')
            ORDER BY coalesce(sum(denominator), sum(numerator)) DESC NULLS LAST, dimension_value
            LIMIT %(top)s
            """
        ).format(table=sql.Identifier(table), date_col=sql.Identifier(date_col))
        params = {
            "kpi": kpi.key,
            "dim": kpi.entity_type,
            "start": start,
            "end": end,
            # Monthly members (budget deviation per category) are stable enough to monitor.
            "ratio_members": table == "kpi_monthly",
            "top": TOP_MEMBERS,
        }
        rows = conn.execute(query, params).fetchall()
        targets += [Target(kpi.entity_type, member, entity_id) for member, entity_id in rows]
    return targets


def daily_series(conn: psycopg.Connection, kpi: str, target: Target, start: date, end: date) -> pd.Series:
    rows = conn.execute(
        """
        SELECT kpi_date, value FROM marts.kpi_daily
        WHERE kpi_key = %s AND dimension = %s AND dimension_value = %s AND kpi_date BETWEEN %s AND %s
        """,
        (kpi, target.dimension, target.member, start, end),
    ).fetchall()
    index = pd.date_range(start, end, freq="D").date
    values = {d: (None if v is None else float(v)) for d, v in rows}
    return pd.Series([values.get(d) for d in index], index=index, dtype=float)


def _entity_refs(kpi: Kpi, target: Target) -> list[EntityRef]:
    refs = [EntityRef(type="kpi", id=f"kpi:{kpi.key}")]
    if target.dimension != "total":
        refs.insert(0, EntityRef(type=target.dimension, id=target.entity_id))
    return refs


def _summary(kpi: Kpi, target: Target, det: anomaly.Detection, period_label: str) -> str:
    scope = (
        ""
        if target.dimension == "total"
        else f" ({DIMENSION_LABELS.get(target.dimension, target.dimension)} {target.member})"
    )
    observed = format_value(det.observed, kpi.unit)
    if kpi.alert and kpi.alert.method == "threshold":
        bound = format_value(kpi.alert.threshold, kpi.unit)
        return f"{kpi.label}{scope} {period_label}: {observed}, Grenze ±{bound} überschritten."
    expected = format_value(det.expected, kpi.unit)
    return (
        f"{kpi.label}{scope} am {period_label}: {observed} statt erwartet {expected} "
        f"({format_signed_pct(det.deviation_pct)})."
    )


def _query_ref(kpi: Kpi, target: Target, start: date, end: date) -> str:
    ref = f"/api/v1/kpis/{kpi.key}/series?from={start}&to={end}"
    if target.dimension != "total":
        ref += f"&dim={target.dimension}&value={target.member}"
    return ref


def detect_daily(conn: psycopg.Connection, kpi: Kpi, sim_date: date) -> list[Insight]:
    assert kpi.alert and kpi.alert.method == "stl_mad" and kpi.alert.min_history_days
    start = sim_date - timedelta(days=anomaly.WINDOW_DAYS - 1)
    insights = []
    for target in _targets(conn, kpi, "kpi_daily", start, sim_date):
        series = daily_series(conn, kpi.key, target, start, sim_date)
        threshold = kpi.alert.threshold * (1 if target.dimension == "total" else MEMBER_THRESHOLD_FACTOR)
        det = anomaly.stl_mad(series, threshold, kpi.alert.min_history_days)
        if det is None or not det.is_anomaly:
            continue
        if kpi.unit == "ratio":
            # Level + weekday effect can leave [0, 1]; a rate is never expected above 100 %.
            det = replace(det, expected=min(max(det.expected, 0.0), 1.0))
        insights.append(
            Insight(
                type="anomaly",
                kpi=kpi.key,
                period=Period(start=sim_date, end=sim_date, grain="day"),
                severity=det.severity,
                direction=det.direction,
                observed=round(det.observed, 6),
                expected=round(det.expected, 6),
                deviation_pct=det.deviation_pct,
                entity_refs=_entity_refs(kpi, target),
                evidence=Evidence(
                    method="stl_mad", score=det.score, query_ref=_query_ref(kpi, target, start, sim_date)
                ),
                summary=_summary(kpi, target, det, sim_date.strftime("%d.%m.%Y")),
                data_class=kpi.data_class,
            )
        )
    return insights


def latest_complete_month(sim_date: date) -> date:
    first = sim_date.replace(day=1)
    if (sim_date + timedelta(days=1)).month != sim_date.month:
        return first  # sim_date is the last day of its month
    return (first - timedelta(days=1)).replace(day=1)


def detect_monthly(conn: psycopg.Connection, kpi: Kpi, sim_date: date) -> list[Insight]:
    assert kpi.alert and kpi.alert.method == "threshold"
    month = latest_complete_month(sim_date)
    month_end = (month.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    insights = []
    for target in _targets(conn, kpi, "kpi_monthly", month, month):
        row = conn.execute(
            """
            SELECT value FROM marts.kpi_monthly
            WHERE kpi_key = %s AND dimension = %s AND dimension_value = %s
              AND month_start = %s AND is_complete
            """,
            (kpi.key, target.dimension, target.member, month),
        ).fetchone()
        det = anomaly.threshold(None if row is None or row[0] is None else float(row[0]), kpi.alert.threshold)
        if det is None or not det.is_anomaly:
            continue
        insights.append(
            Insight(
                type="anomaly",
                kpi=kpi.key,
                period=Period(start=month, end=month_end, grain="month"),
                severity=det.severity,
                direction=det.direction,
                observed=round(det.observed, 6),
                expected=0.0,
                deviation_pct=None,
                entity_refs=_entity_refs(kpi, target),
                evidence=Evidence(
                    method="threshold",
                    score=det.score,
                    query_ref=_query_ref(kpi, target, month, month),
                    threshold=kpi.alert.threshold,
                ),
                summary=_summary(kpi, target, det, month.strftime("%m/%Y")),
                data_class=kpi.data_class,
            )
        )
    return insights


def run(conn: psycopg.Connection, sim_date: date, kpis: list[Kpi] | None = None) -> dict[str, int]:
    """Detect anomalies for sim_date, store new insights. Returns counts for metadata."""
    found = stored = 0
    for kpi in kpis or load_registry():
        if kpi.alert is None:
            continue
        insights = (
            detect_daily(conn, kpi, sim_date)
            if kpi.alert.method == "stl_mad"
            else detect_monthly(conn, kpi, sim_date)
        )
        for insight in insights:
            found += 1
            stored += save(conn, insight)
    conn.commit()
    return {"found": found, "stored": stored}


def main() -> None:
    """Backfill: python -m analytics.detect --from 2017-10-01 --to 2018-01-08"""
    import argparse

    from ingestion.db import connect, ensure_ops_schema

    parser = argparse.ArgumentParser(description="Detect anomalies for a range of past days")
    parser.add_argument("--from", dest="start", type=date.fromisoformat, required=True)
    parser.add_argument("--to", dest="end", type=date.fromisoformat, required=True)
    args = parser.parse_args()
    kpis = load_registry()
    with connect() as conn:
        ensure_ops_schema(conn)
        day, total = args.start, {"found": 0, "stored": 0}
        while day <= args.end:
            counts = run(conn, day, kpis)
            total = {k: total[k] + counts[k] for k in total}
            day += timedelta(days=1)
    print(f"{args.start}..{args.end}: {total['found']} anomalies, {total['stored']} new")


if __name__ == "__main__":
    main()
