"""Connector interface and the generic load loop (watermarks + load log)."""

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Literal

import pandas as pd
import psycopg

from ingestion.db import write_raw

Mode = Literal["full", "incremental"]


@dataclass(frozen=True)
class Entity:
    name: str
    columns: tuple[str, ...]
    mode: Mode = "full"


@dataclass(frozen=True)
class ExtractResult:
    rows: pd.DataFrame
    # Highest watermark contained in `rows`; None keeps the previous watermark.
    watermark: str | None = None


@dataclass(frozen=True)
class LoadResult:
    source: str
    entity: str
    rows: int
    watermark_from: str | None
    watermark_to: str | None


class Connector(ABC):
    """One connector per source system. `extract` must only return data visible at `until`
    (the simulation date, inclusive) and, for incremental entities, newer than `since`."""

    source: str
    entities: tuple[Entity, ...]

    @abstractmethod
    def extract(self, entity: Entity, since: str | None, until: date) -> ExtractResult: ...

    def raw_table(self, entity: Entity) -> str:
        return f"{self.source}__{entity.name}"


def last_watermark(conn: psycopg.Connection, source: str, entity: str) -> str | None:
    row = conn.execute(
        """
        SELECT watermark_to FROM ops.load_log
        WHERE source = %(s)s AND entity = %(e)s AND status = 'success' AND watermark_to IS NOT NULL
        ORDER BY finished_at DESC LIMIT 1
        """,
        {"s": source, "e": entity},
    ).fetchone()
    return row[0] if row else None


def _log(conn, load_id, connector, entity, sim_date, wm_from, wm_to, rows, status, error, started):
    conn.execute(
        """
        INSERT INTO ops.load_log (load_id, source, entity, mode, sim_date, watermark_from,
            watermark_to, rows_loaded, status, error, started_at, finished_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())
        """,
        (
            load_id,
            connector.source,
            entity.name,
            entity.mode,
            sim_date,
            wm_from,
            wm_to,
            rows,
            status,
            error,
            started,
        ),
    )


def run_connector(conn: psycopg.Connection, connector: Connector, sim_date: date) -> list[LoadResult]:
    """Load every entity of a connector into raw. Each entity commits atomically together
    with its load-log row; a failure is logged and re-raised."""
    results = []
    for entity in connector.entities:
        load_id = str(uuid.uuid4())
        started = datetime.now(UTC)
        wm_from = (
            last_watermark(conn, connector.source, entity.name) if entity.mode == "incremental" else None
        )
        try:
            extracted = connector.extract(entity, wm_from, sim_date)
            rows = write_raw(
                conn,
                connector.raw_table(entity),
                entity.columns,
                extracted.rows,
                load_id,
                truncate=entity.mode == "full",
            )
            wm_to = extracted.watermark or wm_from
            _log(conn, load_id, connector, entity, sim_date, wm_from, wm_to, rows, "success", None, started)
            conn.commit()
        except Exception as exc:
            conn.rollback()
            _log(
                conn,
                load_id,
                connector,
                entity,
                sim_date,
                wm_from,
                None,
                None,
                "failed",
                repr(exc)[:2000],
                started,
            )
            conn.commit()
            raise
        results.append(LoadResult(connector.source, entity.name, rows, wm_from, wm_to))
    return results
