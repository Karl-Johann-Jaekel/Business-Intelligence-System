"""Validate the KPI registry and its consistency with the dbt project.

Usage: python -m registry.validate
Exit code 1 on any problem; used in CI.
"""

import sys
from pathlib import Path

import yaml

from registry.schema import Kpi, load_registry

DBT_MARTS_YML = Path(__file__).resolve().parents[1] / "dbt" / "models" / "marts" / "_marts.yml"
MODEL_FOR_SOURCE = {"marts.kpi_daily": "kpi_daily", "marts.kpi_monthly": "kpi_monthly"}


def dbt_accepted_kpi_keys(marts_yml: Path = DBT_MARTS_YML) -> dict[str, set[str]]:
    """Read the accepted_values lists for kpi_key from the dbt marts schema file."""
    doc = yaml.safe_load(marts_yml.read_text(encoding="utf-8"))
    result: dict[str, set[str]] = {}
    for model in doc["models"]:
        for column in model.get("columns", []):
            if column["name"] != "kpi_key":
                continue
            for test in column.get("data_tests", []):
                if isinstance(test, dict) and "accepted_values" in test:
                    result[model["name"]] = set(test["accepted_values"]["arguments"]["values"])
    return result


def check_against_dbt(kpis: list[Kpi], accepted: dict[str, set[str]]) -> list[str]:
    errors = []
    for kpi in kpis:
        model = MODEL_FOR_SOURCE[kpi.source]
        if kpi.key not in accepted.get(model, set()):
            errors.append(f"{kpi.key}: not produced by dbt model {model}")
    registered = {k.key for k in kpis}
    daily_keys = accepted.get("kpi_daily", set())
    for key in sorted(daily_keys - registered):
        errors.append(f"{key}: in kpi_daily but missing from registry")
    return errors


def main() -> int:
    try:
        kpis = load_registry()
    except Exception as exc:  # noqa: BLE001 - report any schema problem
        print(f"Registry invalid: {exc}", file=sys.stderr)
        return 1
    errors = check_against_dbt(kpis, dbt_accepted_kpi_keys())
    for error in errors:
        print(f"ERROR {error}", file=sys.stderr)
    if errors:
        return 1
    print(f"Registry OK: {len(kpis)} KPIs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
