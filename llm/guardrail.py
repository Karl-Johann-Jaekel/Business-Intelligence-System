"""Number guardrail: every number in the generated text must occur in the input data.

Numbers are compared as values, not strings: "1.234,5" equals 1234.5, and a number written with
fewer decimals matches an input value that rounds to it (input 14,25 -> "14,3" passes). Dates
are checked separately and must appear verbatim in the input.
"""

import re
from decimal import ROUND_HALF_UP, Decimal

DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}\.\d{1,2}\.\d{4}\b|\b\d{1,2}/\d{4}\b")
# German notation: thousands separator "." (groups of three), decimal comma.
NUMBER = re.compile(
    r"(?<![\d,.])[-−+]?\d{1,3}(?:\.\d{3})+(?:,\d+)?(?![\d])|(?<![\d,.])[-−+]?\d+(?:,\d+)?(?![\d])"
)


def _parse(token: str) -> Decimal:
    clean = token.replace("−", "-").replace("+", "").replace(".", "").replace(",", ".")
    return Decimal(clean)


def extract(text: str) -> tuple[set[str], list[str]]:
    """(dates, number tokens) found in text."""
    dates = set(DATE.findall(text))
    without_dates = DATE.sub(" ", text)
    return dates, NUMBER.findall(without_dates)


def _decimals(token: str) -> int:
    return len(token.split(",", 1)[1]) if "," in token else 0


def _matches(token: str, allowed: list[Decimal]) -> bool:
    value = abs(_parse(token))
    quantum = Decimal(1).scaleb(-_decimals(token))
    return any(abs(a).quantize(quantum, rounding=ROUND_HALF_UP) == value for a in allowed)


def unsupported_numbers(output: str, source: str) -> list[str]:
    """Numbers or dates in `output` that do not occur in `source`. Empty list = passes."""
    source_dates, source_tokens = extract(source)
    allowed = [_parse(t) for t in source_tokens]
    out_dates, out_tokens = extract(output)
    problems = sorted(out_dates - source_dates)
    problems += [t for t in out_tokens if not _matches(t, allowed)]
    return problems
