"""Warehouse helpers: ops schema DDL, raw table writes, query helpers."""

import io
from collections.abc import Sequence

import pandas as pd
import psycopg
from psycopg import sql

from ingestion.config import warehouse_dsn

OPS_DDL = """
CREATE SCHEMA IF NOT EXISTS raw;
CREATE SCHEMA IF NOT EXISTS ops;

CREATE TABLE IF NOT EXISTS ops.sim_clock (
    id          smallint PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    sim_date    date NOT NULL,
    updated_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ops.load_log (
    load_id         uuid PRIMARY KEY,
    source          text NOT NULL,
    entity          text NOT NULL,
    mode            text NOT NULL,
    sim_date        date NOT NULL,
    watermark_from  text,
    watermark_to    text,
    rows_loaded     integer,
    status          text NOT NULL CHECK (status IN ('success', 'failed')),
    error           text,
    started_at      timestamptz NOT NULL,
    finished_at     timestamptz NOT NULL
);
CREATE INDEX IF NOT EXISTS load_log_source_entity_idx
    ON ops.load_log (source, entity, finished_at DESC);

-- One row per pipeline run that advanced the clock; makes retries idempotent.
CREATE TABLE IF NOT EXISTS ops.clock_advances (
    run_key      text PRIMARY KEY,
    from_date    date NOT NULL,
    to_date      date NOT NULL,
    advanced_at  timestamptz NOT NULL DEFAULT now()
);

-- pgvector for the knowledge layer (A4); requires the pgvector image.
CREATE EXTENSION IF NOT EXISTS vector;

-- Migration 2026-10-08 (plan v2): the outbox carries several event types (insight.v1,
-- decision.v1), so ops.insights becomes ops.events. Idempotent.
DO $migrate$
BEGIN
    IF to_regclass('ops.insights') IS NOT NULL AND to_regclass('ops.events') IS NULL THEN
        ALTER TABLE ops.insights RENAME TO events;
        ALTER TABLE ops.events RENAME COLUMN insight_id TO event_id;
        ALTER INDEX IF EXISTS ops.insights_period_idx RENAME TO events_period_idx;
        ALTER TABLE ops.insight_deliveries RENAME TO event_deliveries;
        ALTER TABLE ops.event_deliveries RENAME COLUMN insight_id TO event_id;
    END IF;
END
$migrate$;

-- Outbox for all events. dedup_key makes producers idempotent: re-running the same day never
-- creates a second event for the same finding. Insight-specific columns are NULL for other types.
CREATE TABLE IF NOT EXISTS ops.events (
    event_id      uuid PRIMARY KEY,
    event_type    text NOT NULL DEFAULT 'insight' CHECK (event_type IN ('insight', 'decision')),
    dedup_key     text NOT NULL UNIQUE,
    type          text CHECK (type IN ('anomaly', 'briefing', 'forecast_deviation', 'data_quality')),
    kpi           text,
    period_start  date,
    period_end    date,
    severity      text CHECK (severity IN ('info', 'warning', 'critical')),
    data_class    text NOT NULL DEFAULT 'public' CHECK (data_class IN ('public', 'internal', 'confidential')),
    payload       jsonb NOT NULL,
    created_at    timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE ops.events ADD COLUMN IF NOT EXISTS event_type text NOT NULL DEFAULT 'insight'
    CHECK (event_type IN ('insight', 'decision'));
ALTER TABLE ops.events ADD COLUMN IF NOT EXISTS data_class text NOT NULL DEFAULT 'public'
    CHECK (data_class IN ('public', 'internal', 'confidential'));
ALTER TABLE ops.events ALTER COLUMN type DROP NOT NULL;
ALTER TABLE ops.events ALTER COLUMN period_start DROP NOT NULL;
ALTER TABLE ops.events ALTER COLUMN period_end DROP NOT NULL;
ALTER TABLE ops.events ALTER COLUMN severity DROP NOT NULL;
UPDATE ops.events SET data_class = payload->>'data_class'
    WHERE payload ? 'data_class' AND data_class IS DISTINCT FROM payload->>'data_class';
CREATE INDEX IF NOT EXISTS events_period_idx ON ops.events (period_end DESC, type);

-- Delivery state per event and consumer (email, webhooks). Retried with backoff.
CREATE TABLE IF NOT EXISTS ops.event_deliveries (
    event_id         uuid NOT NULL REFERENCES ops.events ON DELETE CASCADE,
    consumer         text NOT NULL,
    status           text NOT NULL CHECK (status IN ('pending', 'delivered', 'failed', 'skipped')),
    attempts         integer NOT NULL DEFAULT 0,
    next_attempt_at  timestamptz NOT NULL DEFAULT now(),
    last_error       text,
    delivered_at     timestamptz,
    PRIMARY KEY (event_id, consumer)
);
"""

API_ROLE = "bis_api"


def ensure_api_role(conn: psycopg.Connection, password: str) -> None:
    """Read-only login role for the API: `marts` (grants applied by dbt) and `ops.events`.
    Requires ensure_ops_schema() first."""
    exists = conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (API_ROLE,)).fetchone()
    role = sql.Identifier(API_ROLE)
    if not exists:
        conn.execute(sql.SQL("CREATE ROLE {} LOGIN").format(role))
    conn.execute(sql.SQL("ALTER ROLE {} WITH LOGIN PASSWORD {}").format(role, sql.Literal(password)))
    conn.execute(sql.SQL("ALTER ROLE {} SET default_transaction_read_only = on").format(role))
    conn.execute(sql.SQL("ALTER ROLE {} SET statement_timeout = '10s'").format(role))
    conn.execute("CREATE SCHEMA IF NOT EXISTS marts")
    conn.execute(sql.SQL("GRANT USAGE ON SCHEMA marts TO {}").format(role))
    # Besides marts the API may read the event outbox, nothing else in ops.
    conn.execute(sql.SQL("GRANT USAGE ON SCHEMA ops TO {}").format(role))
    conn.execute(sql.SQL("GRANT SELECT ON ops.events TO {}").format(role))
    conn.commit()


def connect(dsn: str | None = None) -> psycopg.Connection:
    return psycopg.connect(dsn or warehouse_dsn())


def ensure_ops_schema(conn: psycopg.Connection) -> None:
    conn.execute(OPS_DDL)
    conn.commit()


def query_df(conn: psycopg.Connection, query: str, params: dict | None = None) -> pd.DataFrame:
    """Run a query and return all values as strings (None stays None)."""
    with conn.cursor() as cur:
        cur.execute(query, params or {})
        columns = [c.name for c in cur.description]
        rows = [[None if v is None else str(v) for v in row] for row in cur.fetchall()]
    return pd.DataFrame(rows, columns=columns, dtype=object)


def write_raw(
    conn: psycopg.Connection,
    table: str,
    columns: Sequence[str],
    df: pd.DataFrame,
    load_id: str,
    truncate: bool,
) -> int:
    """Append (or replace) rows in raw.<table>. All business columns are stored as text;
    typing happens in dbt staging. Does not commit."""
    ident = sql.Identifier("raw", table)
    col_defs = sql.SQL(", ").join(
        [sql.SQL("{} text").format(sql.Identifier(c)) for c in columns]
        + [sql.SQL("_load_id uuid NOT NULL"), sql.SQL("_loaded_at timestamptz NOT NULL DEFAULT now()")]
    )
    conn.execute(sql.SQL("CREATE TABLE IF NOT EXISTS {} ({})").format(ident, col_defs))
    if truncate:
        conn.execute(sql.SQL("TRUNCATE {}").format(ident))
    if df.empty:
        return 0

    out = df.reindex(columns=list(columns)).copy()
    out["_load_id"] = load_id
    buf = io.StringIO()
    out.to_csv(buf, index=False, header=False)
    buf.seek(0)
    target_cols = sql.SQL(", ").join(sql.Identifier(c) for c in [*columns, "_load_id"])
    copy_stmt = sql.SQL("COPY {} ({}) FROM STDIN WITH (FORMAT csv)").format(ident, target_cols)
    with conn.cursor() as cur, cur.copy(copy_stmt) as copy:
        copy.write(buf.read())
    return len(out)
