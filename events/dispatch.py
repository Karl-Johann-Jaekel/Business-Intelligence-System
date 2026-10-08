"""Outbox dispatcher: delivers ops.events to every configured consumer exactly once
(idempotent per event_id and consumer), retrying failures with exponential backoff."""

import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import timedelta

import psycopg

from events.consumers import ConsumerConfig, Sender, build_sender, load_consumers
from events.insight import DATA_CLASS_RANK, SEVERITY_RANK

log = logging.getLogger(__name__)

MAX_ATTEMPTS = 5
BASE_BACKOFF = timedelta(minutes=1)  # 1, 2, 4, 8 minutes between attempts
BATCH_SIZE = 100


@dataclass
class DispatchStats:
    enqueued: int = 0
    delivered: int = 0
    retrying: int = 0
    failed: int = 0
    inactive: list[str] = field(default_factory=list)


def enqueue(conn: psycopg.Connection, consumer: ConsumerConfig) -> int:
    """Create a delivery row per new insight; insights outside the consumer's filter are
    recorded as skipped so they are not reconsidered on every run."""
    min_rank = SEVERITY_RANK[consumer.min_severity]
    max_class = DATA_CLASS_RANK[consumer.max_data_class]
    cursor = conn.execute(
        """
        INSERT INTO ops.event_deliveries (event_id, consumer, status)
        SELECT i.event_id, %(consumer)s,
               CASE WHEN i.type = ANY(%(types)s)
                     AND (CASE i.severity WHEN 'critical' THEN 2 WHEN 'warning' THEN 1 ELSE 0 END) >= %(rank)s
                     AND (CASE i.data_class WHEN 'confidential' THEN 2 WHEN 'internal' THEN 1 ELSE 0 END)
                         <= %(max_class)s
                     -- Age in simulation time, so a backfill of past periods never floods consumers.
                     AND i.period_end >= (SELECT sim_date FROM ops.sim_clock WHERE id = 1) - %(max_age)s
                    THEN 'pending' ELSE 'skipped' END
        FROM ops.events i
        WHERE NOT EXISTS (
            SELECT 1 FROM ops.event_deliveries d
            WHERE d.event_id = i.event_id AND d.consumer = %(consumer)s
        )
        """,
        {
            "consumer": consumer.name,
            "types": list(consumer.types),
            "rank": min_rank,
            "max_age": consumer.max_age_days,
            "max_class": max_class,
        },
    )
    return cursor.rowcount


def _due(conn: psycopg.Connection, consumer: str) -> list[tuple]:
    # SKIP LOCKED: two dispatcher runs never send the same delivery twice.
    return conn.execute(
        """
        SELECT d.event_id, d.attempts, i.payload
        FROM ops.event_deliveries d JOIN ops.events i USING (event_id)
        WHERE d.consumer = %s AND d.status = 'pending' AND d.next_attempt_at <= now()
        ORDER BY i.created_at
        LIMIT %s
        FOR UPDATE OF d SKIP LOCKED
        """,
        (consumer, BATCH_SIZE),
    ).fetchall()


def deliver_pending(conn: psycopg.Connection, consumer: str, sender: Sender, stats: DispatchStats) -> None:
    for event_id, attempts, payload in _due(conn, consumer):
        try:
            sender.send(str(event_id), payload)
        except Exception as exc:  # noqa: BLE001 - any delivery error is retried
            attempts += 1
            final = attempts >= MAX_ATTEMPTS
            conn.execute(
                """
                UPDATE ops.event_deliveries
                SET attempts = %s, status = %s, last_error = %s, next_attempt_at = now() + %s
                WHERE event_id = %s AND consumer = %s
                """,
                (
                    attempts,
                    "failed" if final else "pending",
                    repr(exc)[:1000],
                    BASE_BACKOFF * 2 ** (attempts - 1),
                    event_id,
                    consumer,
                ),
            )
            log.warning("Delivery of %s to %s failed (attempt %s): %r", event_id, consumer, attempts, exc)
            if final:
                stats.failed += 1
            else:
                stats.retrying += 1
        else:
            conn.execute(
                """
                UPDATE ops.event_deliveries
                SET attempts = attempts + 1, status = 'delivered', delivered_at = now(), last_error = NULL
                WHERE event_id = %s AND consumer = %s
                """,
                (event_id, consumer),
            )
            stats.delivered += 1
        conn.commit()  # one transaction per delivery: a crash never resends delivered ones


def run(
    conn: psycopg.Connection,
    consumers: list[ConsumerConfig] | None = None,
    senders: Mapping[str, Sender] | None = None,
) -> DispatchStats:
    """Enqueue and deliver for all active consumers. `senders` overrides channels (tests)."""
    stats = DispatchStats()
    for consumer in consumers if consumers is not None else load_consumers():
        sender = (senders or {}).get(consumer.name) or build_sender(consumer)
        if sender is None:
            stats.inactive.append(consumer.name)
            continue
        stats.enqueued += enqueue(conn, consumer)
        conn.commit()
        deliver_pending(conn, consumer.name, sender, stats)
    return stats
