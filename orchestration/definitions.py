"""Dagster code location: clock -> ingestion (one multi-asset per source) -> dbt -> checks."""

import os
import shutil
import sys

from dagster import AssetExecutionContext, AssetSelection, Definitions, define_asset_job
from dagster_dbt import DbtCliResource, DbtProject, dbt_assets

from ingestion.config import REPO_ROOT
from orchestration.assets import ingestion_assets, sim_clock
from orchestration.checks import kpi_checks
from orchestration.schedules import build_schedule

DBT_DIR = REPO_ROOT / "dbt"
# Resolve dbt next to the running interpreter so an un-activated virtualenv still works.
DBT_EXECUTABLE = shutil.which("dbt", path=os.path.dirname(sys.executable)) or "dbt"
dbt_project = DbtProject(project_dir=DBT_DIR, profiles_dir=DBT_DIR)
dbt_project.prepare_if_dev()


@dbt_assets(manifest=dbt_project.manifest_path)
def bis_dbt_assets(context: AssetExecutionContext, dbt: DbtCliResource):
    yield from dbt.cli(["build"], context=context).stream()


daily_pipeline = define_asset_job("daily_pipeline", selection=AssetSelection.all())

defs = Definitions(
    assets=[sim_clock, *ingestion_assets, bis_dbt_assets],
    asset_checks=kpi_checks,
    jobs=[daily_pipeline],
    schedules=[build_schedule(daily_pipeline)],
    resources={"dbt": DbtCliResource(project_dir=dbt_project, dbt_executable=DBT_EXECUTABLE)},
)
