"""Provider-agnostic LLM layer with routing by data class (plan section 8).

Every call states the data class of its prompt (the highest class of its parts). A provider
refuses classes it is not cleared for: external providers get `public` only, `internal` needs an
EU provider or a local model, `confidential` only a local model (none on the VPS, so blocked there)."""

import os
from dataclasses import dataclass
from typing import Literal, Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

DEFAULT_ANTHROPIC_MODEL = "claude-opus-5-5"
DEFAULT_MISTRAL_MODEL = "mistral-small-latest"


@dataclass(frozen=True)
class Usage:
    """Tokens of one provider call; recorded in ops.llm_usage for the admin cost view."""

    provider: str
    model: str
    tokens_in: int
    tokens_out: int


DataClass = Literal["public", "internal", "confidential"]
DATA_CLASSES: tuple[DataClass, ...] = ("public", "internal", "confidential")


class LLMError(RuntimeError):
    """The provider could not produce a usable answer (refusal, auth, outage)."""


class LLMRoutingError(PermissionError):
    """A prompt was about to reach a provider not cleared for its data class. Deliberately not an
    LLMError: callers must not treat it as a soft failure."""


def highest_data_class(classes) -> DataClass:
    classes = list(classes)
    if not classes:
        return "public"
    return max(classes, key=DATA_CLASSES.index)


class LLMProvider(Protocol):
    name: str
    model: str
    allowed_data_classes: frozenset[str]

    def generate(self, system: str, user: str, schema: type[T], data_class: DataClass) -> T:
        """Return an instance of `schema` (structured output)."""
        ...


def check_route(provider: LLMProvider, data_class: str) -> None:
    if data_class not in DATA_CLASSES:
        raise LLMRoutingError(f"Unknown data class {data_class!r}")
    if data_class not in provider.allowed_data_classes:
        raise LLMRoutingError(
            f"Provider {provider.name!r} is not cleared for {data_class!r} data "
            f"(allowed: {', '.join(sorted(provider.allowed_data_classes))})"
        )


class AnthropicProvider:
    name = "anthropic"
    # External, non-EU provider: public data only (plan section 8).
    allowed_data_classes = frozenset({"public"})

    def __init__(self, model: str | None = None, effort: str | None = None, client=None):
        import anthropic  # imported lazily so the rest of the system works without the SDK configured

        self._anthropic = anthropic
        self.model = model or os.getenv("BIS_LLM_MODEL", DEFAULT_ANTHROPIC_MODEL)
        # A daily summary over pre-computed numbers is routine work; set explicitly because the
        # model's default effort differs between models.
        self.effort = effort or os.getenv("BIS_LLM_EFFORT", "medium")
        # Credentials resolve from the environment (ANTHROPIC_API_KEY or an `ant auth login` profile).
        self.client = client or anthropic.Anthropic(max_retries=3, timeout=120.0)
        self.calls: list[Usage] = []

    def generate(self, system: str, user: str, schema: type[T], data_class: DataClass) -> T:
        check_route(self, data_class)  # before anything leaves the system
        a = self._anthropic
        try:
            response = self.client.beta.messages.parse(
                model=self.model,
                max_tokens=16000,
                system=system,
                messages=[{"role": "user", "content": user}],
                output_config={"effort": self.effort},
                output_format=schema,
                # On a safety-classifier decline the API re-runs the request on a fallback model.
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
        except a.AuthenticationError as exc:
            raise LLMError("Anthropic credentials missing or invalid") from exc
        except TypeError as exc:
            # Without any credential source the SDK raises TypeError before sending the request.
            if "Could not resolve authentication" not in str(exc):
                raise
            raise LLMError("No Anthropic credentials configured") from exc
        except a.BadRequestError as exc:
            raise LLMError(f"Request rejected: {exc.message}") from exc
        except a.RateLimitError as exc:
            raise LLMError("Rate limited after SDK retries") from exc
        except a.APIStatusError as exc:
            raise LLMError(f"API error {exc.status_code}") from exc
        except a.APIConnectionError as exc:
            raise LLMError("Anthropic API not reachable") from exc

        usage = getattr(response, "usage", None)
        if usage is not None:
            self.calls.append(Usage(self.name, self.model, usage.input_tokens, usage.output_tokens))
        if response.stop_reason == "refusal":
            category = response.stop_details.category if response.stop_details else None
            raise LLMError(f"Request declined (category: {category})")
        if response.stop_reason == "max_tokens" or response.parsed_output is None:
            raise LLMError(f"No structured output (stop_reason={response.stop_reason})")
        return response.parsed_output


def _inline_refs(schema: dict) -> dict:
    """Pydantic puts nested models under $defs; resolve them so the provider sees one flat schema."""
    defs = schema.get("$defs", {})

    def resolve(node):
        if isinstance(node, dict):
            if "$ref" in node:
                return resolve(defs[node["$ref"].rsplit("/", 1)[-1]])
            return {k: resolve(v) for k, v in node.items() if k != "$defs"}
        if isinstance(node, list):
            return [resolve(v) for v in node]
        return node

    return resolve(schema)


class MistralProvider:
    """Mistral chat completions with JSON-schema output (EU provider, plan section 8).

    The free tier may use inputs for training, so it is cleared for `public` only unless
    BIS_MISTRAL_DATA_CLASSES says otherwise (e.g. a paid workspace with training opted out)."""

    name = "mistral"
    URL = "https://api.mistral.ai/v1/chat/completions"
    MAX_ATTEMPTS = 4

    def __init__(self, model: str | None = None, api_key: str | None = None, client=None, sleep=None):
        import time

        import httpx

        self._httpx = httpx
        self.model = model or os.getenv("BIS_MISTRAL_MODEL", DEFAULT_MISTRAL_MODEL)
        self._api_key = api_key if api_key is not None else os.getenv("BIS_MISTRAL_API_KEY", "")
        raw = os.getenv("BIS_MISTRAL_DATA_CLASSES", "public")
        self.allowed_data_classes = frozenset(c.strip() for c in raw.split(",") if c.strip())
        self.client = client or httpx.Client(timeout=120.0)
        self._sleep = sleep or time.sleep
        self.calls: list[Usage] = []

    def generate(self, system: str, user: str, schema: type[T], data_class: DataClass) -> T:
        check_route(self, data_class)  # before anything leaves the system
        if not self._api_key:
            raise LLMError("No Mistral API key configured (BIS_MISTRAL_API_KEY)")
        body = {
            "model": self.model,
            "temperature": 0.2,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": schema.__name__, "schema": _inline_refs(schema.model_json_schema())},
            },
        }
        response = self._post(body)
        data = response.json()
        usage = data.get("usage") or {}
        self.calls.append(
            Usage(self.name, self.model, usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0))
        )
        try:
            choice = data["choices"][0]
            content = choice["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError("Unexpected Mistral response") from exc
        if choice.get("finish_reason") == "length":
            raise LLMError("No structured output (finish_reason=length)")
        try:
            return schema.model_validate_json(content)
        except ValueError as exc:
            raise LLMError("Mistral output does not match the schema") from exc

    def _post(self, body: dict):
        """POST with retries on rate limits and server errors (Retry-After or exponential backoff)."""
        httpx = self._httpx
        headers = {"Authorization": f"Bearer {self._api_key}", "Accept": "application/json"}
        for attempt in range(1, self.MAX_ATTEMPTS + 1):
            try:
                response = self.client.post(self.URL, json=body, headers=headers)
            except httpx.HTTPError as exc:
                if attempt == self.MAX_ATTEMPTS:
                    raise LLMError("Mistral API not reachable") from exc
                self._sleep(2**attempt)
                continue
            if response.status_code in (401, 403):
                raise LLMError("Mistral credentials missing or invalid")
            if response.status_code == 429 or response.status_code >= 500:
                if attempt == self.MAX_ATTEMPTS:
                    raise LLMError(f"Mistral API error {response.status_code} after {attempt} attempts")
                retry_after = response.headers.get("Retry-After", "")
                self._sleep(float(retry_after) if retry_after.replace(".", "", 1).isdigit() else 2**attempt)
                continue
            if response.status_code >= 400:
                raise LLMError(f"Request rejected by Mistral ({response.status_code})")
            return response
        raise LLMError("Mistral API not reachable")  # pragma: no cover - loop always returns or raises


def get_provider() -> LLMProvider | None:
    """Configured provider, or None when the AI analyst is switched off (BIS_LLM_PROVIDER=none)."""
    name = os.getenv("BIS_LLM_PROVIDER", "anthropic").lower()
    if name == "none":
        return None
    if name == "anthropic":
        return AnthropicProvider()
    if name == "mistral":
        return MistralProvider()
    raise ValueError(f"Unknown BIS_LLM_PROVIDER '{name}' (supported: anthropic, mistral, none)")
