"""Read access to the KPI marts. Fixed, parameterised queries only; table and column names
come from a closed mapping, never from request input."""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal, Protocol

import psycopg
from psycopg import sql

Grain = Literal["day", "month"]

# grain -> (table, date column)
_TABLES: dict[str, tuple[str, str]] = {
    "day": ("kpi_daily", "kpi_date"),
    "month": ("kpi_monthly", "month_start"),
}


@dataclass(frozen=True)
class Point:
    period: date
    value: float | None


@dataclass(frozen=True)
class Series:
    dimension_value: str
    entity_id: str
    points: list[Point]


@dataclass(frozen=True)
class Aggregate:
    dimension_value: str
    entity_id: str
    value: float | None


@dataclass(frozen=True)
class PipelineStatus:
    sim_date: date
    latest_kpi_date: date | None
    last_successful_load_at: datetime | None
    last_failed_load_at: datetime | None
    built_at: datetime


class Repository(Protocol):
    def status(self) -> PipelineStatus | None: ...

    def series(
        self,
        kpi: str,
        grain: Grain,
        dimension: str,
        start: date,
        end: date,
        values: list[str] | None,
        top: int,
    ) -> list[Series]: ...

    def aggregate(
        self, kpi: str, grain: Grain, dimension: str, start: date, end: date
    ) -> list[Aggregate]: ...

    def insights(
        self,
        since: date | None,
        types: list[str] | None,
        min_rank: int,
        kpi: str | None,
        limit: int,
        classes: list[str] | None = None,
    ) -> list[dict]: ...

    def latest_briefing(self) -> dict | None: ...


def _f(value) -> float | None:
    return None if value is None else float(value)


class WarehouseRepository:
    def __init__(self, conn: psycopg.Connection):
        self.conn = conn

    def status(self) -> PipelineStatus | None:
        row = self.conn.execute(
            """
            SELECT sim_date, latest_kpi_date, last_successful_load_at, last_failed_load_at, built_at
            FROM marts.pipeline_status
            """
        ).fetchone()
        return PipelineStatus(*row) if row else None

    def series(
        self,
        kpi: str,
        grain: Grain,
        dimension: str,
        start: date,
        end: date,
        values: list[str] | None,
        top: int,
    ) -> list[Series]:
        table, date_col = _TABLES[grain]
        params = {"kpi": kpi, "dim": dimension, "start": start, "end": end, "values": values, "top": top}
        # Without explicit values, keep the `top` members by volume (numerator) in the window.
        query = sql.SQL(
            """
            WITH window_rows AS (
                SELECT {date_col} AS period, dimension_value, entity_id, value, numerator
                FROM marts.{table}
                WHERE kpi_key = %(kpi)s AND dimension = %(dim)s
                  AND {date_col} BETWEEN %(start)s AND %(end)s
            ),
            members AS (
                SELECT dimension_value
                FROM window_rows
                WHERE %(values)s::text[] IS NULL OR dimension_value = ANY(%(values)s::text[])
                GROUP BY dimension_value
                ORDER BY sum(numerator) DESC NULLS LAST, dimension_value
                LIMIT CASE WHEN %(values)s::text[] IS NULL THEN %(top)s END
            )
            SELECT w.dimension_value, w.entity_id, w.period, w.value
            FROM window_rows w JOIN members m USING (dimension_value)
            ORDER BY w.dimension_value, w.period
            """
        ).format(table=sql.Identifier(table), date_col=sql.Identifier(date_col))

        grouped: dict[str, Series] = {}
        for dim_value, entity_id, period, value in self.conn.execute(query, params):
            series = grouped.setdefault(dim_value, Series(dim_value, entity_id, []))
            series.points.append(Point(period, _f(value)))
        return list(grouped.values())

    def aggregate(self, kpi: str, grain: Grain, dimension: str, start: date, end: date) -> list[Aggregate]:
        table, date_col = _TABLES[grain]
        # Ratios are re-aggregated from numerator/denominator, never averaged.
        query = sql.SQL(
            """
            SELECT dimension_value, entity_id,
                   CASE WHEN bool_and(aggregation = 'sum') THEN sum(numerator)
                        ELSE sum(numerator) / nullif(sum(denominator), 0) END
            FROM marts.{table}
            WHERE kpi_key = %(kpi)s AND dimension = %(dim)s
              AND {date_col} BETWEEN %(start)s AND %(end)s
            GROUP BY dimension_value, entity_id
            """
        ).format(table=sql.Identifier(table), date_col=sql.Identifier(date_col))
        rows = self.conn.execute(query, {"kpi": kpi, "dim": dimension, "start": start, "end": end})
        return [Aggregate(dim_value, entity_id, _f(value)) for dim_value, entity_id, value in rows]

    def insights(
        self,
        since: date | None,
        types: list[str] | None,
        min_rank: int,
        kpi: str | None,
        limit: int,
        classes: list[str] | None = None,
    ) -> list[dict]:
        rows = self.conn.execute(
            """
            SELECT payload FROM ops.events
            WHERE event_type = 'insight'
              AND (%(since)s::date IS NULL OR period_end >= %(since)s)
              AND (%(types)s::text[] IS NULL OR type = ANY(%(types)s))
              AND (CASE severity WHEN 'critical' THEN 2 WHEN 'warning' THEN 1 ELSE 0 END) >= %(rank)s
              AND (%(kpi)s::text IS NULL OR kpi = %(kpi)s)
              AND (%(classes)s::text[] IS NULL OR data_class = ANY(%(classes)s))
            ORDER BY period_end DESC, CASE severity WHEN 'critical' THEN 0 WHEN 'warning' THEN 1 ELSE 2 END,
                     created_at DESC
            LIMIT %(limit)s
            """,
            {
                "since": since,
                "types": types,
                "rank": min_rank,
                "kpi": kpi,
                "limit": limit,
                "classes": classes,
            },
        ).fetchall()
        return [row[0] for row in rows]

    def latest_briefing(self) -> dict | None:
        row = self.conn.execute(
            """
            SELECT payload FROM ops.events WHERE event_type = 'insight' AND type = 'briefing'
            ORDER BY period_end DESC, created_at DESC LIMIT 1
            """
        ).fetchone()
        return row[0] if row else None
