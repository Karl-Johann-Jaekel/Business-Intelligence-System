"""Period arithmetic for day and month grains."""

from datetime import date, timedelta

from api.repository import Grain

DEFAULT_DAYS = 90
DEFAULT_MONTHS = 12


def month_start(d: date) -> date:
    return d.replace(day=1)


def add_months(d: date, months: int) -> date:
    index = d.year * 12 + d.month - 1 + months
    return date(index // 12, index % 12 + 1, 1)


def default_window(grain: Grain, sim_date: date) -> tuple[date, date]:
    if grain == "day":
        return sim_date - timedelta(days=DEFAULT_DAYS - 1), sim_date
    end = month_start(sim_date)
    return add_months(end, -(DEFAULT_MONTHS - 1)), end


def normalise(grain: Grain, start: date, end: date) -> tuple[date, date]:
    if grain == "month":
        return month_start(start), month_start(end)
    return start, end


def previous_window(grain: Grain, start: date, end: date) -> tuple[date, date]:
    """The equally long window directly before [start, end]."""
    if grain == "day":
        length = (end - start).days + 1
        prev_end = start - timedelta(days=1)
        return prev_end - timedelta(days=length - 1), prev_end
    months = (end.year - start.year) * 12 + end.month - start.month + 1
    return add_months(start, -months), add_months(start, -1)
