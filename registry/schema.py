"""KPI registry schema. One entry describes a KPI completely enough that dashboard,
anomaly detection and AI analyst need no KPI-specific code."""

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

REGISTRY_DIR = Path(__file__).resolve().parent / "kpis"

Dimension = Literal["region", "category"]


class AlertConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    method: Literal["stl_mad", "threshold"]
    # stl_mad: robust z-score cut-off on STL residuals; threshold: absolute bound on |value|.
    threshold: float = Field(gt=0)
    min_history_days: int | None = Field(default=None, ge=14)

    @model_validator(mode="after")
    def _history_only_for_stl(self) -> "AlertConfig":
        if self.method == "stl_mad" and self.min_history_days is None:
            raise ValueError("stl_mad requires min_history_days")
        if self.method == "threshold" and self.min_history_days is not None:
            raise ValueError("min_history_days only applies to stl_mad")
        return self


class Kpi(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    label: str
    description: str
    source: Literal["marts.kpi_daily", "marts.kpi_monthly"]
    grain: Literal["day", "month"]
    unit: Literal["BRL", "count", "ratio", "days", "score"]
    direction: Literal["higher_is_better", "lower_is_better", "neutral"]
    dimensions: list[Dimension] = []
    entity_type: Dimension | None = None
    alert: AlertConfig | None = None
    data_origin: Literal["real", "partly_synthetic"]
    data_class: Literal["public", "internal", "confidential"]
    owner: str

    @model_validator(mode="after")
    def _consistency(self) -> "Kpi":
        if self.entity_type is not None and self.entity_type not in self.dimensions:
            raise ValueError(f"{self.key}: entity_type must be one of its dimensions")
        expected_source = "marts.kpi_daily" if self.grain == "day" else "marts.kpi_monthly"
        if self.source != expected_source:
            raise ValueError(f"{self.key}: grain {self.grain} requires source {expected_source}")
        if len(set(self.dimensions)) != len(self.dimensions):
            raise ValueError(f"{self.key}: duplicate dimensions")
        return self


def load_registry(directory: Path = REGISTRY_DIR) -> list[Kpi]:
    """Load and validate all *.yaml files. Raises on schema errors and duplicate keys."""
    kpis: list[Kpi] = []
    for path in sorted(directory.glob("*.yaml")):
        entries = yaml.safe_load(path.read_text(encoding="utf-8")) or []
        kpis.extend(Kpi.model_validate(entry) for entry in entries)
    keys = [k.key for k in kpis]
    duplicates = sorted({k for k in keys if keys.count(k) > 1})
    if duplicates:
        raise ValueError(f"Duplicate KPI keys: {duplicates}")
    return kpis
