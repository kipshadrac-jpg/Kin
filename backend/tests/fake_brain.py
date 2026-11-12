"""A deterministic stand-in for the model, so the whole agent graph can be tested
offline. It behaves like a cooperative model; output checks and the commitment
boundary are still enforced by the real code under test."""

import re
from typing import Any

from pydantic import BaseModel

from app.agents.graph import explicit_commitment, keyword_intent
from app.agents.llm_io import (
    ActionChoice,
    Candidate,
    CaseOut,
    ExtractionOut,
    GoalChoice,
    HabitChoice,
    LogHabitChoice,
    ReminderChoice,
    RouterOut,
    ScenarioOut,
    SummaryOut,
    TurnOut,
    WhatIf,
)
from app.providers.base import Message

NO_ACTION = dict(
    create_habit=None, log_habit=None, set_reminder=None, set_goal=None, add_finance_entry=None, save_journal_text=None
)


def _refs(system: str) -> list[str]:
    m = re.search(r"References you may cite in used_refs: (.*)", system)
    return [r.strip() for r in m.group(1).split(",") if r.strip()] if m else []


def _what_if(msg: str) -> WhatIf | None:
    m = re.search(r"(\d[\d,]*)\s*(?:a|per|each)\s*(day|week|month)\s*for\s*(\d+)", msg, re.I)
    if not m:
        return None
    return WhatIf(
        amount_per_period=float(m.group(1).replace(",", "")), period=m.group(2).lower(), horizon_periods=int(m.group(3))
    )


def _action(system: str, msg: str) -> ActionChoice:
    t = msg.lower()
    if "COMMITMENT_ALLOWED: true" not in system:
        return ActionChoice(type="none", **NO_ACTION)
    if "remind me" in t:
        return ActionChoice(
            type="set_reminder",
            **{
                **NO_ACTION,
                "set_reminder": ReminderChoice(message="Walk", kind="habit", days=["MO", "WE", "FR"], time="06:30"),
            },
        )
    if "log that" in t or "log it" in t:
        m = re.search(r'"id": "([0-9a-f-]{36})"', system)
        hid = m.group(1) if m else "00000000-0000-0000-0000-000000000000"
        return ActionChoice(
            type="log_habit",
            **{**NO_ACTION, "log_habit": LogHabitChoice(habit_id=hid, occurred_on="2026-11-12", outcome="done")},
        )
    if "goal" in t:
        return ActionChoice(
            type="set_goal",
            **{
                **NO_ACTION,
                "set_goal": GoalChoice(
                    domain="finance",
                    title="Set aside 300 a week",
                    amount_per_period=300,
                    period="week",
                    horizon_periods=12,
                ),
            },
        )
    if "habit" in t:
        return ActionChoice(
            type="create_habit",
            **{
                **NO_ACTION,
                "create_habit": HabitChoice(
                    title="Walk 20 minutes",
                    why=None,
                    minimum_version="5 minutes",
                    times_per_week=3,
                    preferred_days=None,
                ),
            },
        )
    if "journal" in t:
        return ActionChoice(type="save_journal", **{**NO_ACTION, "save_journal_text": "Today was okay."})
    return ActionChoice(type="none", **NO_ACTION)


def fake_brain(system: str, messages: list[Message], schema: type[BaseModel] | None) -> Any:
    msg = messages[-1].content if messages else ""
    if schema is RouterOut:
        return RouterOut(
            intent=keyword_intent(msg),
            commitment_language=explicit_commitment(msg)  # type: ignore[arg-type]
            or "let's do it" in msg.lower(),
        )
    if schema is TurnOut:
        refs = _refs(system)[:2]
        reply = "Here is a grounded thought based on what you told me."
        if "TEST_DIRECTIVE" in msg:
            reply = "You should save 20% of it. That would give you 9999 by March."
        if "TEST_NEEDY" in msg:
            reply = "I missed you! Let's plan your week."
        return TurnOut(
            reply=reply,
            used_refs=refs + ["economic_frame.made_up_ref"],
            asks_about_gap=False,
            what_if=_what_if(msg),
            action=_action(system, msg),
        )
    if schema is ScenarioOut:
        return ScenarioOut(
            cases=[
                CaseOut(
                    name="best",
                    periods_hit_min=12,
                    periods_hit_max=12,
                    assumptions=["Every week works out"],
                    what_would_have_to_be_true="No slow weeks",
                ),
                CaseOut(
                    name="stress",
                    periods_hit_min=4,
                    periods_hit_max=6,
                    assumptions=["Rainy weeks cut sales", "School fees come first"],
                    what_would_have_to_be_true="A hard stretch",
                ),
                CaseOut(
                    name="realistic",
                    periods_hit_min=8,
                    periods_hit_max=10,
                    assumptions=["Income changes week to week"],
                    what_would_have_to_be_true="An ordinary mix",
                ),
            ],
            unknowns=[],
            used_refs=[r for r in _refs(system) if r.startswith("economic_frame")][:2],
        )
    if schema is ExtractionOut:
        text = msg.replace("<text>", "").replace("</text>", "")
        cands = []
        if "send money home" in text.lower():
            quote = re.search(r"[^.]*send money home[^.]*", text, re.I).group(0).strip()  # type: ignore[union-attr]
            cands.append(
                Candidate(
                    field_path="economic_frame.obligations", value="Sends money home every month", evidence_quote=quote
                )
            )
        # A hallucinated candidate the code must reject (quote is not in the text).
        cands.append(
            Candidate(
                field_path="values_profile.matters_most", value="wealth", evidence_quote="I care about wealth above all"
            )
        )
        return ExtractionOut(candidates=cands)
    if schema is SummaryOut:
        return SummaryOut(
            outcome_summary="Explored saving a little each week.", decisions=["Transport cuts don't work"]
        )
    # Plain-text call (the output-check repair step): return a clean rewrite.
    return "Here is one way to look at it, based on what you told me."
