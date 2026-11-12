"""FastAPI gateway: auth, validation, rate limits. Routers hold no business logic."""

import logging
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.config import get_settings
from app.db.engine import dispose_engine, get_engine
from app.errors import install_error_handlers
from app.logging_setup import setup_logging
from app.providers.registry import get_providers
from app.routers import account, actions, chat, context, finance, habits, me, memories, reminders

log = logging.getLogger("kin.http")
EMBEDDING_COLUMN_DIMENSIONS = 1536  # must match vector(1536) in 0001_init.sql


def check_embedding_dimensions() -> None:
    """Fail fast: a provider with a different size would corrupt search."""
    p = get_providers()
    for emb in (p.embeddings, p.local_embeddings):
        if emb.dimensions != EMBEDDING_COLUMN_DIMENSIONS:
            raise RuntimeError(
                f"Embedding provider {emb.model_name} has {emb.dimensions} dimensions but the database column has "
                f"{EMBEDDING_COLUMN_DIMENSIONS}. Add a migration and re-embed before switching."
            )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    setup_logging()
    check_embedding_dimensions()
    yield
    await dispose_engine()


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(
        title=f"{s.app_name} API",
        version="0.1.0",
        lifespan=lifespan,
        docs_url=None if s.is_production else "/api/docs",
        openapi_url="/api/openapi.json",
        redoc_url=None,
    )
    install_error_handlers(app)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=s.cors_origin_list,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )

    @app.middleware("http")
    async def access_log(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
        start = time.perf_counter()
        response = await call_next(request)
        route = request.scope.get("route")
        log.info(
            "request",
            extra={
                "request_id": rid,
                "user_id": getattr(request.state, "user_id", None),
                "route": getattr(route, "path", "unmatched"),
                "method": request.method,
                "status": response.status_code,
                "latency_ms": round((time.perf_counter() - start) * 1000, 1),
            },
        )
        response.headers["x-request-id"] = rid
        return response

    @app.get("/api/v1/health")
    async def health() -> dict[str, str]:
        db = "ok"
        try:
            async with get_engine().connect() as conn:
                await conn.execute(text("select 1"))
        except Exception:  # noqa: BLE001
            db = "unavailable"
        return {"status": "ok" if db == "ok" else "degraded", "db": db}

    for r in (me, context, memories, account, chat, actions, habits, reminders, finance):
        app.include_router(r.router, prefix="/api/v1")
    return app


app = create_app()
