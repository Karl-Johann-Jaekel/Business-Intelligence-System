"""insight.v1 - the event contract towards consumers (email, Central-Intelligence-Agent).
Source of truth: contracts/insight.v1.schema.json; tests/test_contracts.py keeps this model and
the schema in sync. Within v1 only additive, optional fields may be added."""

import json
import uuid
from datetime import UTC, date, datetime
from typing import Any, Literal

import psycopg
from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = "insight.v1"
SOURCE = "business-intelligence-system"

InsightType = Literal["anomaly", "briefing", "forecast_deviation", "data_quality"]
Severity = Literal["info", "warning", "critical"]
SEVERITY_RANK = {"info": 0, "warning": 1, "critical": 2}
DATA_CLASS_RANK = {"public": 0, "internal": 1, "confidential": 2}


class Period(BaseModel):
    start: date
    end: date
    grain: Literal["day", "month"]


class EntityRef(BaseModel):
    type: str
    id: str


class Evidence(BaseModel):
    model_config = ConfigDict(extra="allow")

    method: str
    score: float | None = None
    query_ref: str | None = None


class Insight(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["insight.v1"] = SCHEMA_VERSION
    insight_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    source: Literal["business-intelligence-system"] = SOURCE
    type: InsightType
    kpi: str | None = None
    period: Period
    severity: Severity
    direction: Literal["up", "down"] | None = None
    observed: float | None = None
    expected: float | None = None
    deviation_pct: float | None = None
    entity_refs: list[EntityRef] = []
    evidence: Evidence
    # Link to the context package (/api/v1/context, phase K3); None until the knowledge layer exists.
    context_ref: str | None = None
    summary: str
    data_class: Literal["public", "internal", "confidential"]
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    # Type-specific content (e.g. the structured briefing). Not part of the core contract.
    details: dict[str, Any] | None = None

    def dedup_key(self) -> str:
        """Same finding for the same period and entity -> same key."""
        entity = ",".join(sorted(ref.id for ref in self.entity_refs))
        period = f"{self.period.grain}:{self.period.start}:{self.period.end}"
        return f"{self.type}:{self.kpi or '-'}:{entity}:{period}"


def save(conn: psycopg.Connection, insight: Insight) -> bool:
    """Insert into the outbox. Returns False if the same finding already exists. Does not commit."""
    row = conn.execute(
        """
        INSERT INTO ops.events (event_id, event_type, dedup_key, type, kpi, period_start, period_end,
                                severity, data_class, payload)
        VALUES (%s, 'insight', %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
        ON CONFLICT (dedup_key) DO NOTHING
        RETURNING event_id
        """,
        (
            insight.insight_id,
            insight.dedup_key(),
            insight.type,
            insight.kpi,
            insight.period.start,
            insight.period.end,
            insight.severity,
            insight.data_class,
            json.dumps(insight.model_dump(mode="json")),
        ),
    ).fetchone()
    return row is not None
