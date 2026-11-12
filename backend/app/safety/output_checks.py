"""Output checks: the LAST node of every agent turn. Code, not model (Section 11)."""

import re
from decimal import Decimal, InvalidOperation
from typing import Any

from app.safety.resources import resources_for

DIRECTIVE_PHRASES = [
    r"\byou should\b",
    r"\byou must\b",
    r"\bthe best option is\b",
    r"\bi recommend\b",
    r"\bi'd recommend\b",
    r"\bi would recommend\b",
    r"\bmy recommendation\b",
    r"\byou need to\b",
    r"\byou have to\b",
    r"\bthe right choice is\b",
    r"\bdefinitely (do|go with|take)\b",
]
GENERIC_ADVICE = [
    r"\bsave 20 ?%",
    r"\b21 days\b",
    r"\bcut (out )?(your )?(daily )?(coffee|latte)",
    r"\b50/30/20\b",
    r"\bpay yourself first\b",
    r"\bemergency fund of (3|three|6|six) months\b",
    r"\bjust stay positive\b",
]
NEEDY_LANGUAGE = [
    r"\bi missed you\b",
    r"\bi'?ve been waiting for you\b",
    r"\bi need you\b",
    r"\bdon'?t leave me\b",
    r"\byou haven'?t (talked|spoken|checked in)\b",
]
REFERRAL_TOPICS = [
    r"\bloan\b",
    r"\binterest\b",
    r"\bcontract\b",
    r"\btax(es)?\b",
    r"\binsurance\b",
    r"\bmortgage\b",
    r"\bcredit\b",
]

_NUM = re.compile(r"(?<![\w.])(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d+))?(?![\w])")


def find(patterns: list[str], text: str) -> list[str]:
    hits = []
    for p in patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            hits.append(m.group(0))
    return hits


def directive_phrases(text: str) -> list[str]:
    return find(DIRECTIVE_PHRASES, text)


def generic_advice(text: str) -> list[str]:
    return find(GENERIC_ADVICE, text)


def needy_language(text: str) -> list[str]:
    return find(NEEDY_LANGUAGE, text)


def needs_referral(text: str) -> bool:
    return bool(find(REFERRAL_TOPICS, text))


def extract_numbers(text: str) -> set[Decimal]:
    out: set[Decimal] = set()
    for m in _NUM.finditer(text):
        whole = m.group(1).replace(",", "")
        frac = m.group(2)
        try:
            out.add(Decimal(f"{whole}.{frac}" if frac else whole).quantize(Decimal("0.01")))
        except InvalidOperation:
            continue
    return out


# Small counting numbers ("2 options", "3 cases", "7 days") are not money claims.
_TRIVIAL = {Decimal(i).quantize(Decimal("0.01")) for i in range(0, 13)}


def unsupported_numbers(reply: str, allowed: set[Decimal]) -> list[Decimal]:
    """Numbers in the reply that are not in the computed scenario or the
    person's own data. Any hit means the model invented a figure."""
    return sorted(n for n in extract_numbers(reply) if n not in allowed and n not in _TRIVIAL)


def crisis_reply(country: str | None) -> tuple[str, list[dict[str, Any]]]:
    res = resources_for(country)
    lines = [
        "I'm really glad you told me. What you're feeling matters, and you don't have to carry it alone.",
        "I'm going to pause everything else. Please reach out to someone you trust right now — a friend, "
        "family member, or someone nearby — and let them know how you're feeling.",
    ]
    cards: list[dict[str, Any]] = []
    if res:
        for c in res.get("crisis", []):
            cards.append({"name": c["name"], "contact": c["contact"]})
        if res.get("emergency"):
            cards.append({"name": "Emergency services", "contact": " / ".join(res["emergency"])})
        lines.append("These services can talk with you now:")
    else:
        lines.append(
            "I don't have a checked list of support lines for where you are, so I won't guess a number. "
            "If you might be in danger, please contact your local emergency services now."
        )
    lines.append("I'm here if you want to keep talking, but a person who can be with you matters most right now.")
    return "\n\n".join(lines), cards


def financial_distress_reply(country: str | None) -> tuple[str, list[dict[str, Any]]]:
    res = resources_for(country)
    lines = [
        "That sounds really hard, and I'm sorry you're dealing with it. Let's set planning aside for now.",
    ]
    cards: list[dict[str, Any]] = []
    if res and res.get("financial"):
        cards = [{"name": c["name"], "contact": c["contact"]} for c in res["financial"]]
        lines.append("These local services may be able to help:")
    else:
        lines.append(
            "I don't have checked local support services for your area yet. Someone you trust, a community or "
            "faith group, or local social services may be able to help with food or with threats from lenders. "
            "If anyone threatens your safety, contact your local emergency services."
        )
    lines.append("If and when you want, we can look at the next few days together — only if that would help.")
    return "\n\n".join(lines), cards


def referral_note(country: str | None) -> str:
    res = resources_for(country)
    base = (
        "For anything involving loan terms, interest, contracts, tax or insurance, a licensed financial adviser "
        "or a free advice service can look at your actual documents."
    )
    if res and res.get("financial"):
        names = ", ".join(c["name"] for c in res["financial"])
        return f"{base} Near you: {names}."
    return base
