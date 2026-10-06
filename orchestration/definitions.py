"""Dagster code location: ingestion assets (one multi-asset per source) feeding dbt assets."""

import os
import shutil
import sys

from dagster import (
    AssetCheckResult,
    AssetExecutionContext,
    AssetKey,
    AssetSelection,
    AssetSpec,
    Definitions,
    MaterializeResult,
    asset_check,
    define_asset_job,
    multi_asset,
)
from dagster_dbt import DbtCliResource, DbtProject, dbt_assets

from ingestion import clock
from ingestion.base import Connector, run_connector
from ingestion.config import REPO_ROOT
from ingestion.connectors import all_connectors
from ingestion.db import connect, ensure_ops_schema
from registry import load_registry

DBT_DIR = REPO_ROOT / "dbt"
# Resolve dbt next to the running interpreter so an un-activated virtualenv still works.
DBT_EXECUTABLE = shutil.which("dbt", path=os.path.dirname(sys.executable)) or "dbt"
dbt_project = DbtProject(project_dir=DBT_DIR, profiles_dir=DBT_DIR)
dbt_project.prepare_if_dev()


def build_ingestion_asset(connector: Connector):
    # Asset keys match dagster-dbt's default source keys ([source_name, table_name]),
    # so dbt staging models depend on these assets without extra translation.
    specs = [
        AssetSpec(
            AssetKey([connector.source, entity.name]),
            group_name="ingestion",
            kinds={"python", "postgres"},
            description=f"raw.{connector.raw_table(entity)} ({entity.mode} load)",
        )
        for entity in connector.entities
    ]

    @multi_asset(name=f"ingest_{connector.source}", specs=specs)
    def _ingest(context: AssetExecutionContext):
        with connect() as conn:
            ensure_ops_schema(conn)
            sim_date = clock.get_sim_date(conn)
            if sim_date is None:
                raise RuntimeError("Simulation clock not set. Run `bis setup`.")
            results = run_connector(conn, connector, sim_date)
        for result in results:
            context.log.info(f"{result.source}.{result.entity}: {result.rows} rows")
            yield MaterializeResult(
                asset_key=AssetKey([result.source, result.entity]),
                metadata={
                    "rows_loaded": result.rows,
                    "sim_date": sim_date.isoformat(),
                    "watermark_from": result.watermark_from or "",
                    "watermark_to": result.watermark_to or "",
                },
            )

    return _ingest


ingestion_assets = [build_ingestion_asset(c) for c in all_connectors()]


@dbt_assets(manifest=dbt_project.manifest_path)
def bis_dbt_assets(context: AssetExecutionContext, dbt: DbtCliResource):
    yield from dbt.cli(["build"], context=context).stream()


@asset_check(
    asset=AssetKey(["marts", "kpi_daily"]), description="Every daily registry KPI has rows in kpi_daily"
)
def kpi_registry_coverage() -> AssetCheckResult:
    registered = {k.key for k in load_registry() if k.grain == "day"}
    with connect() as conn:
        present = {row[0] for row in conn.execute("SELECT DISTINCT kpi_key FROM marts.kpi_daily")}
    missing = sorted(registered - present)
    return AssetCheckResult(
        passed=not missing,
        metadata={"registered": len(registered), "present": len(present), "missing": ", ".join(missing)},
    )


daily_pipeline = define_asset_job("daily_pipeline", selection=AssetSelection.all())

defs = Definitions(
    assets=[*ingestion_assets, bis_dbt_assets],
    asset_checks=[kpi_registry_coverage],
    jobs=[daily_pipeline],
    resources={"dbt": DbtCliResource(project_dir=dbt_project, dbt_executable=DBT_EXECUTABLE)},
)
