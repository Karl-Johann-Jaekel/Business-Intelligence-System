"""contracts/ is the source of truth; producers and examples must validate against it."""

import json
from datetime import date
from pathlib import Path

import psycopg
import pytest
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

from events.insight import EntityRef, Evidence, Insight, Period
from ingestion.db import connect

CONTRACTS = Path(__file__).resolve().parents[1] / "contracts"


def _load(name: str) -> dict:
    return json.loads((CONTRACTS / name).read_text(encoding="utf-8"))


NAMESPACE = _load("entity-namespace.v1.schema.json")
INSIGHT = _load("insight.v1.schema.json")
REGISTRY = Registry().with_resources(
    [
        ("entity-namespace.v1.schema.json", Resource.from_contents(NAMESPACE)),
        (NAMESPACE["$id"], Resource.from_contents(NAMESPACE)),
    ]
)


def _validator(schema: dict) -> Draft202012Validator:
    return Draft202012Validator(schema, registry=REGISTRY, format_checker=FormatChecker())


def _errors(schema: dict, instance) -> list[str]:
    return [f"{list(e.path)}: {e.message}" for e in _validator(schema).iter_errors(instance)]


ENTITY_ID = {"$ref": "entity-namespace.v1.schema.json#/$defs/entity_id"}


def test_schemas_are_valid_json_schema():
    Draft202012Validator.check_schema(NAMESPACE)
    Draft202012Validator.check_schema(INSIGHT)


@pytest.mark.parametrize(
    "example", sorted((CONTRACTS / "examples").glob("insight.v1.*.json")), ids=lambda p: p.name
)
def test_examples_validate(example):
    assert _errors(INSIGHT, json.loads(example.read_text(encoding="utf-8"))) == []


def test_python_model_matches_schema_fields():
    """Drift guard: every field of the producer model is in the schema and vice versa."""
    assert set(Insight.model_fields) == set(INSIGHT["properties"])
    required = {name for name, field in Insight.model_fields.items() if field.is_required()}
    # Fields with defaults (id, timestamps, version) are always serialised, so they may be required.
    assert required <= set(INSIGHT["required"])


def test_model_output_validates():
    insight = Insight(
        type="anomaly",
        kpi="gmv",
        period=Period(start=date(2018, 1, 8), end=date(2018, 1, 8), grain="day"),
        severity="critical",
        direction="up",
        observed=38714.4,
        expected=14488.32,
        deviation_pct=167.2,
        entity_refs=[
            EntityRef(type="category", id="category:computers_accessories"),
            EntityRef(type="kpi", id="kpi:gmv"),
        ],
        evidence=Evidence(method="stl_mad", score=6.2, query_ref="/api/v1/kpis/gmv/series"),
        summary="x",
        data_class="public",
    )
    assert _errors(INSIGHT, insight.model_dump(mode="json")) == []


@pytest.mark.parametrize(
    ("entity_id", "valid"),
    [
        ("kpi:delivery_time_avg_days", True),
        ("region:SP", True),
        ("region:sp", False),
        ("category:health_beauty", True),
        ("person:leitung-logistik", True),
        ("person:Leitung Logistik", False),
        ("customer:861eff4711a542e4b93843c6dd7febb0", True),
        ("delivery_time_avg_days", False),
    ],
)
def test_entity_namespace_patterns(entity_id, valid):
    assert (_errors(ENTITY_ID, entity_id) == []) is valid


# --- live data (skipped without a local warehouse) -----------------------------------------


def _db_available() -> bool:
    try:
        with connect() as conn:
            conn.execute("SELECT 1 FROM ops.events LIMIT 1")
        return True
    except (psycopg.Error, RuntimeError):
        return False


needs_db = pytest.mark.skipif(not _db_available(), reason="warehouse not reachable")


@needs_db
def test_outbox_payloads_validate():
    with connect() as conn:
        rows = conn.execute(
            "SELECT payload FROM ops.events WHERE event_type = 'insight' ORDER BY created_at DESC LIMIT 200"
        ).fetchall()
    problems = {e for (payload,) in rows for e in _errors(INSIGHT, payload)}
    assert problems == set()


@needs_db
@pytest.mark.parametrize(
    "query",
    [
        "SELECT entity_id FROM marts.dim_region",
        "SELECT entity_id FROM marts.dim_customer LIMIT 500",
        "SELECT entity_id FROM marts.dim_product LIMIT 500",
        "SELECT DISTINCT category_entity_id FROM marts.dim_product",
        "SELECT entity_id FROM marts.dim_seller LIMIT 500",
        "SELECT DISTINCT entity_id FROM marts.kpi_daily",
    ],
)
def test_warehouse_entity_ids_follow_namespace(query):
    with connect() as conn:
        ids = [row[0] for row in conn.execute(query).fetchall()]
    assert ids
    assert [i for i in ids if _errors(ENTITY_ID, i)] == []
