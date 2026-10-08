"""HTML + plain-text emails for insights. All dynamic values are escaped."""

from datetime import date, timedelta
from functools import lru_cache
from html import escape
from typing import Any
from urllib.parse import urlencode

from analytics.text import format_signed_pct, format_value
from registry import Kpi, load_registry

SEVERITY_LABEL = {"critical": "Kritisch", "warning": "Warnung", "info": "Info"}
SEVERITY_COLOR = {"critical": "#d03b3b", "warning": "#b07800", "info": "#52514e"}
DIMENSION_LABEL = {"region": "Region", "category": "Kategorie"}
BODY_STYLE = (
    "margin:0;background:#f9f9f7;font-family:system-ui,-apple-system,'Segoe UI',sans-serif;color:#0b0b0b"
)


@lru_cache
def _registry() -> dict[str, Kpi]:
    return {k.key: k for k in load_registry()}


def dashboard_link(payload: dict[str, Any], base_url: str) -> str:
    """Deep link into the dashboard: KPI, dimension and the 30 days (or 12 months) up to the event."""
    params: dict[str, str] = {}
    if payload.get("kpi"):
        params["kpi"] = payload["kpi"]
    dims = [ref for ref in payload.get("entity_refs", []) if ref["type"] != "kpi"]
    if dims:
        params["dim"] = dims[0]["type"]
    end = date.fromisoformat(payload["period"]["end"])
    days = 365 if payload["period"]["grain"] == "month" else 30
    params["from"] = (end - timedelta(days=days - 1)).isoformat()
    params["to"] = end.isoformat()
    return f"{base_url.rstrip('/')}/?{urlencode(params)}"


def _period(period: dict[str, str]) -> str:
    start, end = date.fromisoformat(period["start"]), date.fromisoformat(period["end"])
    if period["grain"] == "month":
        return start.strftime("%m/%Y")
    if start == end:
        return end.strftime("%d.%m.%Y")
    return f"{start:%d.%m.%Y} bis {end:%d.%m.%Y}"


def _scope(payload: dict[str, Any]) -> str:
    dims = [ref for ref in payload.get("entity_refs", []) if ref["type"] != "kpi"]
    if not dims:
        return "Gesamt"
    ref = dims[0]
    return f"{DIMENSION_LABEL.get(ref['type'], ref['type'])} {ref['id'].split(':', 1)[1]}"


def _anomaly(payload: dict[str, Any]) -> tuple[str, list[tuple[str, str]], str]:
    kpi = _registry().get(payload.get("kpi") or "")
    label = kpi.label if kpi else payload.get("kpi", "KPI")
    unit = kpi.unit if kpi else "count"
    severity = SEVERITY_LABEL.get(payload["severity"], payload["severity"])
    subject = f"[{severity}] {label} ({_scope(payload)}) – Auffälligkeit {_period(payload['period'])}"
    rows = [
        ("Kennzahl", label),
        ("Bereich", _scope(payload)),
        ("Zeitraum", _period(payload["period"])),
        ("Beobachtet", format_value(payload.get("observed"), unit)),
    ]
    if payload["evidence"]["method"] == "threshold":
        rows.append(("Grenze", "±" + format_value(payload["evidence"].get("threshold"), unit)))
    else:
        rows += [
            ("Erwartet", format_value(payload.get("expected"), unit)),
            ("Abweichung", format_signed_pct(payload.get("deviation_pct"))),
        ]
    score = payload["evidence"].get("score")
    score_text = "–" if score is None else format_signed_pct(score).removesuffix(" %")
    rows.append(("Methode", f"{payload['evidence']['method']} (Score {score_text})"))
    return subject, rows, payload["summary"]


def _briefing_body(payload: dict[str, Any]) -> tuple[str, str]:
    briefing = (payload.get("details") or {}).get("briefing", {})
    findings = briefing.get("findings", [])
    actions = briefing.get("actions", [])
    html = "".join(f"<li>{escape(f['text'])}</li>" for f in findings)
    html_actions = "".join(f"<li>{escape(a)}</li>" for a in actions)
    text = "\n".join(f"- {f['text']}" for f in findings)
    text_actions = "\n".join(f"- {a}" for a in actions)
    return (
        f"<h3 style='margin:16px 0 4px'>Befunde</h3><ul>{html}</ul>"
        f"<h3 style='margin:16px 0 4px'>Handlungsvorschläge</h3><ul>{html_actions}</ul>",
        f"Befunde:\n{text}\n\nHandlungsvorschläge:\n{text_actions}",
    )


def render_email(payload: dict[str, Any], dashboard_url: str) -> tuple[str, str, str]:
    """Returns (subject, html, text)."""
    link = dashboard_link(payload, dashboard_url)
    color = SEVERITY_COLOR.get(payload["severity"], "#52514e")
    if payload["type"] == "briefing":
        subject = f"Tagesbriefing {_period(payload['period'])}"
        rows: list[tuple[str, str]] = []
        lead = payload["summary"]
        extra_html, extra_text = _briefing_body(payload)
    else:
        subject, rows, lead = _anomaly(payload)
        extra_html, extra_text = "", ""

    table = "".join(
        f"<tr><td style='padding:4px 12px 4px 0;color:#52514e'>{escape(k)}</td>"
        f"<td style='padding:4px 0'><strong>{escape(v)}</strong></td></tr>"
        for k, v in rows
    )
    severity_label = SEVERITY_LABEL.get(payload["severity"], "")
    html = f"""<!doctype html>
<html lang="de"><body style="{BODY_STYLE}">
<div style="max-width:600px;margin:0 auto;padding:24px">
  <div style="background:#fcfcfb;border:1px solid #e1e0d9;border-radius:10px;padding:20px">
    <div style="font-size:12px;color:{color};font-weight:600">{escape(severity_label)}</div>
    <h2 style="font-size:18px;margin:4px 0 12px">{escape(subject)}</h2>
    <p style="margin:0 0 12px">{escape(lead)}</p>
    <table style="border-collapse:collapse;font-size:14px">{table}</table>
    {extra_html}
    <p style="margin:20px 0 0">
      <a href="{escape(link, quote=True)}" style="color:#2a78d6">Im Dashboard ansehen</a>
    </p>
  </div>
  <p style="font-size:12px;color:#898781">
    Business-Intelligence-System · Insight {escape(str(payload["insight_id"]))}
  </p>
</div></body></html>"""
    text = "\n".join(
        [subject, "", lead, ""]
        + [f"{k}: {v}" for k, v in rows]
        + ([extra_text] if extra_text else [])
        + ["", f"Dashboard: {link}"]
    )
    return subject, html, text
