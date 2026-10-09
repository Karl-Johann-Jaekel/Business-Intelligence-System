"""Records the token usage of LLM calls in ops.llm_usage (admin cost view)."""

import os
from datetime import date

import psycopg

from llm.provider import Usage


def _price(provider: str, direction: str) -> float:
    """EUR per million tokens, e.g. BIS_LLM_PRICE_MISTRAL_IN. Free tier and unset: 0."""
    return float(os.getenv(f"BIS_LLM_PRICE_{provider.upper()}_{direction}", "0") or 0)


def cost_eur(usage: Usage) -> float:
    return (
        usage.tokens_in * _price(usage.provider, "IN") + usage.tokens_out * _price(usage.provider, "OUT")
    ) / 1_000_000


def record(conn: psycopg.Connection, purpose: str, calls: list[Usage], sim_date: date | None = None) -> None:
    for usage in calls:
        conn.execute(
            """
            INSERT INTO ops.llm_usage (purpose, provider, model, sim_date, tokens_in, tokens_out, cost_eur)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                purpose,
                usage.provider,
                usage.model,
                sim_date,
                usage.tokens_in,
                usage.tokens_out,
                cost_eur(usage),
            ),
        )
