import pytest

from lend_check.assessment import QUESTIONS, assess, verdict_for

BEST = {q.key: q.options[0].label for q in QUESTIONS}
WORST = {
    "repayment": "They've never borrowed before",
    "reliability": "Very unreliable",
    "money_habits": "Spends on impulse, rarely saves",
    "income": "Between jobs",
    "borrowing": "Owes several people right now",
    "purpose": "They haven't said",
    "size": "More than a month's pay",
}


def answers(**overrides):
    return {**BEST, **overrides}


def test_points_add_up_to_100():
    assert sum(q.max_points for q in QUESTIONS) == 100


def test_best_friend_scores_100_and_lend():
    result = assess(BEST, amount=200, affordable_loss=500)
    assert result.score == 100
    assert result.verdict == "Lend"
    assert result.concerns == ()
    assert result.safe_amount == 200


def test_worst_answers_think_twice():
    result = assess(WORST, amount=200, affordable_loss=500)
    assert result.score == 16
    assert result.verdict == "Think twice"
    assert "Very unreliable" in result.concerns


@pytest.mark.parametrize(
    ("score", "verdict"),
    [
        (100, "Lend"),
        (70, "Lend"),
        (69, "Lend with care"),
        (45, "Lend with care"),
        (44, "Think twice"),
    ],
)
def test_verdict_cutoffs(score, verdict):
    assert verdict_for(score) == verdict


def test_unpaid_debt_overrides_a_high_score():
    result = assess(answers(repayment="They still owe money from before"), 100, 500)
    assert result.score == 75
    assert result.verdict == "Think twice"
    assert result.knocked_out
    assert result.safe_amount == 0
    assert "Still owes money from before" in result.concerns


def test_strengths_and_concerns_follow_answers():
    result = assess(answers(money_habits="Often runs out before payday"), 100, 500)
    assert "Careful with money" not in result.strengths
    assert "Often runs out of money before payday" in result.concerns
    assert "Has always paid back on time" in result.strengths


def test_middle_answers_are_neither_strength_nor_concern():
    result = assess(answers(reliability="Sometimes"), 100, 500)
    assert "Only sometimes reliable" not in result.strengths
    assert "Only sometimes reliable" not in result.concerns


def test_amount_above_affordable_loss_is_flagged_and_capped():
    result = assess(BEST, amount=1_000, affordable_loss=300)
    assert "It's more than you said you could afford to lose" in result.concerns
    assert result.safe_amount == 300


@pytest.mark.parametrize(
    ("overrides", "verdict", "safe"),
    [
        ({}, "Lend", 400),
        (
            {
                "reliability": "Sometimes",
                "money_habits": "A mix of good and bad",
                "purpose": "An emergency (rent, bills, medical)",
                "size": "Up to a month's pay",
                "income": "Student or part-time",
            },  # 25 + 7 + 7 + 6 + 10 + 6 + 6 = 67
            "Lend with care",
            200,
        ),
    ],
)
def test_safe_amount_shrinks_with_the_verdict(overrides, verdict, safe):
    result = assess(answers(**overrides), amount=400, affordable_loss=1_000)
    assert result.verdict == verdict
    assert result.safe_amount == safe


def test_think_twice_suggests_a_quarter_rounded_down():
    result = assess(WORST, amount=450, affordable_loss=1_000)
    assert result.safe_amount == 110  # 112.5 rounded down to the nearest 10


def test_small_amounts_round_to_whole_pounds():
    result = assess(WORST, amount=30, affordable_loss=30)
    assert result.safe_amount == 7


@pytest.mark.parametrize(
    ("amount", "loss", "message"),
    [(0, 100, "more than zero"), (-5, 100, "more than zero"), (100, -1, "can't be negative")],
)
def test_invalid_amounts_rejected(amount, loss, message):
    with pytest.raises(ValueError, match=message):
        assess(BEST, amount, loss)


def test_missing_answer_rejected():
    partial = {k: v for k, v in BEST.items() if k != "income"}
    with pytest.raises(ValueError, match="Missing answers: Income"):
        assess(partial, 100, 100)


def test_unknown_answer_rejected():
    with pytest.raises(ValueError, match="is not an answer"):
        assess(answers(income="Lottery winner"), 100, 100)
