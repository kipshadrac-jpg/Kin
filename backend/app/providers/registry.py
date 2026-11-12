"""Which providers serve a request. Tests swap these with set_providers()."""

from dataclasses import dataclass

from app.config import get_settings
from app.providers.base import EmbeddingProvider, LLMProvider, privacy_mode_var
from app.providers.embeddings import build_embeddings, local_embeddings
from app.providers.llm import build_llm


@dataclass
class Providers:
    llm: LLMProvider | None
    embeddings: EmbeddingProvider
    local_llm: LLMProvider | None
    local_embeddings: EmbeddingProvider


_providers: Providers | None = None


def _build() -> Providers:
    s = get_settings()
    llm: LLMProvider | None
    try:
        llm = build_llm(s)
    except RuntimeError:
        llm = None  # e.g. no API key yet; chat reports it, the rest of the app works
    emb = build_embeddings(s)
    local_llm = llm if (llm is not None and llm.is_local) else None
    return Providers(llm=llm, embeddings=emb, local_llm=local_llm, local_embeddings=local_embeddings(s))


def get_providers() -> Providers:
    global _providers
    if _providers is None:
        _providers = _build()
    return _providers


def set_providers(p: Providers | None) -> None:
    global _providers
    _providers = p


def embeddings_for(privacy_mode: str) -> EmbeddingProvider:
    p = get_providers()
    return p.local_embeddings if privacy_mode == "local" else p.embeddings


def llm_for(privacy_mode: str) -> LLMProvider | None:
    p = get_providers()
    return p.local_llm if privacy_mode == "local" else p.llm


def set_privacy_mode(mode: str) -> None:
    privacy_mode_var.set(mode)
