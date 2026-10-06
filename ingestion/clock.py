"""Simulation clock. Olist data is historical; each pipeline run releases data up to sim_date."""

from datetime import date, timedelta

import psycopg


def get_sim_date(conn: psycopg.Connection) -> date | None:
    row = conn.execute("SELECT sim_date FROM ops.sim_clock WHERE id = 1").fetchone()
    return row[0] if row else None


def set_sim_date(conn: psycopg.Connection, value: date) -> date:
    conn.execute(
        """
        INSERT INTO ops.sim_clock (id, sim_date) VALUES (1, %(d)s)
        ON CONFLICT (id) DO UPDATE SET sim_date = EXCLUDED.sim_date, updated_at = now()
        """,
        {"d": value},
    )
    conn.commit()
    return value


def advance(conn: psycopg.Connection, days: int = 1) -> date:
    current = get_sim_date(conn)
    if current is None:
        raise RuntimeError("Simulation clock not initialised. Run `bis clock set <date>` first.")
    return set_sim_date(conn, current + timedelta(days=days))
