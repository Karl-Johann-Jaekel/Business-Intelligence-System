from datetime import date

import numpy as np
import pandas as pd
import pytest

from analytics import anomaly
from analytics.detect import latest_complete_month
from analytics.text import format_signed_pct, format_value
from events.insight import EntityRef, Evidence, Insight, Period


def _weekly_series(days: int = 120, seed: int = 0) -> pd.Series:
    """Level 100 with a weekday pattern and mild noise."""
    rng = np.random.default_rng(seed)
    index = pd.date_range("2018-01-01", periods=days, freq="D").date
    weekday = np.array([0, 5, 8, 6, 3, -10, -12])[np.arange(days) % 7]
    return pd.Series(100 + weekday + rng.normal(0, 2, days), index=index)


def test_normal_day_is_not_flagged():
    det = anomaly.stl_mad(_weekly_series(), threshold=3.5, min_history_days=56)
    assert det is not None and not det.is_anomaly


def test_spike_on_last_day_is_flagged_with_direction_and_expected_value():
    series = _weekly_series()
    expected_before = anomaly.stl_mad(series, 3.5, 56).expected
    series.iloc[-1] += 40
    det = anomaly.stl_mad(series, 3.5, 56)
    assert det.is_anomaly and det.severity == "critical" and det.direction == "up"
    assert det.expected == pytest.approx(expected_before, abs=0.01)
    assert det.deviation_pct > 30


def test_weekday_pattern_is_not_an_anomaly():
    # The weekend dip (-12) is large relative to noise but expected by the weekly component.
    series = _weekly_series(days=119)
    assert pd.Timestamp(series.index[-1]).dayofweek == 6
    assert not anomaly.stl_mad(series, 3.5, 56).is_anomaly


def test_insufficient_history_or_missing_value_returns_none():
    series = _weekly_series()
    assert anomaly.stl_mad(series.iloc[-30:], 3.5, 56) is None
    series.iloc[-1] = np.nan
    assert anomaly.stl_mad(series, 3.5, 56) is None


def test_gaps_in_history_are_tolerated():
    series = _weekly_series()
    series.iloc[40:45] = np.nan
    series.iloc[-1] -= 40
    det = anomaly.stl_mad(series, 3.5, 56)
    assert det.is_anomaly and det.direction == "down"


def test_threshold_method_severity():
    assert not anomaly.threshold(0.2, 0.25).is_anomaly
    assert anomaly.threshold(-0.3, 0.25).severity == "warning"
    assert anomaly.threshold(0.6, 0.25).severity == "critical"
    assert anomaly.threshold(None, 0.25) is None


def test_latest_complete_month():
    assert latest_complete_month(date(2018, 1, 31)) == date(2018, 1, 1)
    assert latest_complete_month(date(2018, 2, 1)) == date(2018, 1, 1)
    assert latest_complete_month(date(2018, 3, 15)) == date(2018, 2, 1)


def test_german_formatting():
    assert format_value(1234.5, "BRL") == "1.234,50 R$"
    assert format_value(0.0214, "ratio") == "2,14 %"
    assert format_value(8.2, "multiple") == "8,20×"
    assert format_value(12.86, "days") == "12,9 Tage"
    assert format_value(1.1428, "count") == "1,14"
    assert format_signed_pct(-12.34) == "−12,3 %"


def _insight(**overrides) -> Insight:
    base = dict(
        type="anomaly",
        kpi="gmv",
        period=Period(start=date(2018, 1, 5), end=date(2018, 1, 5), grain="day"),
        severity="warning",
        entity_refs=[EntityRef(type="region", id="region:SP"), EntityRef(type="kpi", id="kpi:gmv")],
        evidence=Evidence(method="stl_mad", score=4.2),
        summary="x",
        data_class="public",
    )
    return Insight(**(base | overrides))


def test_dedup_key_is_stable_per_finding_and_distinguishes_entities():
    a, b = _insight(), _insight(severity="critical")
    assert a.insight_id != b.insight_id
    assert a.dedup_key() == b.dedup_key()
    other = _insight(entity_refs=[EntityRef(type="region", id="region:RJ")])
    assert other.dedup_key() != a.dedup_key()


def test_insight_serialises_to_contract_fields():
    payload = _insight().model_dump(mode="json")
    assert payload["schema_version"] == "insight.v1"
    assert payload["source"] == "business-intelligence-system"
    assert payload["period"] == {"start": "2018-01-05", "end": "2018-01-05", "grain": "day"}
