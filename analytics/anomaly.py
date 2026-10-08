"""Anomaly detection methods referenced by the KPI registry (`alert.method`).

stl_mad:   weekday effect from an STL decomposition (weekly period) of the trailing window;
           level = rolling median of the deseasonalised previous 14 days. The day is scored by
           its deviation from level + weekday effect, scaled robustly (median / MAD) by the same
           one-step errors over the window.
threshold: fixed bound on |value| (e.g. monthly budget deviation).

Both look only at data up to the evaluated period, so detection works "online" during replay.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd
from statsmodels.tsa.seasonal import STL

WEEKLY_PERIOD = 7
WINDOW_DAYS = 120
LEVEL_DAYS = 14  # causal level: median of the last two weeks (deseasonalised)
SCALE_FLOOR = 0.01  # minimum spread: 1 % of the current level
WEEKDAY_WEEKS = 4  # weekday effect = median of the last 4 same weekdays
MAD_TO_SIGMA = 1.4826  # MAD of a normal distribution * 1.4826 = standard deviation
CRITICAL_FACTOR = 1.5  # score >= threshold * 1.5 -> critical


@dataclass(frozen=True)
class Detection:
    observed: float
    expected: float
    score: float
    is_anomaly: bool
    severity: str | None  # "warning" | "critical" | None

    @property
    def direction(self) -> str:
        return "up" if self.observed >= self.expected else "down"

    @property
    def deviation_pct(self) -> float | None:
        if self.expected == 0:
            return None
        return round((self.observed - self.expected) / abs(self.expected) * 100, 2)


def _severity(score: float, threshold: float) -> str | None:
    if abs(score) >= threshold * CRITICAL_FACTOR:
        return "critical"
    if abs(score) >= threshold:
        return "warning"
    return None


def stl_mad(series: pd.Series, threshold: float, min_history_days: int) -> Detection | None:
    """Evaluate the last point of a daily series (index = consecutive days, NaN = no data).

    Returns None when the last value is missing or there is not enough history.
    """
    window = series.astype(float).iloc[-WINDOW_DAYS:]
    observed = window.iloc[-1]
    if np.isnan(observed) or window.iloc[:-1].notna().sum() < min_history_days:
        return None

    # STL is fitted on the history only and used for the weekday effect. The level is a causal
    # rolling median of the deseasonalised values, applied identically to history and target,
    # so the error scale matches what is scored. (A centred STL trend "sees" the evaluated day:
    # fitted on the target it hid spikes, fitted on history it understated errors ~5x.)
    history = window.iloc[:-1]
    seasonal = _weekday_effect(history)
    deseason = window - seasonal.reindex(window.index).to_numpy()
    level = deseason.shift(1).rolling(LEVEL_DAYS, min_periods=LEVEL_DAYS // 2).median()
    errors = (deseason - level).iloc[:-1].dropna()
    if len(errors) < min_history_days // 2:
        return None
    center = errors.median()
    scale = MAD_TO_SIGMA * (errors - center).abs().median()
    if not np.isfinite(scale) or np.isnan(level.iloc[-1]):
        return None
    # Floor: when most days carry the same value (e.g. 100 % on-time), the MAD collapses and a
    # tiny change would score in the hundreds.
    scale = max(scale, SCALE_FLOOR * abs(float(level.iloc[-1])), 1e-9)

    # Weekday effect: median over the last weeks' same weekday. Taking only the last one let a
    # holiday define it (2018-01-08 inherited New Year's dip: expected 63 orders instead of ~200).
    same_weekday = seasonal.iloc[-WEEKLY_PERIOD * WEEKDAY_WEEKS :: WEEKLY_PERIOD]
    expected = float(level.iloc[-1] + same_weekday.median() + center)
    score = float((observed - expected) / scale)
    severity = _severity(score, threshold)
    return Detection(float(observed), expected, round(score, 3), severity is not None, severity)


def _weekday_effect(history: pd.Series) -> pd.Series:
    """Seasonal (weekly) component of a robust STL fit, extended by one week periodically."""
    filled = history.interpolate(limit_direction="both")
    fit = STL(filled.to_numpy(), period=WEEKLY_PERIOD, robust=True).fit()
    seasonal = pd.Series(fit.seasonal, index=history.index)
    return seasonal


def threshold(value: float | None, bound: float) -> Detection | None:
    """|value| above bound is an anomaly; the expected value is 0 (e.g. no budget deviation)."""
    if value is None or np.isnan(value):
        return None
    score = abs(value) / bound
    severity = None
    if score >= 2:
        severity = "critical"
    elif score >= 1:
        severity = "warning"
    return Detection(float(value), 0.0, round(score, 3), severity is not None, severity)


def robust_error_sigma(series: pd.Series) -> float:
    """Robust spread of the causal forecast errors over a whole series (sizes injected anomalies)."""
    series = series.astype(float)
    deseason = series - _weekday_effect(series).to_numpy()
    level = deseason.shift(1).rolling(LEVEL_DAYS, min_periods=LEVEL_DAYS // 2).median()
    errors = (deseason - level).dropna()
    return float(MAD_TO_SIGMA * np.median(np.abs(errors - np.median(errors))))
