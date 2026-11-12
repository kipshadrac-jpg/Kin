"""Deterministic scenario arithmetic (Sections 8 and 10).

The model only chooses assumptions (e.g. "in a hard stretch, 4 to 6 of 12
weeks work out"). Every number in the result is computed here, in plain
Python, so it can be tested and can never be invented by a model.
Invariant, enforced by construction: stress <= realistic <= best.
"""

from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field

CaseName = Literal["best", "realistic", "stress"]
CASE_ORDER: tuple[CaseName, ...] = ("best", "realistic", "stress")
WEEKS_PER = {"daily": Decimal(7), "weekly": Decimal(1), "monthly": Decimal(12) / Decimal(52)}


def money(x: Decimal) -> Decimal:
    return x.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def num(x: Decimal) -> int | float:
    """JSON-friendly number: whole amounts as int, otherwise 2-decimal float."""
    q = money(x)
    return int(q) if q == q.to_integral_value() else float(q)


class CaseChoice(BaseModel):
    """What the model is allowed to choose for one case of a set-aside scenario."""

    name: CaseName
    periods_hit_min: int = Field(ge=0)
    periods_hit_max: int = Field(ge=0)
    assumptions: list[str] = Field(min_length=1)
    what_would_have_to_be_true: str


class SetAsideInput(BaseModel):
    premise: str
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    amount_per_period: Decimal = Field(gt=0)
    period: Literal["day", "week", "month"]
    horizon_periods: int = Field(gt=0, le=520)
    cases: list[CaseChoice]


def compute_set_aside(inp: SetAsideInput) -> dict[str, Any]:
    by_name = {c.name: c for c in inp.cases}
    if set(by_name) != set(CASE_ORDER):
        raise ValueError("need exactly best, realistic and stress cases")
    h = inp.horizon_periods
    hits: dict[str, list[int]] = {}
    for name, c in by_name.items():
        lo = min(max(c.periods_hit_min, 0), h)
        hits[name] = [lo, min(max(c.periods_hit_max, lo), h)]
    # Re-label by size so the wording that produced the smallest range is the
    # stress case, even if the chosen assumptions came back in the wrong order.
    order = sorted(by_name, key=lambda n: (hits[n][0] + hits[n][1], hits[n][1]))
    slots = dict(zip(("stress", "realistic", "best"), order, strict=True))
    s_hit, r_hit, b_hit = (list(hits[slots[n]]) for n in ("stress", "realistic", "best"))
    # Make the bounds monotone so stress <= realistic <= best holds at both ends.
    r_hit = [max(r_hit[0], s_hit[0]), max(r_hit[1], s_hit[1])]
    b_hit = [max(b_hit[0], r_hit[0]), max(b_hit[1], r_hit[1])]
    final = {"stress": s_hit, "realistic": r_hit, "best": b_hit}
    cases = []
    for slot in CASE_ORDER:
        src = by_name[slots[slot]]
        lo_hit, hi_hit = final[slot]
        cases.append(
            {
                "name": slot,
                "assumptions": list(src.assumptions),
                "periods_hit": [lo_hit, hi_hit],
                "outcome_range": [num(inp.amount_per_period * lo_hit), num(inp.amount_per_period * hi_hit)],
                "what_would_have_to_be_true": src.what_would_have_to_be_true,
            }
        )
    return {
        "kind": "set_aside",
        "premise": inp.premise,
        "currency": inp.currency,
        "amount_per_period": num(inp.amount_per_period),
        "period": inp.period,
        "horizon_periods": inp.horizon_periods,
        "cases": cases,
        "context_used": [],
        "unknowns": [],
        "not_advice_note": True,
    }


class FlowIn(BaseModel):
    direction: Literal["in", "out", "set_aside"]
    label: str
    amount_min: Decimal = Field(ge=0)
    amount_max: Decimal = Field(ge=0)
    currency: str
    frequency: Literal["daily", "weekly", "monthly", "seasonal", "one_off", "irregular"]
    is_obligation: bool = False


def compute_cash_flow(
    flows: list[FlowIn], currency: str, horizon_weeks: int, premise: str = "What a typical stretch looks like"
) -> dict[str, Any]:
    """Weekly net = money in minus money out (set-asides count as out).

    Stress assumes the low end of income and the high end of spending; best the
    reverse; realistic is the middle half of that span. Obligations are always
    included as fixed commitments and are never treated as cuttable.
    """
    if horizon_weeks <= 0:
        raise ValueError("horizon must be positive")
    unknowns: list[str] = []
    used: list[str] = []
    in_lo = in_hi = out_lo = out_hi = Decimal(0)
    for f in flows:
        if f.currency != currency:
            unknowns.append(f"“{f.label}” is in {f.currency}, so it was left out")
            continue
        factor = WEEKS_PER.get(f.frequency)
        if factor is None:
            unknowns.append(f"“{f.label}” is {f.frequency.replace('_', ' ')}, so it has no weekly amount")
            continue
        lo, hi = min(f.amount_min, f.amount_max) * factor, max(f.amount_min, f.amount_max) * factor
        used.append(f.label)
        if f.direction == "in":
            in_lo, in_hi = in_lo + lo, in_hi + hi
        else:
            out_lo, out_hi = out_lo + lo, out_hi + hi
    weekly_lo = in_lo - out_hi
    weekly_hi = in_hi - out_lo
    span = weekly_hi - weekly_lo
    h = Decimal(horizon_weeks)
    q1 = weekly_lo + span / 4
    q3 = weekly_lo + span * 3 / 4
    cases = [
        {
            "name": "best",
            "assumptions": ["Income near the top of your range", "Spending near the bottom of your range"],
            "outcome_range": [num(q3 * h), num(weekly_hi * h)],
            "what_would_have_to_be_true": "Most weeks go well on both sides at once",
        },
        {
            "name": "realistic",
            "assumptions": ["Income and spending land in the middle of your ranges"],
            "outcome_range": [num(q1 * h), num(q3 * h)],
            "what_would_have_to_be_true": "An ordinary mix of good and slow weeks",
        },
        {
            "name": "stress",
            "assumptions": ["Income near the bottom of your range", "Spending near the top, obligations unchanged"],
            "outcome_range": [num(weekly_lo * h), num(q1 * h)],
            "what_would_have_to_be_true": "Several slow weeks in a row",
        },
    ]
    if "daily" in {f.frequency for f in flows}:
        unknowns.append("Daily amounts were counted for all 7 days of the week")
    return {
        "kind": "cash_flow",
        "premise": premise,
        "currency": currency,
        "horizon_weeks": horizon_weeks,
        "weekly_net_range": [num(weekly_lo), num(weekly_hi)],
        "cases": cases,
        "flows_used": used,
        "context_used": [],
        "unknowns": unknowns,
        "not_advice_note": True,
    }


def validate_scenario(result: dict[str, Any]) -> list[str]:
    """Output check (Section 11): three named cases, assumptions, ordered ranges."""
    problems: list[str] = []
    cases = {c.get("name"): c for c in result.get("cases", [])}
    if set(cases) != set(CASE_ORDER):
        problems.append("scenario must have best, realistic and stress cases")
        return problems
    for c in cases.values():
        if not c.get("assumptions"):
            problems.append(f"{c['name']} case has no assumptions")
        lo, hi = c["outcome_range"]
        if lo > hi:
            problems.append(f"{c['name']} range is inverted")
    s, r, b = (cases[n]["outcome_range"] for n in ("stress", "realistic", "best"))
    if not (s[0] <= r[0] <= b[0] and s[1] <= r[1] <= b[1]):
        problems.append("ranges are not ordered stress <= realistic <= best")
    if result.get("not_advice_note") is not True:
        problems.append("missing not-advice note")
    return problems


def numbers_in(obj: Any) -> set[Decimal]:
    """Every number that appears anywhere in a JSON-like object (for the
    "no invented numbers" check)."""
    out: set[Decimal] = set()
    if isinstance(obj, bool):
        return out
    if isinstance(obj, int | float | Decimal):
        out.add(money(Decimal(str(obj))))
    elif isinstance(obj, dict):
        for v in obj.values():
            out |= numbers_in(v)
    elif isinstance(obj, list | tuple):
        for v in obj:
            out |= numbers_in(v)
    elif isinstance(obj, str):
        from app.safety.output_checks import extract_numbers

        out |= extract_numbers(obj)
    return out
