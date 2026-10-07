"""Simulation clock and ingestion assets."""

from dagster import (
    AssetCheckResult,
    AssetCheckSeverity,
    AssetCheckSpec,
    AssetExecutionContext,
    AssetKey,
    AssetSpec,
    Backoff,
    Config,
    MaterializeResult,
    RetryPolicy,
    asset,
    multi_asset,
)
from psycopg import sql

from ingestion import clock
from ingestion.base import Connector, run_connector
from ingestion.connectors import all_connectors
from ingestion.db import connect, ensure_ops_schema

# Same key as the dbt source `ops.sim_clock`, so dbt models depend on this asset.
CLOCK_KEY = AssetKey(["ops", "sim_clock"])
CLOCK_OP_NAME = CLOCK_KEY.to_python_identifier()

# Transient source errors (API down, DB restart) are retried within the run.
INGESTION_RETRY = RetryPolicy(max_retries=2, delay=10, backoff=Backoff.EXPONENTIAL)


class ClockConfig(Config):
    advance_days: int = 0


@asset(key=CLOCK_KEY, group_name="simulation", kinds={"postgres"})
def sim_clock(context: AssetExecutionContext, config: ClockConfig) -> MaterializeResult:
    """Simulation date. The daily schedule advances it by one day per run; manual runs keep it."""
    with connect() as conn:
        ensure_ops_schema(conn)
        if config.advance_days > 0:
            # Retries and re-executions share the root run id, so the clock moves only once.
            run_key = context.run.root_run_id or context.run_id
            sim_date = clock.advance_for_run(conn, run_key, config.advance_days)
        else:
            sim_date = clock.get_sim_date(conn)
    if sim_date is None:
        raise RuntimeError("Simulation clock not set. Run `bis setup`.")
    context.log.info(f"Simulation date: {sim_date}")
    return MaterializeResult(metadata={"sim_date": sim_date.isoformat()})


def _table_rows(conn, table: str) -> int:
    query = sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier("raw", table))
    return conn.execute(query).fetchone()[0]


def build_ingestion_asset(connector: Connector):
    # Asset keys match dagster-dbt's default source keys ([source_name, table_name]),
    # so dbt staging models depend on these assets without extra translation.
    keys = {entity.name: AssetKey([connector.source, entity.name]) for entity in connector.entities}
    specs = [
        AssetSpec(
            keys[entity.name],
            deps=[CLOCK_KEY],
            group_name="ingestion",
            kinds={"python", "postgres"},
            description=f"raw.{connector.raw_table(entity)} ({entity.mode} load)",
        )
        for entity in connector.entities
    ]
    check_specs = [AssetCheckSpec("rows_present", asset=key) for key in keys.values()] + [
        AssetCheckSpec("new_rows_loaded", asset=keys[e.name])
        for e in connector.entities
        if e.mode == "incremental"
    ]
    modes = {entity.name: entity.mode for entity in connector.entities}

    @multi_asset(
        name=f"ingest_{connector.source}",
        specs=specs,
        check_specs=check_specs,
        retry_policy=INGESTION_RETRY,
    )
    def _ingest(context: AssetExecutionContext):
        with connect() as conn:
            ensure_ops_schema(conn)
            sim_date = clock.get_sim_date(conn)
            if sim_date is None:
                raise RuntimeError("Simulation clock not set. Run `bis setup`.")
            results = run_connector(conn, connector, sim_date)
            table_rows = {r.entity: _table_rows(conn, f"{r.source}__{r.entity}") for r in results}

        for result in results:
            key = keys[result.entity]
            context.log.info(f"{result.source}.{result.entity}: {result.rows} rows")
            yield MaterializeResult(
                asset_key=key,
                metadata={
                    "rows_loaded": result.rows,
                    "table_rows": table_rows[result.entity],
                    "sim_date": sim_date.isoformat(),
                    "watermark_from": result.watermark_from or "",
                    "watermark_to": result.watermark_to or "",
                },
            )
            yield AssetCheckResult(
                asset_key=key,
                check_name="rows_present",
                passed=table_rows[result.entity] > 0,
                metadata={"table_rows": table_rows[result.entity]},
            )
            if modes[result.entity] == "incremental":
                # Quiet days happen (e.g. holidays), so an empty increment is only a warning.
                yield AssetCheckResult(
                    asset_key=key,
                    check_name="new_rows_loaded",
                    passed=result.rows > 0,
                    severity=AssetCheckSeverity.WARN,
                    metadata={"rows_loaded": result.rows, "sim_date": sim_date.isoformat()},
                )

    return _ingest


ingestion_assets = [build_ingestion_asset(c) for c in all_connectors()]
