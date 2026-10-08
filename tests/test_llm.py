from datetime import date

import pytest

from llm import briefing as briefing_mod
from llm.briefing import Briefing, Finding, generate
from llm.context import render
from llm.guardrail import extract, unsupported_numbers
from llm.provider import LLMError

CONTEXT = {
    "date": "2018-01-08",
    "kpis": [
        {
            "id": "kpi:gmv",
            "label": "Umsatz (GMV)",
            "last_7_days": "214.918,64 R$",
            "previous_7_days": "97.961,77 R$",
            "change": "+119,4 %",
            "top_drivers": [{"id": "category:baby", "change": "+570,4 %"}],
        },
        {
            "id": "kpi:on_time_rate",
            "label": "Pünktlichkeitsquote",
            "last_7_days": "87,80 %",
            "change": "−3,2 %",
        },
    ],
    "monthly_kpis": [],
    "anomalies": [],
}


def _briefing(summary: str, ref: str = "kpi:gmv") -> Briefing:
    return Briefing(
        summary=summary,
        findings=[Finding(text="Umsatz +119,4 % gegenüber Vorwoche.", kpi="gmv", evidence_ref=ref)],
        actions=["Lieferpartner zur Pünktlichkeitsquote von 87,80 % befragen."],
    )


class ScriptedProvider:
    name, model = "fake", "fake-1"

    def __init__(self, drafts: list[Briefing]):
        self.drafts = list(drafts)
        self.prompts: list[str] = []

    def generate(self, system, user, schema):
        self.prompts.append(user)
        return self.drafts.pop(0)


@pytest.mark.parametrize(
    ("text", "problems"),
    [
        ("Umsatz 214.918,64 R$ (+119,4 %) am 2018-01-08.", []),
        ("Pünktlichkeit 87,8 %.", []),  # fewer decimals of an input value is fine
        ("Umsatz rund 215.000 R$.", ["215.000"]),
        ("Am 2018-01-09 stieg der Umsatz.", ["2018-01-09"]),
        ("Kategorie baby wuchs um 570 %.", []),  # 570,4 rounded to integer
        ("Plus 571 %.", ["571"]),
    ],
)
def test_guardrail(text, problems):
    assert unsupported_numbers(text, render(CONTEXT)) == problems


def test_extract_ignores_numbers_inside_dates():
    dates, numbers = extract("Am 08.01.2018 waren es 1.590 Bestellungen")
    assert dates == {"08.01.2018"} and numbers == ["1.590"]


def test_valid_draft_is_accepted_first_time():
    provider = ScriptedProvider([_briefing("Umsatz +119,4 % auf 214.918,64 R$.")])
    result = generate(provider, CONTEXT)
    assert result.briefing is not None and result.attempts == 1 and result.rejected == []


def test_draft_with_invented_number_is_regenerated_with_feedback():
    provider = ScriptedProvider(
        [_briefing("Umsatz verdoppelt auf 230.000 R$."), _briefing("Umsatz +119,4 % gegenüber Vorwoche.")]
    )
    result = generate(provider, CONTEXT)
    assert result.attempts == 2
    assert result.rejected == [["230.000"]]
    assert "230.000" in provider.prompts[1] and "verworfen" in provider.prompts[1]


def test_unknown_evidence_ref_is_rejected():
    provider = ScriptedProvider([_briefing("Umsatz +119,4 %.", ref="region:XX")] * 3)
    result = generate(provider, CONTEXT)
    assert result.briefing is None and result.attempts == 3
    assert result.rejected[0] == ["region:XX"]


def test_provider_error_skips_briefing(monkeypatch):
    class Failing:
        name, model = "fake", "fake-1"

        def generate(self, *args):
            raise LLMError("Anthropic credentials missing or invalid")

    monkeypatch.setattr(briefing_mod.ctx, "build", lambda conn, kpis, d: CONTEXT)
    result = briefing_mod.run(conn=None, provider=Failing(), sim_date=date(2018, 1, 8))
    assert result == {"status": "skipped", "reason": "Anthropic credentials missing or invalid"}
