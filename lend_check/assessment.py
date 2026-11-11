"""Turn seven everyday questions about a friend into a lending verdict.

Each answer carries points (higher means safer to lend). The points add up to
a 0-100 score, which maps to a verdict. One knock-out rule overrides the
score: if they still owe money from before, settle that first.
"""

from dataclasses import dataclass

LEND_MIN = 70
CARE_MIN = 45
VERDICTS = ("Lend", "Lend with care", "Think twice")


@dataclass(frozen=True)
class Option:
    label: str
    points: int
    note: str


@dataclass(frozen=True)
class Question:
    key: str
    title: str
    prompt: str
    options: tuple

    @property
    def max_points(self) -> int:
        return max(o.points for o in self.options)

    def option(self, label: str) -> Option:
        for o in self.options:
            if o.label == label:
                return o
        raise ValueError(f"'{label}' is not an answer to: {self.prompt}")


QUESTIONS = (
    Question(
        "repayment",
        "Repayment history",
        "Have they paid back money they owed before, to you or anyone you know of?",
        (
            Option("Yes, always on time", 25, "Has always paid back on time"),
            Option("Yes, but late", 15, "Paid back before, but late"),
            Option("They've never borrowed before", 12, "No track record of borrowing"),
            Option("They still owe money from before", 0, "Still owes money from before"),
        ),
    ),
    Question(
        "reliability",
        "Reliability",
        "How reliable are they day to day? Do they turn up on time and keep promises?",
        (
            Option("Very reliable", 15, "Very reliable day to day"),
            Option("Mostly reliable", 11, "Mostly reliable"),
            Option("Sometimes", 7, "Only sometimes reliable"),
            Option("Often late or lets people down", 3, "Often late or lets people down"),
            Option("Very unreliable", 0, "Very unreliable"),
        ),
    ),
    Question(
        "money_habits",
        "Money habits",
        "How do they handle money?",
        (
            Option("Careful: budgets and saves", 15, "Careful with money"),
            Option("Fairly sensible", 11, "Fairly sensible with money"),
            Option("A mix of good and bad", 7, "Mixed money habits"),
            Option("Often runs out before payday", 3, "Often runs out of money before payday"),
            Option("Spends on impulse, rarely saves", 0, "Spends on impulse and rarely saves"),
        ),
    ),
    Question(
        "income",
        "Income",
        "What's their work situation?",
        (
            Option("Steady job with a regular salary", 15, "Has a steady income"),
            Option("Self-employed or freelance, regular work", 10, "Has fairly regular income"),
            Option("Student or part-time", 6, "Has a limited income"),
            Option("Between jobs", 2, "Is between jobs"),
        ),
    ),
    Question(
        "borrowing",
        "Other borrowing",
        "How often do they borrow from other people?",
        (
            Option("Rarely or never", 10, "Rarely borrows from others"),
            Option("Occasionally", 6, "Borrows occasionally"),
            Option("Often", 2, "Borrows from people often"),
            Option("Owes several people right now", 0, "Currently owes several people"),
        ),
    ),
    Question(
        "purpose",
        "What it's for",
        "What's the money for?",
        (
            Option(
                "Something planned that helps them (course, tools, deposit)",
                10,
                "Has a clear, planned use for the money",
            ),
            Option("An emergency (rent, bills, medical)", 6, "Needs it for an emergency"),
            Option(
                "Fun or lifestyle (trip, gadget, night out)", 3, "Wants it for lifestyle spending"
            ),
            Option("They haven't said", 0, "Hasn't said what it's for"),
        ),
    ),
    Question(
        "size",
        "Loan size",
        "How big is the loan compared with their monthly income?",
        (
            Option("Less than a week's pay", 10, "Small compared with their income"),
            Option("Up to a month's pay", 6, "Up to a month of their income"),
            Option("More than a month's pay", 2, "Large compared with their income"),
            Option("Not sure", 4, "You're not sure how it compares with their income"),
        ),
    ),
)

KNOCK_OUT = ("repayment", "They still owe money from before")
_SHARE_OF_SAFE_AMOUNT = {"Lend": 1.0, "Lend with care": 0.5, "Think twice": 0.25}


@dataclass(frozen=True)
class Result:
    score: int
    verdict: str
    strengths: tuple
    concerns: tuple
    knocked_out: bool
    amount: float
    affordable_loss: float
    safe_amount: int


def verdict_for(score: int, knocked_out: bool = False) -> str:
    if knocked_out or score < CARE_MIN:
        return "Think twice"
    return "Lend" if score >= LEND_MIN else "Lend with care"


def _round_down(value: float) -> int:
    step = 10 if value >= 50 else 1
    return int(value // step * step)


def assess(answers: dict, amount: float, affordable_loss: float) -> Result:
    """answers maps each question key to the chosen option label."""
    if amount <= 0:
        raise ValueError("The loan amount must be more than zero.")
    if affordable_loss < 0:
        raise ValueError("The amount you could afford to lose can't be negative.")
    missing = [q.title for q in QUESTIONS if q.key not in answers]
    if missing:
        raise ValueError(f"Missing answers: {', '.join(missing)}.")

    strengths, concerns, score = [], [], 0
    for q in QUESTIONS:
        chosen = q.option(answers[q.key])
        score += chosen.points
        share = chosen.points / q.max_points
        if share >= 0.8:
            strengths.append(chosen.note)
        elif share <= 0.4:
            concerns.append(chosen.note)

    if amount > affordable_loss:
        concerns.append("It's more than you said you could afford to lose")

    knocked_out = answers[KNOCK_OUT[0]] == KNOCK_OUT[1]
    verdict = verdict_for(score, knocked_out)

    cap = min(amount, affordable_loss)
    safe = 0 if knocked_out else _round_down(cap * _SHARE_OF_SAFE_AMOUNT[verdict])

    return Result(
        score=score,
        verdict=verdict,
        strengths=tuple(strengths),
        concerns=tuple(concerns),
        knocked_out=knocked_out,
        amount=amount,
        affordable_loss=affordable_loss,
        safe_amount=safe,
    )
