from decimal import Decimal

from app.agents.graph import explicit_commitment
from app.safety import output_checks as oc
from app.safety.screens import screen

WHAT_IFS = [
    "What if I set aside KES 300 a week for 12 weeks?",
    "Should I start walking in the mornings?",
    "Maybe I could save a bit from each sale?",
    "I'm thinking about a habit of reading before bed",
    "How much would I have if I saved 200 a month for a year?",
    "Would it help to go to the gym twice a week?",
    "Hypothetically, if I skipped lunch out, what changes?",
    "I'm wondering whether to join a second chama",
    "Not sure if I should pay the loan faster",
    "Imagine I walked every day, what would that look like?",
]
COMMITMENTS = [
    "Remind me to walk on Monday, Wednesday and Friday at 6:30",
    "Make this my goal",
    "Log that I walked today",
    "Set this as my goal please",
    "Create a habit: read 10 pages",
    "Add my rent: 15000 a month",
    "Save this to my journal: today was heavy",
    "Set a reminder for my chama on the 1st",
    "Track this for me",
    "Please log my walk",
]


def test_commitment_boundary_regex() -> None:
    assert [m for m in WHAT_IFS if explicit_commitment(m)] == []
    assert [m for m in COMMITMENTS if not explicit_commitment(m)] == []


def test_crisis_screen() -> None:
    assert screen("I don't want to live anymore").crisis
    assert screen("nataka kufa").crisis
    assert not screen("I'm dying to try that new cafe").crisis
    assert screen("I can't afford food this week").financial_distress
    assert screen("the lender threatened me").financial_distress


def test_minor_screen() -> None:
    assert screen("I'm 15 years old").possible_minor
    assert screen("i am a 16-year-old student").possible_minor
    assert not screen("I'm 15 minutes late").possible_minor
    assert not screen("I'm 25 years old").possible_minor


def test_directive_and_generic_phrases() -> None:
    assert oc.directive_phrases("You should save more. I recommend a budget.")
    assert not oc.directive_phrases("One option is to save more; another is to wait.")
    assert oc.generic_advice("Try to save 20% of your income")
    assert oc.generic_advice("It takes 21 days to build a habit")
    assert oc.needy_language("I missed you!")


def test_unsupported_numbers() -> None:
    allowed = {Decimal("2400.00"), Decimal("3000.00")}
    assert oc.unsupported_numbers("Between 2,400 and 3,000.", allowed) == []
    assert oc.unsupported_numbers("Maybe 9,999 by March", allowed) == [Decimal("9999.00")]
    assert oc.unsupported_numbers("Try 3 times a week", allowed) == []  # counting numbers are fine


def test_crisis_reply_never_invents_numbers_for_unverified_country() -> None:
    # Shipped entries are unverified (verified_on: null), so no numbers may show.
    text, cards = oc.crisis_reply("KE")
    assert cards == []
    assert "emergency services" in text
    assert not any(ch.isdigit() for ch in text)
    text2, cards2 = oc.crisis_reply("ZZ")
    assert cards2 == [] and "won't guess" in text2
