"""Safety screen: the FIRST node of every agent turn (Section 11).

Deliberately simple, code-based pattern matching so it works even when the
model is down. The router can also raise safety_escalation as a second layer.
"""

import re
from dataclasses import dataclass, field

CRISIS = [
    r"\bkill(ing)? myself\b",
    r"\bend(ing)? (my|it all|my own) li(fe|ves)\b",
    r"\bsuicid",
    r"\bwant to die\b",
    r"\bdon'?t want to (live|be alive|wake up)\b",
    r"\bself[- ]?harm",
    r"\bhurt(ing)? myself\b",
    r"\bcut(ting)? myself\b",
    r"\bno reason to live\b",
    r"\bbetter off dead\b",
    r"\bend it all\b",
    r"\bkujiua\b",
    r"\bnataka kufa\b",
    r"\btake my (own )?life\b",
    r"\boverdose\b",
]
FINANCIAL_DISTRESS = [
    r"\b(can'?t|cannot|can not) afford (food|to eat|rent)\b",
    r"\bno (money for )?food\b",
    r"\bhaven'?t eaten\b",
    r"\bnothing to eat\b",
    r"\bloan shark",
    r"\bdebt collectors?\b.*\b(threat|hurt|beat)",
    r"\b(lender|lenders|shylock)s?\b.*\b(threat|threaten|hurt|beat|harass)",
    r"\bthreaten\w*\b.*\b(loan|debt|lender)",
    r"\bbeing evicted\b",
    r"\beviction\b",
]
MINOR = [
    r"\b(i am|i'?m)\s+(1[0-7]|[6-9])\s*(years?[- ]old|yrs?\b|yo\b|y/o)",
    r"\b(i am|i'?m) a (1[0-7]|[6-9])[- ]year[- ]old\b",
    r"\bmy age is (1[0-7]|[6-9])\b",
    r"\bi'?m in (form [1-4]|grade [1-9]|high school|primary school|middle school)\b",
]
PROFESSIONAL = {
    "medical": [r"\bdiagnos", r"\bmedication\b", r"\bdosage\b", r"\bprescri", r"\bsymptoms?\b"],
    "legal": [r"\blawyer\b", r"\bsue\b", r"\blawsuit\b", r"\bcourt\b", r"\blegal(ly)?\b"],
    "investment": [r"\bwhich (stock|share|coin)s?\b", r"\bshould i (buy|invest)\b", r"\bcrypto\b", r"\bforex\b"],
}
RELIANCE = [
    r"\byou'?re my only (friend|one)\b",
    r"\bonly (one|person) i (talk|can talk) to\b",
    r"\byou'?re all i have\b",
    r"\bdon'?t need anyone else\b",
    r"\bi only talk to you\b",
    r"\bbetter than (real )?people\b",
]


def _any(patterns: list[str], text: str) -> bool:
    return any(re.search(p, text, re.IGNORECASE) for p in patterns)


@dataclass
class ScreenResult:
    crisis: bool = False
    financial_distress: bool = False
    possible_minor: bool = False
    professional: list[str] = field(default_factory=list)
    reliance: bool = False

    @property
    def stop_coaching(self) -> bool:
        return self.crisis or self.financial_distress


def screen(text: str) -> ScreenResult:
    return ScreenResult(
        crisis=_any(CRISIS, text),
        financial_distress=_any(FINANCIAL_DISTRESS, text),
        possible_minor=_any(MINOR, text),
        professional=[k for k, pats in PROFESSIONAL.items() if _any(pats, text)],
        reliance=_any(RELIANCE, text),
    )
