"""Agent contracts (A0): daily_snapshot, task, finding, action, agent_metrics.

The Central-Intelligence-Agent pins these schemas; the tests make sure examples validate, the
rules that matter (spawn depth, approvals, evidence) are enforced and broken payloads fail."""

import copy
import json
import re
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

from registry import load_registry

CONTRACTS = Path(__file__).resolve().parents[1] / "contracts"
AGENT_CONTRACTS = ["daily_snapshot.v1", "task.v1", "finding.v1", "action.v1", "agent_metrics.v1"]


def _load(name: str) -> dict:
    return json.loads((CONTRACTS / name).read_text(encoding="utf-8"))


SCHEMAS = {path.name: _load(path.name) for path in CONTRACTS.glob("*.schema.json")}
# Schemas reference each other by file name, resolved against their $id.
REGISTRY = Registry().with_resources(
    (key, Resource.from_contents(schema)) for name, schema in SCHEMAS.items() for key in (name, schema["$id"])
)


def _errors(contract: str, instance) -> list[str]:
    validator = Draft202012Validator(
        SCHEMAS[f"{contract}.schema.json"], registry=REGISTRY, format_checker=FormatChecker()
    )
    return [f"{list(e.path)}: {e.message}" for e in validator.iter_errors(instance)]


def _example(name: str) -> dict:
    return json.loads((CONTRACTS / "examples" / name).read_text(encoding="utf-8"))


def _examples(contract: str) -> list[Path]:
    return sorted((CONTRACTS / "examples").glob(f"{contract}.*.json"))


# --- schemas and examples -------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(SCHEMAS))
def test_schema_is_valid_and_id_matches_file(name):
    Draft202012Validator.check_schema(SCHEMAS[name])
    assert SCHEMAS[name]["$id"].endswith(f"/contracts/{name}")


@pytest.mark.parametrize("contract", AGENT_CONTRACTS)
def test_every_contract_has_examples(contract):
    assert _examples(contract)


@pytest.mark.parametrize(
    "path",
    [p for c in AGENT_CONTRACTS for p in _examples(c)],
    ids=lambda p: p.name,
)
def test_examples_validate(path):
    contract = path.name.split(".")[0] + ".v1"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == contract
    assert _errors(contract, payload) == []


def test_examples_use_registry_kpis():
    """Examples must not invent KPIs: every KPI key they mention exists in the registry."""
    known = {k.key for k in load_registry()}
    text = " ".join(p.read_text(encoding="utf-8") for c in AGENT_CONTRACTS for p in _examples(c))
    mentioned = set(re.findall(r'"kpi(?:s)?":\s*\[?\s*"([a-z_]+)"', text))
    mentioned |= set(re.findall(r"kpi:([a-z_]+)", text))
    mentioned |= set(re.findall(r"/api/v1/kpis/([a-z_]+)/", text))
    assert mentioned and mentioned <= known, mentioned - known


def test_example_story_is_consistent():
    """Findings, spawned tasks and actions point at the tasks and findings that exist."""
    tasks = {t["task_id"]: t for t in map(_example_from_path, _examples("task.v1"))}
    findings = {f["finding_id"]: f for f in map(_example_from_path, _examples("finding.v1"))}
    for task in tasks.values():
        if task["parent_task_id"]:
            parent = tasks[task["parent_task_id"]]
            assert task["depth"] == parent["depth"] + 1
            assert task["requested_by"]["department"] == parent["department"]
    for finding in findings.values():
        assert tasks[finding["task_id"]]["department"] == finding["department"]
    for action in map(_example_from_path, _examples("action.v1")):
        if action["trigger"]["kind"] == "finding":
            assert action["trigger"]["id"] in findings


def _example_from_path(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# --- broken payloads must fail ----------------------------------------------------------------


def _broken(example: str, mutate) -> dict:
    payload = copy.deepcopy(_example(example))
    mutate(payload)
    return payload


def _set(path: str, value):
    def mutate(payload):
        *parents, last = path.split(".")
        node = payload
        for key in parents:
            node = node[int(key)] if key.isdigit() else node[key]
        if value is _DELETE:
            del node[last]
        else:
            node[int(last) if last.isdigit() else last] = value

    return mutate


_DELETE = object()

BROKEN = [
    # daily_snapshot
    ("daily_snapshot.v1", "daily_snapshot.v1.example.json", "departments.0.department", "legal"),
    ("daily_snapshot.v1", "daily_snapshot.v1.example.json", "departments.0.score", 1.5),
    ("daily_snapshot.v1", "daily_snapshot.v1.example.json", "sim_date", "10.01.2018"),
    ("daily_snapshot.v1", "daily_snapshot.v1.example.json", "pipeline", _DELETE),
    # task: spawn structure, tools, budget, reasons
    ("task.v1", "task.v1.delegated.json", "depth", 2),
    ("task.v1", "task.v1.spawned.json", "depth", 1),
    ("task.v1", "task.v1.spawned.json", "requested_by.department", None),
    ("task.v1", "task.v1.spawn-rejected.json", "status_reason", None),
    ("task.v1", "task.v1.delegated.json", "allowed_tools", ["sql.query"]),
    ("task.v1", "task.v1.delegated.json", "allowed_tools", []),
    ("task.v1", "task.v1.delegated.json", "budget.max_steps", 0),
    ("task.v1", "task.v1.delegated.json", "output_schema", "free_text"),
    # finding: evidence and hypotheses
    ("finding.v1", "finding.v1.supplier-outage.json", "statements.0.evidence", []),
    ("finding.v1", "finding.v1.supplier-outage.json", "hypotheses.0.evidence", []),
    ("finding.v1", "finding.v1.supplier-outage.json", "hypotheses.0.confidence", 1.2),
    ("finding.v1", "finding.v1.supplier-outage.json", "hypotheses", []),
    ("finding.v1", "finding.v1.supplier-outage.json", "statements.0.evidence.1.ref", "SELECT 1"),
    ("finding.v1", "finding.v1.supplier-outage.json", "recommended_actions.0.action_type", "delete_data"),
    # action: autonomy, approval, payloads
    ("action.v1", "action.v1.sim-ticket-executed.json", "approved_by", None),
    ("action.v1", "action.v1.sim-ticket-executed.json", "result_ref", None),
    ("action.v1", "action.v1.sim-ticket-executed.json", "autonomy_level", "L0"),
    ("action.v1", "action.v1.sim-ticket-executed.json", "payload.department", _DELETE),
    ("action.v1", "action.v1.sim-ticket-executed.json", "payload.sql", "DROP TABLE x"),
    ("action.v1", "action.v1.sim-ticket-executed.json", "evidence", []),
    ("action.v1", "action.v1.notify-proposed.json", "payload.subject", _DELETE),
    # agent_metrics
    ("agent_metrics.v1", "agent_metrics.v1.department-supply.json", "department", None),
    ("agent_metrics.v1", "agent_metrics.v1.central.json", "department", "sales"),
    ("agent_metrics.v1", "agent_metrics.v1.central.json", "metrics.error_rate", 1.5),
    ("agent_metrics.v1", "agent_metrics.v1.central.json", "metrics.spawns_rejected.cycle", _DELETE),
    ("agent_metrics.v1", "agent_metrics.v1.central.json", "metrics.cost_eur", -1),
]


@pytest.mark.parametrize(
    ("contract", "example", "path", "value"),
    BROKEN,
    ids=[f"{e.split('.v1.')[1].removesuffix('.json')}:{p}" for _, e, p, _ in BROKEN],
)
def test_broken_payload_fails(contract, example, path, value):
    assert _errors(contract, _broken(example, _set(path, value))) != []


def test_high_risk_action_cannot_run_automatically():
    action = _broken("action.v1.sim-ticket-executed.json", _set("risk", "high"))
    assert _errors("action.v1", action) == []  # L1 with approval is fine
    action["autonomy_level"] = "L2"
    assert _errors("action.v1", action) != []


def test_failed_action_names_the_error():
    action = _broken("action.v1.sim-ticket-executed.json", _set("status", "failed"))
    action["result_ref"] = None
    assert _errors("action.v1", action) != []
    action["error"] = "BI API returned 503"
    assert _errors("action.v1", action) == []
