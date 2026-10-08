# Contracts

Source of truth for everything other systems consume from the Business-Intelligence-System
(plan section 10). The Central-Intelligence-Agent pins a tagged version of this directory and
validates against it in its CI.

| Contract | File | Status |
|---|---|---|
| Entity namespace `<type>:<source key>` | [entity-namespace.v1.schema.json](entity-namespace.v1.schema.json) | draft |
| `insight.v1` | [insight.v1.schema.json](insight.v1.schema.json) | draft, frozen at milestone M1 |
| `decision.v1` | – | phase K3 |
| `context.v1` | – | phase K3 |
| `action.v1` | – | phase K4 |

Examples: [examples/](examples/). `tests/test_contracts.py` validates every example, the Python
models that produce events, and live outbox payloads (when a local warehouse is available)
against these schemas.

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
| `X-BIS-Event-Id` | Event id (`insight_id`, later `decision_id`); de-duplicate on it |
| `X-BIS-Event-Type` | `schema_version` of the body, e.g. `insight.v1` |
| `X-BIS-Signature` | `sha256=<hex>`: HMAC-SHA256 of the raw body with the shared secret |

Non-2xx responses are retried with exponential backoff (at most 5 attempts).
