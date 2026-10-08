"""German number formatting by registry unit, for insight summaries and emails."""


def _de(value: float, decimals: int) -> str:
    text = f"{value:,.{decimals}f}"
    return text.replace(",", "_").replace(".", ",").replace("_", ".")


def format_value(value: float | None, unit: str) -> str:
    if value is None:
        return "–"
    if unit == "BRL":
        return f"{_de(value, 2)} R$"
    if unit == "ratio":
        return f"{_de(value * 100, 2)} %"
    if unit == "multiple":
        return f"{_de(value, 2)}×"
    if unit == "days":
        return f"{_de(value, 1)} Tage"
    if unit == "score":
        return _de(value, 2)
    return _de(value, 0) if float(value).is_integer() else _de(value, 2)


def format_signed_pct(value: float | None) -> str:
    if value is None:
        return "–"
    sign = "+" if value > 0 else "−" if value < 0 else "±"
    return f"{sign}{_de(abs(value), 1)} %"
