"""Embedding providers.

The column is vector(1536) for the whole deployment. Every provider here
reports `dimensions`, and app startup refuses to run if they differ (a model
with another size needs a migration plus a re-embed job). Each stored row
records `embedding_model` so a re-embed knows what it is replacing.
"""

import hashlib
import math
import re

import httpx

from app.config import Settings
from app.providers.base import EmbeddingProvider, ProviderError, assert_cloud_allowed

_WORD = re.compile(r"[\w']+", re.UNICODE)


def _hash_embed(text: str, dims: int) -> list[float]:
    """Feature hashing over words and word pairs, L2-normalised.

    Fully local and deterministic: no model download, no outbound call. It is
    lexical (shared words), not truly semantic, which is why OpenAI embeddings
    are preferred when a key is configured.
    """
    vec = [0.0] * dims
    words = [w.lower() for w in _WORD.findall(text)]
    feats = words + [f"{a} {b}" for a, b in zip(words, words[1:], strict=False)]
    for f in feats:
        h = hashlib.blake2b(f.encode(), digest_size=8).digest()
        idx = int.from_bytes(h[:4], "little") % dims
        sign = 1.0 if h[4] & 1 else -1.0
        vec[idx] += sign * (1.0 if " " not in f else 0.5)
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


class HashingEmbeddings:
    is_local = True

    def __init__(self, dims: int = 1536):
        self.dimensions = dims
        self.model_name = f"kin-hashing-v1-{dims}"

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [_hash_embed(t, self.dimensions) for t in texts]


class FakeEmbeddings(HashingEmbeddings):
    """Deterministic embeddings for tests (same algorithm, separate name)."""

    def __init__(self, dims: int = 1536):
        super().__init__(dims)
        self.model_name = "fake-embeddings"


class OpenAIEmbeddings:
    is_local = False

    def __init__(self, api_key: str, model: str, dims: int):
        self._key = api_key
        self.model_name = model
        self.dimensions = dims

    async def embed(self, texts: list[str]) -> list[list[float]]:
        assert_cloud_allowed("openai-embeddings")
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(
                "https://api.openai.com/v1/embeddings",
                headers={"Authorization": f"Bearer {self._key}"},
                json={"model": self.model_name, "input": texts, "dimensions": self.dimensions},
            )
        if r.status_code != 200:
            raise ProviderError(f"embedding call failed with status {r.status_code}")
        data = sorted(r.json()["data"], key=lambda d: d["index"])
        return [d["embedding"] for d in data]


class OllamaEmbeddings:
    """Local embeddings through an Ollama server. Its model must output
    EMBEDDING_DIMENSIONS values, which must equal the column size."""

    is_local = True

    def __init__(self, url: str, model: str, dims: int):
        self._url = url.rstrip("/")
        self.model_name = model
        self.dimensions = dims

    async def embed(self, texts: list[str]) -> list[list[float]]:
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(f"{self._url}/api/embed", json={"model": self.model_name, "input": texts})
        if r.status_code != 200:
            raise ProviderError(f"local embedding call failed with status {r.status_code}")
        return list(r.json()["embeddings"])


def build_embeddings(s: Settings) -> EmbeddingProvider:
    p = s.embedding_provider
    if p == "openai":
        if not s.openai_api_key:
            raise RuntimeError("EMBEDDING_PROVIDER=openai needs OPENAI_API_KEY")
        return OpenAIEmbeddings(s.openai_api_key, s.embedding_model, s.embedding_dimensions)
    if p == "ollama":
        return OllamaEmbeddings(s.ollama_url, s.embedding_model, s.embedding_dimensions)
    if p == "fake":
        return FakeEmbeddings(s.embedding_dimensions)
    return HashingEmbeddings(s.embedding_dimensions)


def local_embeddings(s: Settings) -> EmbeddingProvider:
    """What local-mode people get: never a cloud embedder."""
    if s.embedding_provider == "ollama":
        return OllamaEmbeddings(s.ollama_url, s.embedding_model, s.embedding_dimensions)
    return HashingEmbeddings(s.embedding_dimensions)
