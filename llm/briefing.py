"""Daily briefing by the AI analyst, stored as an insight.v1 event of type `briefing`."""

import logging
from dataclasses import dataclass
from datetime import date

import psycopg
from pydantic import BaseModel, Field

from events.insight import Evidence, Insight, Period, save
from llm import context as ctx
from llm.guardrail import unsupported_numbers
from llm.provider import LLMError, LLMProvider
from registry import load_registry

log = logging.getLogger(__name__)
MAX_ATTEMPTS = 3

SYSTEM_PROMPT = """Du bist Business-Analyst eines E-Commerce-Unternehmens und schreibst das tägliche
Kennzahlen-Briefing für die Geschäftsführung, auf Deutsch.

Du bekommst ausschließlich bereits berechnete Werte als JSON. Für das Briefing gilt:
- Verwende nur Zahlen und Daten, die im JSON stehen, und übernimm sie exakt in der dort
  angegebenen Schreibweise. Rechne nichts selbst nach, schätze nichts, runde nicht um.
- Jeder Befund nennt in `evidence_ref` die `id` des Eintrags, auf den er sich stützt
  (z. B. "kpi:gmv", "region:SP" oder "insight:<uuid>").
- `summary`: zwei bis drei Sätze mit dem Wichtigsten des Tages.
- `findings`: drei bis fünf Befunde, die auffälligsten zuerst. Erkannte Anomalien haben Vorrang.
- `actions`: ein bis drei konkrete, überprüfbare Handlungsvorschläge.
- Kennzahlen mit data_origin "partly_synthetic" beruhen teils auf synthetischen Daten; erwähne
  das, wenn du sie verwendest.
- Wenn die Daten keine klare Aussage tragen, schreibe das, statt eine Ursache zu erfinden."""


class Finding(BaseModel):
    text: str = Field(description="Ein Satz zum Befund, mit Zahlen aus dem Input")
    kpi: str = Field(description="Registry-Schlüssel der Kennzahl, z. B. gmv")
    evidence_ref: str = Field(description="id des belegenden Eintrags aus dem Input")


class Briefing(BaseModel):
    summary: str
    findings: list[Finding]
    actions: list[str]


@dataclass
class BriefingResult:
    briefing: Briefing | None
    attempts: int
    rejected: list[list[str]]  # unsupported numbers per rejected attempt


def _all_text(briefing: Briefing) -> str:
    return "\n".join([briefing.summary, *(f.text for f in briefing.findings), *briefing.actions])


def _evidence_problems(briefing: Briefing, source: str) -> list[str]:
    return [f.evidence_ref for f in briefing.findings if f'"{f.evidence_ref}"' not in source]


def generate(provider: LLMProvider, context: dict) -> BriefingResult:
    """Generate and validate. A draft with numbers or evidence refs not found in the input is
    discarded and regenerated (with feedback), at most MAX_ATTEMPTS times."""
    source = ctx.render(context)
    prompt = f"Daten für das Briefing:\n\n{source}"
    rejected: list[list[str]] = []
    for attempt in range(1, MAX_ATTEMPTS + 1):
        draft = provider.generate(SYSTEM_PROMPT, prompt, Briefing, data_class=context["data_class"])
        problems = unsupported_numbers(_all_text(draft), source) + _evidence_problems(draft, source)
        if not problems:
            return BriefingResult(draft, attempt, rejected)
        rejected.append(problems)
        log.warning("Briefing attempt %s rejected by guardrail: %s", attempt, problems)
        prompt = (
            f"Daten für das Briefing:\n\n{source}\n\n"
            f"Ein vorheriger Entwurf wurde verworfen, weil diese Angaben nicht im Input stehen: "
            f"{', '.join(problems)}. Verwende ausschließlich Zahlen, Daten und ids aus dem Input."
        )
    return BriefingResult(None, MAX_ATTEMPTS, rejected)


def run(conn: psycopg.Connection, provider: LLMProvider, sim_date: date) -> dict:
    """Create and store the briefing for sim_date. Returns metadata for the pipeline."""
    kpis = load_registry()
    context = ctx.build(conn, kpis, sim_date, provider.allowed_data_classes)
    try:
        result = generate(provider, context)
    except LLMError as exc:
        log.warning("No briefing for %s: %s", sim_date, exc)
        return {"status": "skipped", "reason": str(exc)}
    if result.briefing is None:
        return {"status": "rejected", "attempts": result.attempts, "rejected": result.rejected}

    has_critical = any(a["severity"] == "critical" for a in context["anomalies"])
    insight = Insight(
        type="briefing",
        period=Period(start=sim_date, end=sim_date, grain="day"),
        severity="warning" if has_critical else "info",
        evidence=Evidence(method="llm_briefing", provider=provider.name, model=provider.model),
        summary=result.briefing.summary,
        data_class=context["data_class"],
        details={
            "briefing": result.briefing.model_dump(),
            "attempts": result.attempts,
            "rejected_drafts": result.rejected,
            "context": context,
        },
    )
    stored = save(conn, insight)
    conn.commit()
    return {"status": "stored" if stored else "exists", "attempts": result.attempts}
