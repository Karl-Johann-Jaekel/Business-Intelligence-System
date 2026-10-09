# Contracts

Source of truth for the contracts between the Business-Intelligence-System (BIS) and the
Central-Intelligence-Agent (CIA) (plan section 11). The CIA pins a tagged version of this
directory and validates against it in its CI.

| Contract | Direction | File | Status |
|---|---|---|---|
| Entity namespace `<type>:<source key>` | both | [entity-namespace.v1.schema.json](entity-namespace.v1.schema.json) | draft |
| Common definitions | both | [common.v1.schema.json](common.v1.schema.json) | draft (A0) |
| `insight.v1` | BIS → CIA (webhook) | [insight.v1.schema.json](insight.v1.schema.json) | **frozen** (M1, 2026-10-09; tag `contracts-insight.v1`) |
| `daily_snapshot.v1` | BIS → CIA (webhook) | [daily_snapshot.v1.schema.json](daily_snapshot.v1.schema.json) | draft (A0) |
| `task.v1` | CIA internal, read by the BIS portal | [task.v1.schema.json](task.v1.schema.json) | draft (A0) |
| `finding.v1` | CIA internal, read by the BIS portal | [finding.v1.schema.json](finding.v1.schema.json) | draft (A0) |
| `action.v1` | CIA → BIS (`/facts`, `/actions/sim-ticket`) | [action.v1.schema.json](action.v1.schema.json) | draft (A0) |
| `agent_metrics.v1` | CIA → BIS (pulled daily into `ai_ops`) | [agent_metrics.v1.schema.json](agent_metrics.v1.schema.json) | draft (A0) |
| `decision.v1`, `context.v1` | BIS → CIA | – | phase A4 |

Drafts are tagged `contracts-v3-draft` so the CIA can start; they are frozen in phase A5.

Examples: [examples/](examples/), one consistent story per contract set (supplier outage in
`supply`, 2018-01-10). `tests/test_contracts.py` covers `insight.v1` (examples, the producing
Python model, live outbox payloads); `tests/test_agent_contracts.py` covers the agent contracts
(examples, consistency of the example story, KPI keys against the registry and a list of broken
payloads that must fail).

### Rules the schemas enforce

| Contract | Rule |
|---|---|
| `task.v1` | Top-level tasks have `depth` 1 and no parent; spawned tasks have a parent and `depth` ≥ 2. Tools only from `bi.*`, `agents.*`, `actions.*`. Every task that did not complete has a `status_reason`. |
| `finding.v1` | Every statement has evidence; a supported hypothesis has evidence; without `no_cause_found` there is at least one hypothesis. Query evidence is a BIS API path, never SQL. |
| `action.v1` | High-risk actions never run at L2. L1 actions past the proposal carry `approved_by`/`approved_at`. L0 is never executed. Executed actions have a `result_ref`, failed ones an `error`. Payloads for `create_sim_ticket`, `write_fact`, `notify_admin` are closed. |
| `agent_metrics.v1` | One record per (`sim_date`, `role`, `department`); `department` is set exactly for department agents. |

## Versioning rules

- Semantic versioning per contract; the major version is part of the name (`insight.v1`).
- Within a major version only **additive, optional** fields. Removing, renaming or tightening a
  field means a new major version, published alongside the old one for a transition period.
- `details` and other fields marked as not part of the core may change without a new version.
- Freezing: once a contract is frozen, its file is tagged (`contracts-insight.v1`) and only the
  rules above apply.

## Delivery

Events are delivered by webhook as JSON (`POST`) with:

| Header | Content |
|---|---|
| `X-BIS-Event-Id` | Event id (`insight_id`, `snapshot_id`, later `decision_id`); de-duplicate on it |
| `X-BIS-Event-Type` | `schema_version` of the body, e.g. `insight.v1`, `daily_snapshot.v1` |
| `X-BIS-Signature` | `sha256=<hex>`: HMAC-SHA256 of the raw body with the shared secret |

Non-2xx responses are retried with exponential backoff (at most 5 attempts).
