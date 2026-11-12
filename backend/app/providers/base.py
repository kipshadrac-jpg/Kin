"""Provider interfaces (Section 15). Tests never call a real provider."""

from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from pydantic import BaseModel


class Message(BaseModel):
    role: Literal["user", "assistant"]
    content: str


@dataclass
class LLMResult:
    text: str
    parsed: BaseModel | None = None
    model: str = ""
    stop_reason: str | None = None
    usage: dict[str, Any] = field(default_factory=dict)


class LLMProvider(Protocol):
    name: str
    is_local: bool

    async def complete(
        self,
        *,
        system: str,
        messages: list[Message],
        response_schema: type[BaseModel] | None = None,
        max_tokens: int = 1024,
        effort: str = "low",
    ) -> LLMResult: ...


class EmbeddingProvider(Protocol):
    dimensions: int
    model_name: str
    is_local: bool

    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class PrivacyModeError(RuntimeError):
    """Raised when local mode is active and code tries to call a cloud model."""


class ProviderError(RuntimeError):
    pass


# Per-request privacy mode. Cloud providers check this before any outbound call,
# so a bug elsewhere cannot leak a local-mode person's text (Section 14.9).
privacy_mode_var: ContextVar[str] = ContextVar("privacy_mode", default="cloud")


def assert_cloud_allowed(provider_name: str) -> None:
    if privacy_mode_var.get() == "local":
        raise PrivacyModeError(f"local privacy mode: outbound call to {provider_name} blocked")
