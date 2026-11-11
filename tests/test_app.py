"""Drive the Streamlit app headlessly, the way a visitor would."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from lend_check.assessment import QUESTIONS

APP = str(Path(__file__).parent.parent / "streamlit_app.py")
BEST = {q.key: q.options[0].label for q in QUESTIONS}


@pytest.fixture
def app(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: None)
    return AppTest.from_file(APP, default_timeout=60).run()


def answer(app, **overrides):
    for key, label in {**BEST, **overrides}.items():
        app.radio(key=key).set_value(label)
    return app.run()


def suggested(app):
    return next(m.value for m in app.metric if m.label == "Suggested amount")


def test_asks_for_all_answers_first(app):
    assert not app.exception
    assert "0 of 7 done" in app.info[0].value
    assert not app.metric


def test_partial_answers_show_progress(app):
    app.radio(key="repayment").set_value("Yes, always on time").run()
    assert "1 of 7 done" in app.info[0].value


def test_good_friend_gets_lend(app):
    answer(app)
    assert any("Lend]" in m.value and "with care" not in m.value for m in app.markdown)
    assert suggested(app) == "£200"


def test_unpaid_debt_means_think_twice(app):
    answer(app, repayment="They still owe money from before")
    assert any("Think twice" in m.value for m in app.markdown)
    assert suggested(app) == "£0"
    assert any("settled before lending more" in m.value for m in app.markdown)


def test_suggested_amount_capped_by_what_you_can_lose(app):
    app.number_input(key="amount").set_value(1_000)
    app.number_input(key="affordable_loss").set_value(250)
    answer(app)
    assert suggested(app) == "£250"
    assert any("more than you said you could afford to lose" in m.value for m in app.markdown)


def test_no_claude_button_without_api_key(app):
    answer(app)
    assert not [b for b in app.button if "Claude" in b.label]
