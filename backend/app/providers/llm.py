"""LLM providers: Anthropic (cloud), Ollama (local), Fake (tests).

Model IDs come from env vars (LLM_MODEL, LOCAL_LLM_MODEL), never from code paths.
"""

import copy
import json
from collections.abc import Awaitable, Callable
from typing import Any

import anthropic
import httpx
from pydantic import BaseModel

from app.config import Settings
from app.providers.base import LLMProvider, LLMResult, Message, ProviderError, assert_cloud_allowed

_UNSUPPORTED_KEYS = {
    "title",
    "default",
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "minLength",
    "maxLength",
    "minItems",
    "maxItems",
    "pattern",
    "examples",
}


def strict_json_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Pydantic schema -> the strict subset structured outputs accept.

    Inlines $refs, closes every object (additionalProperties: false), marks every
    property required and drops validation keywords. Pydantic still validates the
    full model (with its constraints) after the response arrives.
    """
    raw = model.model_json_schema()
    defs = raw.pop("$defs", {})

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                name = node["$ref"].split("/")[-1]
                return walk(copy.deepcopy(defs[name]))
            out = {k: walk(v) for k, v in node.items() if k not in _UNSUPPORTED_KEYS}
            if out.get("type") == "object" or "properties" in out:
                out["additionalProperties"] = False
                out["required"] = list(out.get("properties", {}).keys())
            return out
        if isinstance(node, list):
            return [walk(n) for n in node]
        return node

    return walk(raw)


def _text_of(content: list[Any]) -> str:
    return "".join(getattr(b, "text", "") for b in content if getattr(b, "type", None) == "text").strip()


class AnthropicLLM:
    name = "anthropic"
    is_local = False

    def __init__(self, api_key: str | None, model: str, refusal_fallback: str = "default"):
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set")
        self._client = anthropic.AsyncAnthropic(api_key=api_key, max_retries=2, timeout=90)
        self._model = model
        self._fallback = refusal_fallback == "default"

    async def complete(
        self,
        *,
        system: str,
        messages: list[Message],
        response_schema: type[BaseModel] | None = None,
        max_tokens: int = 1024,
        effort: str = "low",
    ) -> LLMResult:
        assert_cloud_allowed(self.name)
        output_config: dict[str, Any] = {"effort": effort}
        if response_schema is not None:
            output_config["format"] = {"type": "json_schema", "schema": strict_json_schema(response_schema)}
        kwargs: dict[str, Any] = {
            "model": self._model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": [m.model_dump() for m in messages],
            "output_config": output_config,
        }
        try:
            if self._fallback:
                try:
                    # Server-side refusal fallback: if the model declines on a
                    # safety-classifier false positive, the API retries on another model.
                    resp: Any = await self._client.beta.messages.create(
                        betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs
                    )
                except anthropic.BadRequestError:
                    self._fallback = False  # not available for this account/model; stop trying
                    resp = await self._client.messages.create(**kwargs)
            else:
                resp = await self._client.messages.create(**kwargs)
        except anthropic.RateLimitError as exc:
            raise ProviderError("model rate limited") from exc
        except anthropic.APIStatusError as exc:
            raise ProviderError(f"model call failed with status {exc.status_code}") from exc
        except anthropic.APIConnectionError as exc:
            raise ProviderError("model unreachable") from exc

        if resp.stop_reason == "refusal":
            raise ProviderError("model declined this request")
        text = _text_of(resp.content)
        parsed = response_schema.model_validate_json(text) if response_schema is not None else None
        usage = {"input_tokens": resp.usage.input_tokens, "output_tokens": resp.usage.output_tokens}
        return LLMResult(text=text, parsed=parsed, model=resp.model, stop_reason=resp.stop_reason, usage=usage)


class OllamaLLM:
    """Local model through Ollama. Nothing leaves the machine."""

    name = "ollama"
    is_local = True

    def __init__(self, url: str, model: str):
        self._url = url.rstrip("/")
        self._model = model

    async def complete(
        self,
        *,
        system: str,
        messages: list[Message],
        response_schema: type[BaseModel] | None = None,
        max_tokens: int = 1024,
        effort: str = "low",
    ) -> LLMResult:
        body: dict[str, Any] = {
            "model": self._model,
            "stream": False,
            "messages": [{"role": "system", "content": system}] + [m.model_dump() for m in messages],
            "options": {"num_predict": max_tokens},
        }
        if response_schema is not None:
            body["format"] = strict_json_schema(response_schema)
        try:
            async with httpx.AsyncClient(timeout=180) as client:
                r = await client.post(f"{self._url}/api/chat", json=body)
        except httpx.HTTPError as exc:
            raise ProviderError("local model unreachable") from exc
        if r.status_code != 200:
            raise ProviderError(f"local model failed with status {r.status_code}")
        text = r.json().get("message", {}).get("content", "").strip()
        parsed = response_schema.model_validate_json(text) if response_schema is not None else None
        return LLMResult(text=text, parsed=parsed, model=self._model)


Responder = Callable[[str, list[Message], type[BaseModel] | None], Awaitable[str | BaseModel] | str | BaseModel]


class FakeLLM:
    """Deterministic test double. A responder decides the output per call;
    every call is recorded so tests can assert on prompts."""

    name = "fake"
    is_local = True

    def __init__(self, responder: Responder | None = None):
        self.responder = responder
        self.calls: list[dict[str, Any]] = []

    async def complete(
        self,
        *,
        system: str,
        messages: list[Message],
        response_schema: type[BaseModel] | None = None,
        max_tokens: int = 1024,
        effort: str = "low",
    ) -> LLMResult:
        self.calls.append({"system": system, "messages": messages, "schema": response_schema})
        if self.responder is None:
            out: Any = "OK" if response_schema is None else "{}"
        else:
            out = self.responder(system, messages, response_schema)
            if hasattr(out, "__await__"):
                out = await out
        if isinstance(out, BaseModel):
            return LLMResult(text=out.model_dump_json(), parsed=out, model="fake")
        text = out if isinstance(out, str) else json.dumps(out)
        parsed = response_schema.model_validate_json(text) if response_schema is not None else None
        return LLMResult(text=text, parsed=parsed, model="fake")


def build_llm(s: Settings) -> LLMProvider:
    if s.llm_provider == "fake":
        return FakeLLM()
    if s.llm_provider == "ollama":
        return OllamaLLM(s.ollama_url, s.local_llm_model)
    return AnthropicLLM(s.anthropic_api_key, s.llm_model, s.llm_refusal_fallback)
