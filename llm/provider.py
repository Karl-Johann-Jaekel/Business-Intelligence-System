"""Provider-agnostic LLM layer. MVP: Anthropic. Phase 2 adds OpenAI, Mistral, Ollama and routing
by data_class (plan section 3)."""

import os
from typing import Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

DEFAULT_ANTHROPIC_MODEL = "claude-opus-5-5"


class LLMError(RuntimeError):
    """The provider could not produce a usable answer (refusal, auth, outage)."""


class LLMProvider(Protocol):
    name: str
    model: str

    def generate(self, system: str, user: str, schema: type[T]) -> T:
        """Return an instance of `schema` (structured output)."""
        ...


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, model: str | None = None, effort: str | None = None, client=None):
        import anthropic  # imported lazily so the rest of the system works without the SDK configured

        self._anthropic = anthropic
        self.model = model or os.getenv("BIS_LLM_MODEL", DEFAULT_ANTHROPIC_MODEL)
        # A daily summary over pre-computed numbers is routine work; set explicitly because the
        # model's default effort differs between models.
        self.effort = effort or os.getenv("BIS_LLM_EFFORT", "medium")
        # Credentials resolve from the environment (ANTHROPIC_API_KEY or an `ant auth login` profile).
        self.client = client or anthropic.Anthropic(max_retries=3, timeout=120.0)

    def generate(self, system: str, user: str, schema: type[T]) -> T:
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

        if response.stop_reason == "refusal":
            category = response.stop_details.category if response.stop_details else None
            raise LLMError(f"Request declined (category: {category})")
        if response.stop_reason == "max_tokens" or response.parsed_output is None:
            raise LLMError(f"No structured output (stop_reason={response.stop_reason})")
        return response.parsed_output


def get_provider() -> LLMProvider | None:
    """Configured provider, or None when the AI analyst is switched off (BIS_LLM_PROVIDER=none)."""
    name = os.getenv("BIS_LLM_PROVIDER", "anthropic").lower()
    if name == "none":
        return None
    if name == "anthropic":
        return AnthropicProvider()
    raise ValueError(f"Unknown BIS_LLM_PROVIDER '{name}' (MVP supports: anthropic, none)")
