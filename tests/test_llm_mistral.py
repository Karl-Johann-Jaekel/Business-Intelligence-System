"""Mistral provider: routing, structured output, retries, usage. No real API calls (MockTransport)."""

import json

import httpx
import pytest

from llm.briefing import Briefing
from llm.provider import LLMError, LLMRoutingError, MistralProvider, Usage, get_provider
from llm.usage import cost_eur

BRIEFING = {
    "summary": "Umsatz +119,4 %.",
    "findings": [{"text": "Umsatz +119,4 %.", "kpi": "gmv", "evidence_ref": "kpi:gmv"}],
    "actions": ["Pünktlichkeit prüfen."],
}


def _completion(content: str, finish_reason: str = "stop") -> dict:
    return {
        "choices": [{"message": {"role": "assistant", "content": content}, "finish_reason": finish_reason}],
        "usage": {"prompt_tokens": 1200, "completion_tokens": 300},
    }


def _provider(handler, **kwargs) -> tuple[MistralProvider, list[httpx.Request], list[float]]:
    requests: list[httpx.Request] = []
    sleeps: list[float] = []

    def record(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return handler(request, len(requests))

    client = httpx.Client(transport=httpx.MockTransport(record))
    provider = MistralProvider(api_key="test-key", client=client, sleep=sleeps.append, **kwargs)
    return provider, requests, sleeps


def test_structured_output_and_usage():
    provider, requests, _ = _provider(
        lambda req, n: httpx.Response(200, json=_completion(json.dumps(BRIEFING)))
    )
    result = provider.generate("system", "user", Briefing, data_class="public")
    assert result.findings[0].evidence_ref == "kpi:gmv"
    assert provider.calls == [Usage("mistral", "mistral-small-latest", 1200, 300)]

    body = json.loads(requests[0].content)
    assert requests[0].headers["Authorization"] == "Bearer test-key"
    assert body["response_format"]["type"] == "json_schema"
    schema = body["response_format"]["json_schema"]["schema"]
    # Nested models are inlined: the provider gets one schema without $ref/$defs.
    assert "$defs" not in json.dumps(schema) and "$ref" not in json.dumps(schema)
    assert schema["properties"]["findings"]["items"]["properties"]["evidence_ref"]["type"] == "string"


@pytest.mark.parametrize("data_class", ["internal", "confidential"])
def test_free_tier_is_public_only_and_checked_before_sending(data_class):
    provider, requests, _ = _provider(lambda req, n: pytest.fail("request left the system"))
    with pytest.raises(LLMRoutingError):
        provider.generate("s", "u", Briefing, data_class=data_class)
    assert requests == []


def test_data_classes_can_be_widened_for_a_paid_workspace(monkeypatch):
    monkeypatch.setenv("BIS_MISTRAL_DATA_CLASSES", "public,internal")
    provider, _, _ = _provider(lambda req, n: httpx.Response(200, json=_completion(json.dumps(BRIEFING))))
    provider.generate("s", "u", Briefing, data_class="internal")
    with pytest.raises(LLMRoutingError):
        provider.generate("s", "u", Briefing, data_class="confidential")


def test_rate_limit_is_retried_with_retry_after():
    def handler(req, n):
        if n < 3:
            return httpx.Response(429, headers={"Retry-After": "1.5"})
        return httpx.Response(200, json=_completion(json.dumps(BRIEFING)))

    provider, requests, sleeps = _provider(handler)
    provider.generate("s", "u", Briefing, data_class="public")
    assert len(requests) == 3 and sleeps == [1.5, 1.5]


def test_persistent_server_errors_become_llm_error():
    provider, requests, sleeps = _provider(lambda req, n: httpx.Response(503))
    with pytest.raises(LLMError, match="503"):
        provider.generate("s", "u", Briefing, data_class="public")
    assert len(requests) == MistralProvider.MAX_ATTEMPTS and sleeps == [2, 4, 8]


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (httpx.Response(401), "credentials"),
        (httpx.Response(400, json={"message": "bad"}), "rejected"),
        (httpx.Response(200, json=_completion("not json")), "schema"),
        (httpx.Response(200, json=_completion(json.dumps({"summary": "x"}))), "schema"),
        (httpx.Response(200, json=_completion(json.dumps(BRIEFING), "length")), "length"),
        (httpx.Response(200, json={"choices": []}), "Unexpected"),
    ],
    ids=["auth", "bad-request", "no-json", "missing-fields", "truncated", "empty"],
)
def test_failures_become_llm_error(response, message):
    provider, _, _ = _provider(lambda req, n: response)
    with pytest.raises(LLMError, match=message):
        provider.generate("s", "u", Briefing, data_class="public")


def test_missing_key_skips_without_request(monkeypatch):
    monkeypatch.delenv("BIS_MISTRAL_API_KEY", raising=False)
    provider = MistralProvider(client=httpx.Client(transport=httpx.MockTransport(lambda r: pytest.fail())))
    with pytest.raises(LLMError, match="BIS_MISTRAL_API_KEY"):
        provider.generate("s", "u", Briefing, data_class="public")


def test_get_provider_selects_mistral(monkeypatch):
    monkeypatch.setenv("BIS_LLM_PROVIDER", "mistral")
    monkeypatch.setenv("BIS_MISTRAL_MODEL", "mistral-medium-latest")
    assert get_provider().model == "mistral-medium-latest"


def test_cost_uses_configured_prices(monkeypatch):
    usage = Usage("mistral", "m", 2_000_000, 500_000)
    assert cost_eur(usage) == 0  # free tier
    monkeypatch.setenv("BIS_LLM_PRICE_MISTRAL_IN", "0.1")
    monkeypatch.setenv("BIS_LLM_PRICE_MISTRAL_OUT", "0.3")
    assert cost_eur(usage) == pytest.approx(0.35)
