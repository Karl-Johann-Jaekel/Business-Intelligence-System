"""Evaluate and calibrate stl_mad with injected anomalies on real KPI history.

For every day in the evaluation window the detector sees only the history up to that day (as
in the daily pipeline). Spikes of `magnitude` x robust forecast-error sigma are injected on
random days; hits = injected days flagged, false alarms = other days flagged. Scores are
computed once per KPI and evaluated for several thresholds to calibrate the registry.

Usage: python -m analytics.evaluate [--start 2017-04-01] [--end 2017-12-31] [--magnitude 6]
Writes docs/anomaly-evaluation.md.
"""

import argparse
from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
import pandas as pd

from analytics import anomaly
from analytics.detect import Target, daily_series
from ingestion.config import REPO_ROOT
from ingestion.db import connect
from registry import Kpi, load_registry

TOTAL = Target("total", "all", "")
REPORT = REPO_ROOT / "docs" / "anomaly-evaluation.md"
INJECTION_SPACING_DAYS = 10  # one injection roughly every 10 days, never adjacent
CANDIDATE_THRESHOLDS = (3.5, 4.0, 4.5, 5.0, 5.5, 6.0)
MAX_FALSE_ALARMS_PER_MONTH = 2.0


@dataclass
class Result:
    kpi: str
    threshold: float
    days: int
    injected: int
    hits: int
    false_alarms_clean: int
    false_alarms_injected: int

    @property
    def hit_rate(self) -> float:
        return self.hits / self.injected if self.injected else float("nan")

    def fa_per_month(self, which: str) -> float:
        count = self.false_alarms_clean if which == "clean" else self.false_alarms_injected
        return count / self.days * 30


def injection_days(days: list[date], rng: np.random.Generator) -> list[date]:
    picks = []
    for chunk_start in range(0, len(days), INJECTION_SPACING_DAYS):
        chunk = days[chunk_start + 2 : chunk_start + INJECTION_SPACING_DAYS - 2]
        if chunk:
            picks.append(chunk[rng.integers(len(chunk))])
    return picks


def online_scores(series: pd.Series, eval_days: list[date], kpi: Kpi) -> dict[date, float]:
    """Score every day with only its own history visible, as the daily pipeline does."""
    scores = {}
    for day in eval_days:
        det = anomaly.stl_mad(series.loc[:day], kpi.alert.threshold, kpi.alert.min_history_days)
        if det is not None:
            scores[day] = abs(det.score)
    return scores


def flags_at(scores: dict[date, float], threshold: float) -> set[date]:
    return {day for day, score in scores.items() if score >= threshold}


def evaluate_kpi(
    series: pd.Series, kpi: Kpi, start: date, end: date, magnitude: float, seed: int
) -> dict[float, Result]:
    """Results per candidate threshold (scores are computed once and thresholded afterwards)."""
    rng = np.random.default_rng(seed)
    eval_days = [d for d in series.index if start <= d <= end and not np.isnan(series[d])]
    clean_scores = online_scores(series, eval_days, kpi)

    sigma = anomaly.robust_error_sigma(series.loc[:end].dropna())
    injected = injection_days(eval_days, rng)
    dirty = series.copy()
    for day in injected:
        dirty[day] += rng.choice([-1, 1]) * magnitude * sigma
    dirty_scores = online_scores(dirty, eval_days, kpi)

    results = {}
    for threshold in sorted({*CANDIDATE_THRESHOLDS, kpi.alert.threshold}):
        dirty_flags = flags_at(dirty_scores, threshold)
        results[threshold] = Result(
            kpi=kpi.key,
            threshold=threshold,
            days=len(eval_days),
            injected=len(injected),
            hits=len(set(injected) & dirty_flags),
            false_alarms_clean=len(flags_at(clean_scores, threshold)),
            false_alarms_injected=len(dirty_flags - set(injected)),
        )
    return results


def calibrate(results: dict[float, Result]) -> Result:
    """Smallest threshold that keeps false alarms on clean data within the target."""
    for threshold in sorted(results):
        if results[threshold].fa_per_month("clean") <= MAX_FALSE_ALARMS_PER_MONTH:
            return results[threshold]
    return results[max(results)]


def _table(title: str, results: list[Result]) -> list[str]:
    lines = [
        f"## {title}",
        "",
        "| KPI | Schwelle | Tage | Injiziert | Treffer | Trefferquote "
        "| Fehlalarme/Monat (sauber) | Fehlalarme/Monat (mit Injektion) |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in results:
        lines.append(
            f"| `{r.kpi}` | {r.threshold:g} | {r.days} | {r.injected} | {r.hits} | {r.hit_rate:.0%} "
            f"| {r.fa_per_month('clean'):.1f} | {r.fa_per_month('injected'):.1f} |"
        )
    injected = sum(r.injected for r in results)
    hits = sum(r.hits for r in results)
    fa_clean = sum(r.false_alarms_clean for r in results) / sum(r.days for r in results) * 30
    return lines + [
        "",
        f"**Gesamt:** Trefferquote {hits / injected:.0%} ({hits}/{injected}), "
        f"Fehlalarme Ø {fa_clean:.1f} pro KPI und simuliertem Monat auf den sauberen Daten.",
        "",
    ]


def render(
    current: list[Result], calibrated: list[Result], start: date, end: date, magnitude: float, seed: int
) -> str:
    lines = [
        "# Anomalieerkennung: Auswertung mit injizierten Anomalien",
        "",
        f"Erzeugt mit `python -m analytics.evaluate --start {start} --end {end} --magnitude {magnitude:g} "
        f"--seed {seed}`.",
        "",
        "Methode: `stl_mad` (Wochentagseffekt aus STL, Niveau = rollierender Median der Vortage,",
        "robuster Z-Score der Prognoseabweichung). Bewertet wird nur die Gesamtreihe.",
        f"Injektion: etwa alle {INJECTION_SPACING_DAYS} Tage ein Einzeltag-Ausschlag von "
        f"±{magnitude:g} × robuster",
        "Standardabweichung des Ein-Schritt-Prognosefehlers der jeweiligen KPI.",
        "",
        "Fehlalarme sauber = Alarme auf den echten Daten ohne Injektion. Darin stecken auch echte",
        "Ausreißer (z. B. Black Friday 2017), sie sind also eine obere Schranke für Fehlalarme.",
        "",
    ]
    for title, results in (("Registry-Schwellen", current), ("Kalibriert", calibrated)):
        lines += _table(title, results)
    lines += [
        "Kalibrierung: je KPI die kleinste Schwelle aus "
        f"{', '.join(f'{t:g}' for t in CANDIDATE_THRESHOLDS)} mit höchstens "
        f"{MAX_FALSE_ALARMS_PER_MONTH:g} Fehlalarmen pro Monat auf den sauberen Daten.",
        "Zielwerte aus dem Plan: Trefferquote ≥ 80 %, höchstens 2 Fehlalarme pro simuliertem Monat.",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--start", type=date.fromisoformat, default=date(2017, 4, 1))
    parser.add_argument("--end", type=date.fromisoformat, default=date(2017, 12, 31))
    parser.add_argument("--magnitude", type=float, default=6.0)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    history_start = args.start - timedelta(days=anomaly.WINDOW_DAYS)
    kpis = [k for k in load_registry() if k.alert and k.alert.method == "stl_mad"]
    current, calibrated = [], []
    with connect() as conn:
        for i, kpi in enumerate(kpis):
            series = daily_series(conn, kpi.key, TOTAL, history_start, args.end)
            results = evaluate_kpi(series, kpi, args.start, args.end, args.magnitude, args.seed + i)
            now, best = results[kpi.alert.threshold], calibrate(results)
            current.append(now)
            calibrated.append(best)
            print(
                f"{kpi.key:<24} registry {now.threshold:g}: hit {now.hit_rate:4.0%} "
                f"FA {now.fa_per_month('clean'):4.1f} | calibrated {best.threshold:g}: "
                f"hit {best.hit_rate:4.0%} FA {best.fa_per_month('clean'):4.1f}",
                flush=True,
            )
    REPORT.write_text(
        render(current, calibrated, args.start, args.end, args.magnitude, args.seed), encoding="utf-8"
    )
    print(f"Report: {REPORT.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
