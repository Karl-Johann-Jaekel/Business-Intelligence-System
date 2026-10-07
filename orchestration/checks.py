"""Asset checks on the KPI marts (freshness relative to the simulation clock, registry coverage)."""

from dagster import AssetCheckResult, AssetKey, asset_check

from ingestion import clock
from ingestion.db import connect
from registry import load_registry

KPI_DAILY = AssetKey(["marts", "kpi_daily"])


@asset_check(asset=KPI_DAILY, description="kpi_daily contains the current simulation date")
def kpi_daily_current() -> AssetCheckResult:
    # Wall-clock freshness is meaningless in a replay; compare against the simulation date.
    with connect() as conn:
        sim_date = clock.get_sim_date(conn)
        latest = conn.execute("SELECT max(kpi_date) FROM marts.kpi_daily").fetchone()[0]
    return AssetCheckResult(
        passed=latest is not None and latest == sim_date,
        metadata={"sim_date": str(sim_date), "latest_kpi_date": str(latest)},
    )


@asset_check(asset=KPI_DAILY, description="Every daily registry KPI has rows in kpi_daily")
def kpi_registry_coverage() -> AssetCheckResult:
    registered = {k.key for k in load_registry() if k.grain == "day"}
    with connect() as conn:
        present = {row[0] for row in conn.execute("SELECT DISTINCT kpi_key FROM marts.kpi_daily")}
    missing = sorted(registered - present)
    return AssetCheckResult(
        passed=not missing,
        metadata={"registered": len(registered), "present": len(present), "missing": ", ".join(missing)},
    )


kpi_checks = [kpi_daily_current, kpi_registry_coverage]
