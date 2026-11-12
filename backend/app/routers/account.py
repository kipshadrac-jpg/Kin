from typing import Any

from fastapi import APIRouter, Response

from app.db.engine import user_session
from app.deps import DbDep, UserDep
from app.errors import AppError
from app.schemas.domain import DeleteAccountIn
from app.services import account as svc

router = APIRouter(prefix="/account", tags=["account"])


@router.get("/export")
async def export(user: UserDep, db: DbDep) -> dict[str, Any]:
    return await svc.export_all(db, user.id)


@router.delete("", status_code=204)
async def delete_account(body: DeleteAccountIn, user: UserDep) -> Response:
    if body.confirm.strip().lower() != svc.DELETE_CONFIRM_PHRASE:
        raise AppError(422, "confirm_phrase", f'Type "{svc.DELETE_CONFIRM_PHRASE}" to confirm')
    async with user_session(user.id) as db:
        await svc.delete_user_rows(db, user.id)
    await svc.delete_auth_user(user.id)
    return Response(status_code=204)
