"""Auth and database dependencies.

Identity comes ONLY from a verified Supabase JWT. No route accepts a user id
from the path or body.
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from functools import lru_cache
from typing import Annotated, Any
from uuid import UUID

import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.engine import user_session
from app.errors import AppError

_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class CurrentUser:
    id: UUID
    email: str | None
    claims: dict[str, Any]


@lru_cache
def _jwks_client(url: str) -> jwt.PyJWKClient:
    return jwt.PyJWKClient(url, cache_keys=True, lifespan=3600)


def verify_token(token: str) -> dict[str, Any]:
    """Check signature, expiry and audience. Asymmetric keys via JWKS when configured,
    otherwise the shared HS256 secret that self-hosted GoTrue signs with."""
    s = get_settings()
    options: Any = {"require": ["exp", "sub", "aud"]}
    try:
        header = jwt.get_unverified_header(token)
        alg = header.get("alg", "")
        if alg.startswith(("RS", "ES", "PS", "Ed")) and s.supabase_jwks_url:
            key = _jwks_client(s.supabase_jwks_url).get_signing_key_from_jwt(token).key
            return jwt.decode(token, key, algorithms=[alg], audience=s.supabase_jwt_audience, options=options)
        if alg == "HS256" and s.supabase_jwt_secret:
            return jwt.decode(
                token, s.supabase_jwt_secret, algorithms=["HS256"], audience=s.supabase_jwt_audience, options=options
            )
    except jwt.PyJWTError as exc:
        raise AppError(401, "invalid_token", "Your session is not valid. Please sign in again.") from exc
    raise AppError(401, "invalid_token", "Your session is not valid. Please sign in again.")


async def current_user(
    request: Request, creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)]
) -> CurrentUser:
    if creds is None or creds.scheme.lower() != "bearer":
        raise AppError(401, "missing_token", "Sign in to continue.")
    claims = verify_token(creds.credentials)
    if claims.get("role") != "authenticated":
        raise AppError(403, "forbidden", "This token cannot be used here.")
    try:
        uid = UUID(str(claims["sub"]))
    except ValueError as exc:
        raise AppError(401, "invalid_token", "Your session is not valid.") from exc
    request.state.user_id = str(uid)  # for structured logs (an ID, never content)
    return CurrentUser(id=uid, email=claims.get("email"), claims=claims)


async def db_session(user: Annotated[CurrentUser, Depends(current_user)]) -> AsyncIterator[AsyncSession]:
    async with user_session(user.id, "authenticated") as session:
        yield session


UserDep = Annotated[CurrentUser, Depends(current_user)]
# scope="function": commit BEFORE the response is sent, so a client never sees
# success for a write that later fails to commit.
DbDep = Annotated[AsyncSession, Depends(db_session, scope="function")]
