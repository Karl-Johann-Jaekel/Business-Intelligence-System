"""Insight assets: anomaly detection -> AI briefing -> dispatch to consumers."""

from dagster import AssetExecutionContext, AssetKey, MaterializeResult, asset

from analytics import detect
from events import dispatch
from ingestion import clock
from ingestion.db import connect, ensure_ops_schema
from llm import briefing
from llm.provider import get_provider

GROUP = "insights"
ANOMALIES = AssetKey(["insights", "anomalies"])
BRIEFING = AssetKey(["insights", "briefing"])


def _sim_date(conn):
    sim_date = clock.get_sim_date(conn)
    if sim_date is None:
        raise RuntimeError("Simulation clock not set. Run `bis setup`.")
    return sim_date


@asset(
    key=ANOMALIES,
    deps=[AssetKey(["marts", "kpi_daily"]), AssetKey(["marts", "kpi_monthly"])],
    group_name=GROUP,
    kinds={"python"},
    description="Registry alert rules (stl_mad, threshold) for the simulation date -> ops.events",
)
def anomalies(context: AssetExecutionContext) -> MaterializeResult:
    with connect() as conn:
        ensure_ops_schema(conn)
        sim_date = _sim_date(conn)
        counts = detect.run(conn, sim_date)
    context.log.info(f"{sim_date}: {counts['found']} anomalies, {counts['stored']} new")
    return MaterializeResult(metadata={"sim_date": sim_date.isoformat(), **counts})


@asset(
    key=BRIEFING,
    deps=[ANOMALIES],
    group_name=GROUP,
    kinds={"python"},
    description="Daily AI analyst briefing (number guardrail) -> ops.events. "
    "Skipped without LLM credentials.",
)
def daily_briefing(context: AssetExecutionContext) -> MaterializeResult:
    provider = get_provider()
    with connect() as conn:
        sim_date = _sim_date(conn)
        if provider is None:
            result = {"status": "disabled"}
        else:
            result = briefing.run(conn, provider, sim_date)
    # A missing briefing must not stop alerting, so this asset never fails on LLM problems.
    context.log.info(f"Briefing {sim_date}: {result}")
    return MaterializeResult(
        metadata={"sim_date": sim_date.isoformat(), **{k: str(v) for k, v in result.items()}}
    )


@asset(
    key=AssetKey(["insights", "dispatch"]),
    deps=[ANOMALIES, BRIEFING],
    group_name=GROUP,
    kinds={"python"},
    description="Deliver new insights to all active consumers (email, webhooks) with retries",
)
def dispatch_insights(context: AssetExecutionContext) -> MaterializeResult:
    with connect() as conn:
        stats = dispatch.run(conn)
    context.log.info(f"Dispatch: {stats}")
    return MaterializeResult(
        metadata={
            "enqueued": stats.enqueued,
            "delivered": stats.delivered,
            "retrying": stats.retrying,
            "failed": stats.failed,
            "inactive_consumers": ", ".join(stats.inactive),
        }
    )


insight_assets = [anomalies, daily_briefing, dispatch_insights]
