import pytest
from pydantic import ValidationError

from registry.schema import Kpi, load_registry
from registry.validate import check_against_dbt, dbt_accepted_kpi_keys

BASE = {
    "key": "example_kpi",
    "label": "Example",
    "description": "Example KPI",
    "source": "marts.kpi_daily",
    "grain": "day",
    "unit": "count",
    "direction": "higher_is_better",
    "dimensions": ["region"],
    "entity_type": "region",
    "data_origin": "real",
    "data_class": "public",
    "owner": "sales",
}


def test_registry_loads_and_has_at_least_eight_kpis():
    kpis = load_registry()
    assert len(kpis) >= 8


def test_registry_matches_dbt_models():
    assert check_against_dbt(load_registry(), dbt_accepted_kpi_keys()) == []


def test_stl_mad_requires_min_history():
    with pytest.raises(ValidationError, match="min_history_days"):
        Kpi.model_validate({**BASE, "alert": {"method": "stl_mad", "threshold": 3.5}})


def test_entity_type_must_be_a_dimension():
    with pytest.raises(ValidationError, match="entity_type"):
        Kpi.model_validate({**BASE, "dimensions": [], "entity_type": "region"})


def test_grain_and_source_must_agree():
    with pytest.raises(ValidationError, match="requires source"):
        Kpi.model_validate({**BASE, "grain": "month"})


def test_unknown_fields_are_rejected():
    with pytest.raises(ValidationError):
        Kpi.model_validate({**BASE, "colour": "red"})


def test_missing_dbt_key_is_reported():
    kpi = Kpi.model_validate(BASE)
    errors = check_against_dbt([kpi], {"kpi_daily": {"other_kpi"}})
    assert "example_kpi: not produced by dbt model kpi_daily" in errors
    assert "other_kpi: in kpi_daily but missing from registry" in errors
