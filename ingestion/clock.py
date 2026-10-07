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


def advance_for_run(conn: psycopg.Connection, run_key: str, days: int = 1) -> date:
    """Advance the clock once per run_key. A retried run with the same key gets the date
    its first attempt produced instead of skipping another day."""
    row = conn.execute("SELECT sim_date FROM ops.sim_clock WHERE id = 1 FOR UPDATE").fetchone()
    if row is None:
        conn.rollback()
        raise RuntimeError("Simulation clock not initialised. Run `bis setup` first.")
    done = conn.execute("SELECT to_date FROM ops.clock_advances WHERE run_key = %s", (run_key,)).fetchone()
    if done:
        conn.commit()
        return done[0]
    new_date = row[0] + timedelta(days=days)
    conn.execute("UPDATE ops.sim_clock SET sim_date = %s, updated_at = now() WHERE id = 1", (new_date,))
    conn.execute(
        "INSERT INTO ops.clock_advances (run_key, from_date, to_date) VALUES (%s, %s, %s)",
        (run_key, row[0], new_date),
    )
    conn.commit()
    return new_date


def advance(conn: psycopg.Connection, days: int = 1) -> date:
    current = get_sim_date(conn)
    if current is None:
        raise RuntimeError("Simulation clock not initialised. Run `bis clock set <date>` first.")
    return set_sim_date(conn, current + timedelta(days=days))
