"""Input for the AI analyst: only computed values from the marts and the outbox, already
formatted, each with an id the briefing can cite as evidence. No raw rows, no free text."""

import json
from datetime import date, timedelta
from typing import Any

import psycopg

from analytics.detect import latest_complete_month
from analytics.text import format_signed_pct, format_value
from llm.provider import highest_data_class
from registry import Kpi

WINDOW_DAYS = 7
TOP_DRIVERS = 3
RATIO_CANDIDATES = 10


def _aggregate(
    conn, kpi: str, dimension: str, start: date, end: date
) -> dict[str, tuple[float | None, float]]:
    """member -> (value, volume). Volume = denominator (ratios) or the value itself (sums)."""
    rows = conn.execute(
        """
        SELECT dimension_value,
               CASE WHEN bool_and(aggregation = 'sum') THEN sum(numerator)
                    ELSE sum(numerator) / nullif(sum(denominator), 0) END,
               coalesce(sum(denominator), sum(numerator), 0)
        FROM marts.kpi_daily
        WHERE kpi_key = %s AND dimension = %s AND kpi_date BETWEEN %s AND %s
        GROUP BY dimension_value
        """,
        (kpi, dimension, start, end),
    ).fetchall()
    return {member: (None if v is None else float(v), float(vol)) for member, v, vol in rows}


def _is_additive(conn, kpi: str) -> bool:
    """Sum KPIs (aggregation = 'sum' in kpi_daily) can be split into contributions."""
    row = conn.execute(
        "SELECT bool_and(aggregation = 'sum') FROM marts.kpi_daily WHERE kpi_key = %s", (kpi,)
    ).fetchone()
    return bool(row and row[0])


def _change_pct(current: float | None, previous: float | None) -> float | None:
    if current is None or previous in (None, 0):
        return None
    return round((current - previous) / abs(previous) * 100, 1)


def _daily_kpi(conn, kpi: Kpi, sim_date: date) -> dict[str, Any]:
    cur_start = sim_date - timedelta(days=WINDOW_DAYS - 1)
    prev_end = cur_start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=WINDOW_DAYS - 1)
    current = _aggregate(conn, kpi.key, "total", cur_start, sim_date).get("all", (None, 0))[0]
    previous = _aggregate(conn, kpi.key, "total", prev_start, prev_end).get("all", (None, 0))[0]
    entry: dict[str, Any] = {
        "id": f"kpi:{kpi.key}",
        "label": kpi.label,
        "direction": kpi.direction,
        "data_origin": kpi.data_origin,
        "last_7_days": format_value(current, kpi.unit),
        "previous_7_days": format_value(previous, kpi.unit),
        "change": format_signed_pct(_change_pct(current, previous)),
    }
    if kpi.entity_type:
        cur = _aggregate(conn, kpi.key, kpi.entity_type, cur_start, sim_date)
        prev = _aggregate(conn, kpi.key, kpi.entity_type, prev_start, prev_end)
        # Small members produce huge percentages (39,90 -> 1.788,99 R$ = +4.383 %). Additive KPIs
        # are ranked by absolute contribution to the change; ratios only among the members with
        # the largest volume.
        additive = _is_additive(conn, kpi.key)
        candidates = [m for m in cur if m in prev and cur[m][0] is not None and prev[m][0] is not None]
        if not additive:
            candidates = sorted(candidates, key=lambda m: cur[m][1], reverse=True)[:RATIO_CANDIDATES]
        movers = [(m, cur[m][0], prev[m][0], _change_pct(cur[m][0], prev[m][0])) for m in candidates]
        movers = [x for x in movers if x[3] is not None]
        if additive:
            movers.sort(key=lambda x: abs(x[1] - x[2]), reverse=True)
        else:
            movers.sort(key=lambda x: abs(x[3]), reverse=True)
        entry["top_drivers"] = [
            {
                "id": f"{kpi.entity_type}:{member}",
                "last_7_days": format_value(c, kpi.unit),
                "previous_7_days": format_value(p, kpi.unit),
                "change": format_signed_pct(pct),
            }
            for member, c, p, pct in movers[:TOP_DRIVERS]
        ]
    return entry


def _monthly_kpi(conn, kpi: Kpi, sim_date: date) -> dict[str, Any] | None:
    month = latest_complete_month(sim_date)
    row = conn.execute(
        """
        SELECT value FROM marts.kpi_monthly
        WHERE kpi_key = %s AND dimension = 'total' AND month_start = %s AND is_complete
        """,
        (kpi.key, month),
    ).fetchone()
    if row is None:
        return None
    return {
        "id": f"kpi:{kpi.key}",
        "label": kpi.label,
        "data_origin": kpi.data_origin,
        "month": month.strftime("%m/%Y"),
        "value": format_value(None if row[0] is None else float(row[0]), kpi.unit),
    }


def _anomalies(conn, sim_date: date, classes: list[str]) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT event_id, severity, payload->>'summary'
        FROM ops.events
        WHERE event_type = 'insight' AND type = 'anomaly' AND period_end BETWEEN %s AND %s
          AND data_class = ANY(%s)
        ORDER BY CASE severity WHEN 'critical' THEN 0 ELSE 1 END, created_at
        LIMIT 20
        """,
        (sim_date - timedelta(days=1), sim_date, classes),
    ).fetchall()
    return [{"id": f"insight:{iid}", "severity": sev, "summary": text} for iid, sev, text in rows]


def build(
    conn: psycopg.Connection, kpis: list[Kpi], sim_date: date, allowed_classes: frozenset[str]
) -> dict[str, Any]:
    """Context limited to data the target provider may see; everything else is left out rather
    than raising the prompt's data class."""
    kpis = [k for k in kpis if k.data_class in allowed_classes]
    daily = [_daily_kpi(conn, k, sim_date) for k in kpis if k.grain == "day"]
    monthly = [m for k in kpis if k.grain == "month" if (m := _monthly_kpi(conn, k, sim_date))]
    return {
        "date": sim_date.isoformat(),
        "comparison": f"letzte {WINDOW_DAYS} Tage gegenüber den {WINDOW_DAYS} Tagen davor",
        "kpis": daily,
        "monthly_kpis": monthly,
        "anomalies": _anomalies(conn, sim_date, sorted(allowed_classes)),
        "data_class": highest_data_class(k.data_class for k in kpis),
    }


def render(context: dict[str, Any]) -> str:
    return json.dumps(context, ensure_ascii=False, indent=1)
