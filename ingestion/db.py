"""Warehouse helpers: ops schema DDL, raw table writes, query helpers."""

import io
from collections.abc import Sequence

import pandas as pd
import psycopg
from psycopg import sql

from ingestion.config import WAREHOUSE_DSN

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
"""

API_ROLE = "bis_api"


def ensure_api_role(conn: psycopg.Connection, password: str) -> None:
    """Read-only login role for the API. It may only read `marts` (grants are applied by dbt)."""
    exists = conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (API_ROLE,)).fetchone()
    role = sql.Identifier(API_ROLE)
    if not exists:
        conn.execute(sql.SQL("CREATE ROLE {} LOGIN").format(role))
    conn.execute(sql.SQL("ALTER ROLE {} WITH LOGIN PASSWORD {}").format(role, sql.Literal(password)))
    conn.execute(sql.SQL("ALTER ROLE {} SET default_transaction_read_only = on").format(role))
    conn.execute(sql.SQL("ALTER ROLE {} SET statement_timeout = '10s'").format(role))
    conn.execute("CREATE SCHEMA IF NOT EXISTS marts")
    conn.execute(sql.SQL("GRANT USAGE ON SCHEMA marts TO {}").format(role))
    conn.commit()


def connect(dsn: str = WAREHOUSE_DSN) -> psycopg.Connection:
    return psycopg.connect(dsn)


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
