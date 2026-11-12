from fastapi import APIRouter

from app.config import get_settings
from app.deps import CurrentUser, DbDep, UserDep
from app.models.tables import Profile
from app.providers.registry import get_providers
from app.schemas.context import MeOut, MePatch
from app.services.context import get_profile

router = APIRouter(tags=["me"])


def _providers_info() -> dict[str, object]:
    p = get_providers()
    return {
        "cloud_llm": None if p.llm is None or p.llm.is_local else "Anthropic (Claude)",
        "cloud_embeddings": None if p.embeddings.is_local else "OpenAI (embeddings)",
        "local_available": p.local_llm is not None,
        "chat_ready": p.llm is not None,
    }


def _out(user: CurrentUser, prof: Profile) -> MeOut:
    return MeOut(
        user_id=user.id,
        email=user.email,
        display_name=prof.display_name,
        locale=prof.locale,
        privacy_mode=prof.privacy_mode,
        onboarding_state=prof.onboarding_state,
        app_name=get_settings().app_name,
        providers=_providers_info(),
    )


@router.get("/me", response_model=MeOut)
async def get_me(user: UserDep, db: DbDep) -> MeOut:
    return _out(user, await get_profile(db, user.id))


@router.patch("/me", response_model=MeOut)
async def patch_me(body: MePatch, user: UserDep, db: DbDep) -> MeOut:
    prof = await get_profile(db, user.id)
    for k, v in body.model_dump(exclude_unset=True).items():
        if v is not None:
            setattr(prof, k, v)
    await db.flush()
    return _out(user, prof)
