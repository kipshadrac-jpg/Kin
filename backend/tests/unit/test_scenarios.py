from decimal import Decimal

from hypothesis import given
from hypothesis import strategies as st

from app.services.scenarios import (
    CaseChoice,
    FlowIn,
    SetAsideInput,
    compute_cash_flow,
    compute_set_aside,
    numbers_in,
    validate_scenario,
)


def _cases(b=(12, 12), r=(8, 10), s=(4, 6)) -> list[CaseChoice]:
    return [
        CaseChoice(
            name="best", periods_hit_min=b[0], periods_hit_max=b[1], assumptions=["a"], what_would_have_to_be_true="x"
        ),
        CaseChoice(
            name="realistic",
            periods_hit_min=r[0],
            periods_hit_max=r[1],
            assumptions=["b"],
            what_would_have_to_be_true="y",
        ),
        CaseChoice(
            name="stress", periods_hit_min=s[0], periods_hit_max=s[1], assumptions=["c"], what_would_have_to_be_true="z"
        ),
    ]


def test_set_aside_matches_the_mockup_numbers() -> None:
    res = compute_set_aside(
        SetAsideInput(
            premise="p",
            currency="KES",
            amount_per_period=Decimal(300),
            period="week",
            horizon_periods=12,
            cases=_cases(),
        )
    )
    by = {c["name"]: c["outcome_range"] for c in res["cases"]}
    assert by == {"best": [3600, 3600], "realistic": [2400, 3000], "stress": [1200, 1800]}
    assert validate_scenario(res) == []
    assert res["not_advice_note"] is True


def test_misordered_model_choices_are_relabelled() -> None:
    res = compute_set_aside(
        SetAsideInput(
            premise="p",
            currency="KES",
            amount_per_period=Decimal(100),
            period="week",
            horizon_periods=10,
            cases=_cases(b=(1, 2), r=(9, 10), s=(5, 6)),
        )
    )
    by = {c["name"]: c for c in res["cases"]}
    assert by["best"]["outcome_range"] == [900, 1000]
    assert by["best"]["assumptions"] == ["b"]  # wording travels with its numbers
    assert validate_scenario(res) == []


def test_hits_are_clamped_to_horizon() -> None:
    res = compute_set_aside(
        SetAsideInput(
            premise="p",
            currency="USD",
            amount_per_period=Decimal("2.5"),
            period="day",
            horizon_periods=5,
            cases=_cases(b=(99, 120), r=(3, 4), s=(0, 1)),
        )
    )
    assert {c["name"]: c["outcome_range"] for c in res["cases"]}["best"] == [12.5, 12.5]


@given(
    amount=st.decimals(min_value=Decimal("0.01"), max_value=Decimal("100000"), places=2),
    horizon=st.integers(min_value=1, max_value=104),
    hits=st.lists(st.tuples(st.integers(0, 120), st.integers(0, 120)), min_size=3, max_size=3),
)
def test_property_stress_le_realistic_le_best(amount: Decimal, horizon: int, hits: list[tuple[int, int]]) -> None:
    cases = _cases(b=hits[0], r=hits[1], s=hits[2])
    res = compute_set_aside(
        SetAsideInput(
            premise="p", currency="KES", amount_per_period=amount, period="week", horizon_periods=horizon, cases=cases
        )
    )
    assert validate_scenario(res) == []


@given(
    flows=st.lists(
        st.tuples(
            st.sampled_from(["in", "out", "set_aside"]),
            st.integers(0, 50000),
            st.integers(0, 50000),
            st.sampled_from(["daily", "weekly", "monthly", "irregular"]),
        ),
        min_size=1,
        max_size=8,
    ),
    weeks=st.integers(1, 52),
)
def test_property_cash_flow_ordering(flows: list[tuple[str, int, int, str]], weeks: int) -> None:
    fl = [
        FlowIn(
            direction=d,
            label=f"f{i}",
            amount_min=Decimal(min(a, b)),
            amount_max=Decimal(max(a, b)),  # type: ignore[arg-type]
            currency="KES",
            frequency=f,
        )
        for i, (d, a, b, f) in enumerate(flows)
    ]  # type: ignore[arg-type]
    assert validate_scenario(compute_cash_flow(fl, "KES", weeks)) == []


def test_cash_flow_excludes_other_currency_and_irregular() -> None:
    res = compute_cash_flow(
        [
            FlowIn(
                direction="in",
                label="sales",
                amount_min=Decimal(500),
                amount_max=Decimal(1500),
                currency="KES",
                frequency="daily",
            ),
            FlowIn(
                direction="out",
                label="school fees",
                amount_min=Decimal(4000),
                amount_max=Decimal(4000),
                currency="KES",
                frequency="monthly",
                is_obligation=True,
            ),
            FlowIn(
                direction="in",
                label="gift",
                amount_min=Decimal(10),
                amount_max=Decimal(10),
                currency="USD",
                frequency="weekly",
            ),
            FlowIn(
                direction="in",
                label="harvest",
                amount_min=Decimal(1),
                amount_max=Decimal(2),
                currency="KES",
                frequency="seasonal",
            ),
        ],
        "KES",
        4,
    )
    assert res["flows_used"] == ["sales", "school fees"]
    assert len(res["unknowns"]) == 3
    # weekly: in 3500..10500, out 923.08 -> stress = 3500 - 923.08
    assert res["weekly_net_range"] == [2576.92, 9576.92]


def test_numbers_in_reads_nested_values() -> None:
    assert Decimal("2400.00") in numbers_in({"a": [2400, {"b": "about 3,000"}]})
    assert Decimal("3000.00") in numbers_in({"a": [2400, {"b": "about 3,000"}]})
