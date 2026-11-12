from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Response
from sqlalchemy import select

from app.agents.graph import choose_and_compute_set_aside
from app.deps import DbDep, UserDep
from app.errors import AppError, not_found
from app.models.tables import Scenario
from app.providers.registry import embeddings_for, llm_for, set_privacy_mode
from app.schemas.domain import ActionOut, Created, FinanceEntryIn, FinanceEntryOut, ScenarioRequest
from app.services import actions as actions_svc
from app.services import finance as svc
from app.services.bundle import get_context_bundle
from app.services.context import get_profile
from app.services.scenarios import FlowIn, compute_cash_flow, validate_scenario

router = APIRouter(prefix="/finance", tags=["finance"])


@router.get("/entries", response_model=list[FinanceEntryOut])
async def list_entries(user: UserDep, db: DbDep) -> list[Any]:
    return await svc.list_entries(db, user.id)


@router.post("/entries", response_model=Created, status_code=201)
async def create_entry(body: FinanceEntryIn, user: UserDep, db: DbDep) -> Any:
    return await svc.create_entry(db, user.id, body.model_dump())


@router.put("/entries/{entry_id}", response_model=FinanceEntryOut)
async def update_entry(entry_id: UUID, body: FinanceEntryIn, user: UserDep, db: DbDep) -> Any:
    return await svc.update_entry(db, user.id, entry_id, body.model_dump())


@router.delete("/entries/{entry_id}", status_code=204)
async def delete_entry(entry_id: UUID, user: UserDep, db: DbDep) -> Response:
    await svc.delete_entry(db, user.id, entry_id)
    return Response(status_code=204)


@router.post("/scenarios")
async def run_scenario(body: ScenarioRequest, user: UserDep, db: DbDep) -> dict[str, Any]:
    """A what-if. Pure exploration: never queues an action (Section 9.3)."""
    prof = await get_profile(db, user.id)
    set_privacy_mode(prof.privacy_mode)
    query = body.premise or "saving money each week"
    bundle = await get_context_bundle(db, user.id, "finance", query, embeddings_for(prof.privacy_mode))
    currency = str(bundle.profile.get("region", {}).get("currency") or "XXX")
    if body.kind == "set_aside":
        if body.amount_per_period is None:
            raise AppError(422, "missing_amount", "How much would you set aside each time?")
        premise = (
            body.premise
            or f"Set aside {body.amount_per_period} a {body.period} for {body.horizon_periods} {body.period}s"
        )
        result = await choose_and_compute_set_aside(
            llm_for(prof.privacy_mode),
            bundle,
            Decimal(body.amount_per_period),
            body.period,
            body.horizon_periods,
            premise,
        )
    else:
        entries = await svc.list_entries(db, user.id)
        flows = [
            FlowIn.model_validate(
                {
                    c: getattr(e, c)
                    for c in (
                        "direction",
                        "label",
                        "amount_min",
                        "amount_max",
                        "currency",
                        "frequency",
                        "is_obligation",
                    )
                }
            )
            for e in entries
        ]
        if not flows:
            raise AppError(422, "no_entries", "Add what comes in and goes out first.")
        weeks = (
            body.horizon_periods * {"day": 1, "week": 1, "month": 4}[body.period]
            if body.period != "day"
            else max(1, body.horizon_periods // 7)
        )
        result = compute_cash_flow(flows, currency, weeks, body.premise or f"The next {weeks} weeks")
        result["context_used"] = [
            r for r in ("economic_frame.income_pattern", "economic_frame.obligations") if r in bundle.fact_refs()
        ]
        result["context_used_labels"] = [bundle.label_for(r) for r in result["context_used"]]
    assert result is not None
    problems = validate_scenario(result)
    if problems:
        raise AppError(500, "scenario_invalid", "The scenario did not pass its checks", {"problems": problems})
    sc = Scenario(user_id=user.id, premise=result["premise"], result=result)
    db.add(sc)
    await db.flush()
    return {**result, "id": str(sc.id), "gaps": bundle.gap_labels}


@router.get("/scenarios")
async def recent_scenarios(user: UserDep, db: DbDep) -> list[dict[str, Any]]:
    rows = (
        await db.execute(
            select(Scenario).where(Scenario.user_id == user.id).order_by(Scenario.created_at.desc()).limit(10)
        )
    ).scalars()
    return [{**r.result, "id": str(r.id), "created_at": r.created_at.isoformat()} for r in rows]


@router.post("/scenarios/{scenario_id}/make-goal", response_model=ActionOut, status_code=201)
async def make_goal(scenario_id: UUID, user: UserDep, db: DbDep) -> Any:
    """The person tapped "Make this my goal". That is explicit commitment, but the
    goal still goes to the approval feed, so they confirm the exact wording."""
    sc = await db.scalar(select(Scenario).where(Scenario.id == scenario_id, Scenario.user_id == user.id))
    if sc is None:
        raise not_found("scenario")
    r = sc.result
    if r.get("kind") != "set_aside":
        raise AppError(422, "not_a_goal", "Only set-aside what-ifs can become a goal")
    payload = {
        "domain": "finance",
        "title": r["premise"][:160],
        "amount_per_period": r["amount_per_period"],
        "period": r["period"],
        "horizon_periods": r["horizon_periods"],
        "scenario_id": str(sc.id),
    }
    if r.get("currency") and r["currency"] != "XXX":
        payload["currency"] = r["currency"]
    return await actions_svc.enqueue(db, user.id, "set_goal", payload, sc.session_id)


@router.get("/goals")
async def goals(user: UserDep, db: DbDep) -> list[dict[str, Any]]:
    from app.models.tables import Goal

    rows = (
        await db.execute(
            select(Goal).where(Goal.user_id == user.id, Goal.status == "active").order_by(Goal.created_at.desc())
        )
    ).scalars()
    return [
        {"id": str(g.id), "domain": g.domain, "title": g.title, "detail": g.detail, "status": g.status} for g in rows
    ]
