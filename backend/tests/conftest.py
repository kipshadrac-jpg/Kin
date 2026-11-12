"""Test setup.

Unit tests need nothing. Integration tests need the local Postgres + GoTrue
stack (deploy/docker-compose.test.yml, or `./kin.sh test` on a server).
No test ever calls a real model provider: LLM and embeddings are fakes.
"""

import json
import os
import time
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import jwt
import pytest

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("DATABASE_URL", "postgresql://kin_api:apipass@localhost:55432/postgres")
os.environ.setdefault("DATABASE_ADMIN_URL", "postgresql://supabase_admin:testpass@localhost:55432/postgres")
os.environ.setdefault("KIN_API_DB_PASSWORD", "apipass")
os.environ.setdefault("KIN_WORKER_DB_PASSWORD", "workerpass")
os.environ.setdefault("SUPABASE_JWT_SECRET", "super-secret-jwt-token-with-at-least-32-characters")
os.environ.setdefault("GOTRUE_URL", "http://localhost:59999")
os.environ.setdefault("REDIS_URL", "redis://localhost:6390/0")  # nothing listens: jobs fail open
os.environ["LLM_PROVIDER"] = "fake"
os.environ["EMBEDDING_PROVIDER"] = "fake"
os.environ["ANTHROPIC_API_KEY"] = ""
os.environ["OPENAI_API_KEY"] = ""
os.environ.setdefault("RATE_LIMIT_ENABLED", "false")

FIXTURES = Path(__file__).parent / "fixtures" / "profiles"


def load_fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / f"{name}.json").read_text())


def _stack_up() -> bool:
    try:
        return httpx.get(os.environ["GOTRUE_URL"] + "/health", timeout=2).status_code == 200
    except httpx.HTTPError:
        return False


STACK_UP = _stack_up()


def pytest_collection_modifyitems(config: Any, items: list[Any]) -> None:
    skip = pytest.mark.skip(reason="local Postgres + GoTrue stack is not running")
    for item in items:
        if "integration" in str(item.fspath) or "evals" in str(item.fspath):
            item.add_marker(pytest.mark.integration)
            if not STACK_UP:
                item.add_marker(skip)


@pytest.fixture(scope="session", autouse=True)
async def _migrated() -> AsyncIterator[None]:
    if STACK_UP:
        from app.db.migrate import main as migrate_main

        assert await migrate_main() == 0
    yield


@pytest.fixture
async def fake_llm() -> AsyncIterator[Any]:
    from app.providers.embeddings import FakeEmbeddings
    from app.providers.llm import FakeLLM
    from app.providers.registry import Providers, set_providers
    from tests.fake_brain import fake_brain

    llm = FakeLLM(fake_brain)
    emb = FakeEmbeddings()
    set_providers(Providers(llm=llm, embeddings=emb, local_llm=llm, local_embeddings=emb))
    from app.routers import chat

    chat._graphs.clear()
    yield llm
    set_providers(None)
    chat._graphs.clear()


@pytest.fixture
async def client(fake_llm: Any) -> AsyncIterator[httpx.AsyncClient]:
    from app.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class TestUser:
    __test__ = False

    def __init__(self, user_id: uuid.UUID, token: str, email: str):
        self.id = user_id
        self.token = token
        self.email = email

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}


def signup() -> TestUser:
    """A real GoTrue signup: the token is exactly what the web app would send."""
    email = f"t-{uuid.uuid4().hex[:12]}@example.com"
    r = httpx.post(
        os.environ["GOTRUE_URL"] + "/signup", json={"email": email, "password": "correct-horse-9"}, timeout=10
    )
    r.raise_for_status()
    body = r.json()
    return TestUser(uuid.UUID(body["user"]["id"]), body["access_token"], email)


@pytest.fixture
def user() -> TestUser:
    return signup()


@pytest.fixture
def other_user() -> TestUser:
    return signup()


def forge_token(
    sub: str,
    *,
    secret: str | None = None,
    exp_delta: int = 3600,
    aud: str = "authenticated",
    role: str = "authenticated",
) -> str:
    now = int(time.time())
    return jwt.encode(
        {"sub": sub, "aud": aud, "role": role, "exp": now + exp_delta, "iat": now},
        secret or os.environ["SUPABASE_JWT_SECRET"],
        algorithm="HS256",
    )
