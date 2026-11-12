"""The agent turn as an explicit LangGraph state graph (Section 4):

    safety_screen -> router -> context_inject -> domain_agent -> output_checks -> persist
          '-------------(crisis / severe distress)------------------^

The agent runtime reads through the `kin_agent` database role, which can only
INSERT into action_queue, context_proposals, reasoning_sessions, scenarios and
memories. It cannot write habits, money entries, goals, reminders or the
profile — those happen only when the person approves a card.
"""

import json
import re
from datetime import date, datetime
from decimal import Decimal
from typing import Any, TypedDict
from uuid import UUID
from zoneinfo import ZoneInfo

from langgraph.graph import END, START, StateGraph
from sqlalchemy import select

from app.agents.llm_io import (
    ActionChoice,
    RouterOut,
    ScenarioOut,
    TurnOut,
    prompt,
    structured,
)
from app.config import get_settings
from app.db.engine import user_session
from app.errors import AppError
from app.models.tables import FinanceEntry, Habit, ReasoningSession, Scenario
from app.providers.base import EmbeddingProvider, LLMProvider, Message, ProviderError
from app.safety import output_checks as oc
from app.safety.screens import screen
from app.services import actions as actions_svc
from app.services.bundle import ContextBundle, get_context_bundle
from app.services.scenarios import CaseChoice, SetAsideInput, compute_set_aside, numbers_in, validate_scenario

STRONG_COMMIT = [
    r"\bmake (this|that|it) (my|a) goal\b",
    r"\bset (this|that|it) (up|as (my|a) goal)\b",
    r"\bremind me\b",
    r"\blog (that|this|it)\b",
    r"\bsave (this|that|it) (to|in) my journal\b",
    r"\bmark (it|that|this) (as )?done\b",
]
COMMIT = STRONG_COMMIT + [
    r"\b(add|save|track|record) (this|that|it)\b",
    r"\bcreate (a |the )?habit\b",
    r"\bstart (a|the|this) habit\b",
    r"\bset (a |my |the )?(goal|reminder)\b",
    r"\badd (my|a|an) \w+",
    r"\bput (this|that|it) (in|on)\b",
    r"\bplease (log|add|save|set)\b",
]
HEDGE = [
    r"\bwhat if\b",
    r"\bshould i\b",
    r"\bmaybe\b",
    r"\bthinking (about|of)\b",
    r"\bwould it\b",
    r"\bcould i\b",
    r"\bhypothetically\b",
    r"\bwondering\b",
    r"\bnot sure\b",
    r"\bhow (much|would)\b",
    r"\bimagine\b",
]
FINANCE_INTENTS = {"finance_query", "finance_log"}
PURPOSE_BY_INTENT = {
    "habit_log": "habits",
    "habit_plan": "habits",
    "finance_query": "finance",
    "finance_log": "finance",
    "motivation_request": "motivation",
    "open_reasoning": "general",
    "profile_edit": "general",
    "safety_escalation": "general",
}
ASK_COMMITMENT = "Want me to set that up, or are we still thinking?"


def explicit_commitment(text: str) -> bool:
    """The commitment boundary (Section 9.3), decided in code. A model's opinion
    alone can never queue an action."""
    t = text.lower()
    if any(re.search(p, t) for p in STRONG_COMMIT):
        return True
    return any(re.search(p, t) for p in COMMIT) and not any(re.search(p, t) for p in HEDGE)


def keyword_intent(text: str) -> str:
    t = text.lower()
    if re.search(r"\b(kes|ksh|usd|money|save|saving|spend|budget|loan|debt|income|salary|rent|pay|cost|afford|\$)", t):
        return "finance_query" if re.search(r"\?|what if|should|how much|could", t) else "finance_log"
    if re.search(r"\b(habit|walk|run|exercise|read|routine|pray|meditat|gym|sleep)", t):
        return "habit_log" if re.search(r"\b(did|done|finished|walked|ran|read today|skipped)\b", t) else "habit_plan"
    if re.search(r"\b(stuck|tired|unmotivated|can't keep|give up|motivat)", t):
        return "motivation_request"
    return "open_reasoning"


class TurnState(TypedDict, total=False):
    user_id: UUID
    privacy_mode: str
    session_id: UUID | None
    message: str
    history: list[Message]
    today: date
    country: str | None
    timezone: str
    # filled by nodes
    screen: dict[str, Any]
    intent: str
    commitment_explicit: bool
    commitment_model: bool
    bundle: ContextBundle
    habits: list[dict[str, str]]
    finance_numbers: list[str]
    turn: TurnOut | None
    reply: str
    cards: list[dict[str, Any]]
    scenario: dict[str, Any] | None
    pending_action: dict[str, Any] | None
    context_used: list[dict[str, str]]
    flags: list[str]
    result: dict[str, Any]


def _blocks(bundle: ContextBundle, habits: list[dict[str, str]] | None) -> str:
    mems = [m for m in bundle.memories if m["kind"] != "session_summary"]
    sessions = [m for m in bundle.memories if m["kind"] == "session_summary"]
    parts = [
        "<context>\n" + json.dumps(bundle.profile, ensure_ascii=False, indent=1) + "\n</context>",
        "GAPS (unknown, matter for this question — ask or stay general, never assume): "
        + (", ".join(bundle.gaps) if bundle.gaps else "none"),
        "<memories>\n" + "\n".join(f"[memory:{m['id']}] {m['content'][:600]}" for m in mems) + "\n</memories>",
        "<earlier_sessions>\n"
        + "\n".join(
            f"[memory:{m['id']}] (session {m['metadata'].get('session_id', '?')}) {m['content'][:400]}"
            for m in sessions
        )
        + "\n</earlier_sessions>",
    ]
    if habits is not None:
        parts.append("Their habits: " + json.dumps(habits, ensure_ascii=False))
    parts.append(
        "References you may cite in used_refs: "
        + ", ".join(bundle.fact_refs() + [f"memory:{m['id']}" for m in bundle.memories])
    )
    return "\n\n".join(parts)


def build_graph(llm: LLMProvider | None, embedder: EmbeddingProvider) -> Any:
    settings = get_settings()
    base_system = prompt("system_v1.md").replace("{app_name}", settings.app_name)

    async def safety_screen(state: TurnState) -> dict[str, Any]:
        s = screen(state["message"])
        out: dict[str, Any] = {
            "screen": s.__dict__,
            "flags": [],
            "cards": [],
            "scenario": None,
            "pending_action": None,
            "context_used": [],
            "turn": None,
        }
        if s.crisis:
            reply, cards = oc.crisis_reply(state.get("country"))
            out.update(intent="safety_escalation", reply=reply, cards=cards, flags=["crisis"])
        elif s.financial_distress:
            reply, cards = oc.financial_distress_reply(state.get("country"))
            out.update(intent="safety_escalation", reply=reply, cards=cards, flags=["financial_distress"])
        return out

    def after_screen(state: TurnState) -> str:
        return "output_checks" if state.get("intent") == "safety_escalation" else "router"

    async def router(state: TurnState) -> dict[str, Any]:
        explicit = explicit_commitment(state["message"])
        intent, model_commit = keyword_intent(state["message"]), False
        if llm is not None:
            try:
                r = await structured(
                    llm,
                    system=prompt("router_v1.md"),
                    schema=RouterOut,
                    max_tokens=200,
                    effort="low",
                    messages=[*state.get("history", [])[-4:], Message(role="user", content=state["message"])],
                )
                intent, model_commit = r.intent, r.commitment_language
            except ProviderError:
                pass  # keyword fallback keeps the app usable if the model is down
        out: dict[str, Any] = {"intent": intent, "commitment_explicit": explicit, "commitment_model": model_commit}
        if intent == "safety_escalation":
            reply, cards = oc.crisis_reply(state.get("country"))
            out.update(reply=reply, cards=cards, flags=[*state.get("flags", []), "router_escalation"])
        return out

    def after_router(state: TurnState) -> str:
        return "output_checks" if state.get("intent") == "safety_escalation" else "context_inject"

    async def context_inject(state: TurnState) -> dict[str, Any]:
        purpose = PURPOSE_BY_INTENT.get(state["intent"], "general")
        async with user_session(state["user_id"], "kin_agent") as db:
            bundle = await get_context_bundle(db, state["user_id"], purpose, state["message"], embedder)  # type: ignore[arg-type]
            habits = None
            if state["intent"] in ("habit_log", "habit_plan"):
                rows = (
                    await db.execute(
                        select(Habit.id, Habit.title).where(Habit.user_id == state["user_id"], Habit.status == "active")
                    )
                ).all()
                habits = [{"id": str(i), "title": t} for i, t in rows]
            fin: list[str] = []
            if state["intent"] in FINANCE_INTENTS:
                for e in (
                    await db.execute(select(FinanceEntry).where(FinanceEntry.user_id == state["user_id"]))
                ).scalars():
                    fin += [str(e.amount_min), str(e.amount_max)]
        return {"bundle": bundle, "habits": habits or [], "finance_numbers": fin}

    async def domain_agent(state: TurnState) -> dict[str, Any]:
        if llm is None:
            raise AppError(503, "no_model", "The thinking part of Kin isn't set up on this server yet.")
        bundle, intent = state["bundle"], state["intent"]
        minor_money = bool(state["screen"].get("possible_minor")) and intent in FINANCE_INTENTS
        allowed = bool(state["commitment_explicit"]) and not minor_money
        tz = state.get("timezone") or "UTC"
        today = state["today"]
        system = "\n\n".join(
            [
                base_system,
                f"Today is {today.strftime('%A %d %B %Y')} ({tz}). Intent: {intent}.",
                (
                    "COMMITMENT_ALLOWED: true — the person clearly asked you to do something. Put exactly one matching "
                    "action in `action`; the person will approve it on a card before anything happens."
                    if allowed
                    else 'COMMITMENT_ALLOWED: false — set action.type to "none". Do not offer to set anything up.'
                ),
                "If they describe a what-if about setting aside a fixed amount regularly, fill `what_if` with their "
                "amount, period and number of periods; otherwise null. Never compute totals in `reply`.",
                "In `used_refs` list the references from the blocks below that your reply actually relies on.",
                _blocks(bundle, state.get("habits") if intent in ("habit_log", "habit_plan") else None),
            ]
        )
        msgs = [*state.get("history", [])[-10:], Message(role="user", content=state["message"])]
        try:
            turn = await structured(llm, system=system, messages=msgs, schema=TurnOut, max_tokens=2000, effort="medium")
        except ProviderError:
            return {
                "turn": None,
                "reply": "I couldn't think that through just now. Could you try again in a moment?",
                "flags": [*state.get("flags", []), "model_error"],
            }
        update: dict[str, Any] = {"turn": turn, "reply": turn.reply}
        if not allowed:
            turn.action = ActionChoice(
                type="none",
                create_habit=None,
                log_habit=None,
                set_reminder=None,
                set_goal=None,
                add_finance_entry=None,
                save_journal_text=None,
            )
            if state.get("commitment_model") and not state["commitment_explicit"]:
                update["reply"] = turn.reply.rstrip() + "\n\n" + ASK_COMMITMENT
        if turn.what_if is not None and (intent in FINANCE_INTENTS or intent == "open_reasoning"):
            update["scenario"] = await _scenario(llm, state, turn)
        if turn.action.type != "none":
            update["pending_action"] = _action_payload(turn.action, state, bundle)
        return update

    async def output_checks(state: TurnState) -> dict[str, Any]:
        reply = state.get("reply", "")
        flags = list(state.get("flags", []))
        if state.get("intent") == "safety_escalation":
            return {"reply": reply, "flags": flags, "pending_action": None, "scenario": None}
        intent = state.get("intent", "")
        is_finance = intent in FINANCE_INTENTS or state.get("scenario") is not None
        bundle: ContextBundle | None = state.get("bundle")
        allowed_numbers = _allowed_numbers(state)

        def problems_of(text: str) -> list[str]:
            p = []
            if is_finance:
                p += [f"directive phrase: {h}" for h in oc.directive_phrases(text)]
                p += [
                    f"number not from their data or the computed card: {n}"
                    for n in oc.unsupported_numbers(text, allowed_numbers)
                ]
            p += [f"generic advice: {h}" for h in oc.generic_advice(text)]
            p += [f"implies the app has needs: {h}" for h in oc.needy_language(text)]
            return p

        problems = problems_of(reply)
        if problems and llm is not None and state.get("turn") is not None:
            flags.append("repaired")
            try:
                fix = await llm.complete(
                    system=prompt("system_v1.md").replace("{app_name}", settings.app_name),
                    messages=[
                        Message(
                            role="user",
                            content=(
                                "Rewrite this reply so it fixes these problems, keeping its meaning, tone and length. "
                                "Return only the new reply text.\nProblems: "
                                + "; ".join(problems)
                                + "\n\n<reply>\n"
                                + reply
                                + "\n</reply>"
                            ),
                        )
                    ],
                    max_tokens=800,
                    effort="low",
                )
                reply = fix.text
            except ProviderError:
                pass
            problems = problems_of(reply)
        if problems:
            flags.append("sentences_removed")
            reply = _drop_bad_sentences(reply, problems_of)
            if not reply:
                reply = (
                    "Here's how it could look. The card shows the ranges and what I assumed."
                    if state.get("scenario")
                    else "I want to keep this grounded in what you've told me. Can you say a bit more?"
                )
        scenario = state.get("scenario")
        if scenario is not None and validate_scenario(scenario):
            flags.append("scenario_rejected")
            scenario = None
        if is_finance and oc.needs_referral(state["message"] + " " + reply):
            reply = reply.rstrip() + "\n\n" + oc.referral_note(state.get("country"))
        if state["screen"].get("reliance"):
            reply = reply.rstrip() + (
                "\n\nI'm glad talking here helps. Is there someone in your life you could share some of this with too?"
            )
        pending = state.get("pending_action")
        if (
            pending
            and state["screen"].get("possible_minor")
            and pending["action_type"] in ("add_finance_entry", "set_goal")
        ):
            flags.append("minor_finance_blocked")
            pending = None
        used = _context_used(state.get("turn"), bundle, scenario)
        return {"reply": reply, "flags": flags, "scenario": scenario, "pending_action": pending, "context_used": used}

    async def persist(state: TurnState) -> dict[str, Any]:
        uid = state["user_id"]
        async with user_session(uid, "kin_agent") as db:
            sess = None
            if state.get("session_id"):
                sess = await db.scalar(
                    select(ReasoningSession).where(
                        ReasoningSession.id == state["session_id"], ReasoningSession.user_id == uid
                    )
                )
            if sess is None:
                sess = ReasoningSession(user_id=uid, topic=state["message"][:80], transcript=[])
                db.add(sess)
                await db.flush()
            now = datetime.now().astimezone().isoformat()
            sess.transcript = [
                *sess.transcript,
                {"role": "user", "content": state["message"], "at": now},
                {
                    "role": "assistant",
                    "content": state.get("reply", ""),
                    "at": now,
                    "context_used": state.get("context_used", []),
                    "intent": state.get("intent"),
                },
            ]
            scenario_id = None
            scenario = state.get("scenario")
            if scenario:
                sc = Scenario(user_id=uid, session_id=sess.id, premise=scenario["premise"], result=scenario)
                db.add(sc)
                await db.flush()
                scenario_id = sc.id
            action = None
            pa = state.get("pending_action")
            if pa:
                try:
                    row = await actions_svc.enqueue(db, uid, pa["action_type"], pa["payload"], sess.id)
                    action = {
                        "id": str(row.id),
                        "action_type": row.action_type,
                        "preview": row.preview,
                        "status": row.status,
                    }
                except AppError:
                    pass  # an invalid model payload is simply not offered
            await db.flush()
            result = {
                "session_id": str(sess.id),
                "reply": state.get("reply", ""),
                "intent": state.get("intent"),
                "context_used": state.get("context_used", []),
                "gaps": state["bundle"].gap_labels if state.get("bundle") else [],
                "scenario": ({**scenario, "id": str(scenario_id)} if scenario else None),
                "action": action,
                "support": state.get("cards", []),
                "flags": state.get("flags", []),
            }
        return {"result": result}

    g = StateGraph(TurnState)
    g.add_node("safety_screen", safety_screen)
    g.add_node("router", router)
    g.add_node("context_inject", context_inject)
    g.add_node("domain_agent", domain_agent)
    g.add_node("output_checks", output_checks)
    g.add_node("persist", persist)
    g.add_edge(START, "safety_screen")
    g.add_conditional_edges("safety_screen", after_screen, ["router", "output_checks"])
    g.add_conditional_edges("router", after_router, ["context_inject", "output_checks"])
    g.add_edge("context_inject", "domain_agent")
    g.add_edge("domain_agent", "output_checks")
    g.add_edge("output_checks", "persist")
    g.add_edge("persist", END)
    return g.compile()


async def _scenario(llm: LLMProvider, state: TurnState, turn: TurnOut) -> dict[str, Any] | None:
    wi = turn.what_if
    assert wi is not None
    bundle = state["bundle"]
    return await choose_and_compute_set_aside(
        llm,
        bundle,
        Decimal(str(wi.amount_per_period)),
        wi.period,
        wi.horizon_periods,
        premise=state["message"][:200],
    )


async def choose_and_compute_set_aside(
    llm: LLMProvider | None, bundle: ContextBundle, amount: Decimal, period: str, horizon: int, premise: str
) -> dict[str, Any] | None:
    """The model picks assumptions; code computes every number."""
    currency = str(bundle.profile.get("region", {}).get("currency") or "XXX")
    p_word = period
    unknowns: list[str] = []
    used_refs: list[str] = []
    if llm is not None:
        system = (
            prompt("scenario_v1.md").replace("{horizon}", str(horizon)).replace("{period}", p_word)
            + "\n\n"
            + _blocks(bundle, None)
        )
        try:
            out = await structured(
                llm,
                system=system,
                schema=ScenarioOut,
                max_tokens=1500,
                effort="low",
                messages=[
                    Message(role="user", content=f"What-if: set aside {amount} each {period} for {horizon} {period}s.")
                ],
            )
            cases = [CaseChoice(**c.model_dump()) for c in out.cases]
            unknowns, used_refs = out.unknowns, out.used_refs
        except (ProviderError, ValueError):
            cases = []
    else:
        cases = []
    if {c.name for c in cases} != {"best", "realistic", "stress"}:
        # Plain fallback assumptions, clearly labelled, when the model can't help.
        h = horizon
        cases = [
            CaseChoice(
                name="best",
                periods_hit_min=h,
                periods_hit_max=h,
                assumptions=[f"Every {period} works out"],
                what_would_have_to_be_true="Nothing gets in the way",
            ),
            CaseChoice(
                name="realistic",
                periods_hit_min=max(1, round(h * 0.6)),
                periods_hit_max=max(1, round(h * 0.85)),
                assumptions=["Some periods are missed, as happens to most people"],
                what_would_have_to_be_true="An ordinary mix of easy and hard periods",
            ),
            CaseChoice(
                name="stress",
                periods_hit_min=max(0, round(h * 0.3)),
                periods_hit_max=max(1, round(h * 0.5)),
                assumptions=["A hard stretch; fixed obligations still come first"],
                what_would_have_to_be_true="Several difficult periods close together",
            ),
        ]
        unknowns.append("These are rough defaults, not based on your own pattern yet")
    if currency == "XXX":
        unknowns.append("Your currency isn't in your profile yet")
    inp = SetAsideInput(
        premise=premise,
        currency=currency,
        amount_per_period=amount,
        period=period,  # type: ignore[arg-type]
        horizon_periods=horizon,
        cases=cases,
    )
    result = compute_set_aside(inp)
    valid_refs = set(bundle.fact_refs()) | {f"memory:{m['id']}" for m in bundle.memories}
    result["context_used"] = [r for r in used_refs if r in valid_refs]
    result["context_used_labels"] = [bundle.label_for(r) for r in result["context_used"]]
    result["unknowns"] = unknowns
    return result


def _action_payload(a: ActionChoice, state: TurnState, bundle: ContextBundle) -> dict[str, Any] | None:
    tz = state.get("timezone") or "UTC"
    currency = bundle.profile.get("region", {}).get("currency")
    if a.type == "create_habit" and a.create_habit:
        h = a.create_habit
        cad = {k: v for k, v in {"times_per_week": h.times_per_week, "preferred_days": h.preferred_days}.items() if v}
        return {
            "action_type": "create_habit",
            "payload": {"title": h.title, "why": h.why, "minimum_version": h.minimum_version, "cadence": cad},
        }
    if a.type == "log_habit" and a.log_habit:
        title = next((h["title"] for h in state.get("habits", []) if h["id"] == a.log_habit.habit_id), None)
        if title is None:
            return None  # the model may only log habits that exist
        return {
            "action_type": "log_habit",
            "payload": {
                "habit_id": a.log_habit.habit_id,
                "habit_title": title,
                "occurred_on": a.log_habit.occurred_on,
                "outcome": a.log_habit.outcome,
            },
        }
    if a.type == "set_reminder" and a.set_reminder:
        r = a.set_reminder
        return {
            "action_type": "set_reminder",
            "payload": {"message": r.message, "kind": r.kind, "days": r.days, "time": r.time, "timezone": tz},
        }
    if a.type == "set_goal" and a.set_goal:
        g = a.set_goal
        return {
            "action_type": "set_goal",
            "payload": {
                k: v
                for k, v in {
                    "domain": g.domain,
                    "title": g.title,
                    "amount_per_period": g.amount_per_period,
                    "period": g.period,
                    "horizon_periods": g.horizon_periods,
                    "currency": currency if g.amount_per_period else None,
                }.items()
                if v is not None
            },
        }
    if a.type == "add_finance_entry" and a.add_finance_entry and currency:
        f = a.add_finance_entry
        return {"action_type": "add_finance_entry", "payload": {**f.model_dump(), "currency": currency}}
    if a.type == "save_journal" and a.save_journal_text:
        return {"action_type": "save_journal", "payload": {"content": a.save_journal_text}}
    return None


def _allowed_numbers(state: TurnState) -> set[Decimal]:
    allowed: set[Decimal] = set()
    allowed |= numbers_in(state.get("scenario") or {})
    allowed |= numbers_in(state.get("finance_numbers") or [])
    if state.get("bundle"):
        allowed |= numbers_in(state["bundle"].profile)
    allowed |= numbers_in(state["message"])
    for m in state.get("history", []):
        if m.role == "user":
            allowed |= numbers_in(m.content)
    # Dates and times are not money claims.
    today = state.get("today") or date.today()
    allowed |= {Decimal(today.year).quantize(Decimal("0.01")), Decimal(today.day).quantize(Decimal("0.01"))}
    return allowed


def _drop_bad_sentences(text: str, problems_of: Any) -> str:
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    return " ".join(s for s in sentences if not problems_of(s)).strip()


def _context_used(
    turn: TurnOut | None, bundle: ContextBundle | None, scenario: dict[str, Any] | None
) -> list[dict[str, str]]:
    if bundle is None:
        return []
    valid = set(bundle.fact_refs()) | {f"memory:{m['id']}" for m in bundle.memories}
    refs: list[str] = []
    for r in (turn.used_refs if turn else []) + ((scenario or {}).get("context_used") or []):
        if r in valid and r not in refs:
            refs.append(r)
    return [{"ref": r, "label": bundle.label_for(r)} for r in refs]


def person_today(timezone: str | None) -> date:
    try:
        return datetime.now(ZoneInfo(timezone or "UTC")).date()
    except Exception:  # noqa: BLE001 — unknown tz falls back to UTC
        return datetime.now(ZoneInfo("UTC")).date()
