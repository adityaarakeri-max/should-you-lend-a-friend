import json
from types import SimpleNamespace

import anthropic
import httpx2
import pytest

from lend_check import advice
from lend_check.assessment import QUESTIONS, assess

REQUEST = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
BEST = {q.key: q.options[0].label for q in QUESTIONS}
CAREFUL = {
    **BEST,
    "reliability": "Sometimes",
    "money_habits": "A mix of good and bad",
    "income": "Student or part-time",
    "purpose": "An emergency (rent, bills, medical)",
    "size": "Up to a month's pay",
}


class FakeMessages:
    def __init__(self):
        self.calls = []
        self.error = None
        self.response = SimpleNamespace(
            stop_reason="end_turn",
            content=[SimpleNamespace(type="text", text="Lend £200 and agree a date.")],
        )

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.response


@pytest.fixture(autouse=True)
def clear_cache():
    advice._ai_text.cache_clear()
    yield
    advice._ai_text.cache_clear()


@pytest.fixture
def no_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


@pytest.fixture
def fake_api(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.delenv("LEND_CHECK_MODEL", raising=False)
    messages = FakeMessages()
    client = SimpleNamespace(beta=SimpleNamespace(messages=messages))
    monkeypatch.setattr(advice, "_get_client", lambda: client)
    return messages


@pytest.mark.parametrize(("value", "text"), [(200, "£200"), (1500, "£1,500"), (12.5, "£12.50")])
def test_money_format(value, text):
    assert advice.money(value) == text


def test_template_for_lend(no_key):
    result = assess(BEST, 200, 500)
    got = advice.get_advice(result)
    assert got.source == "template"
    assert got.text.startswith("Lending £200 looks reasonable.")


def test_template_for_lend_over_budget(no_key):
    got = advice.get_advice(assess(BEST, 800, 300))
    assert "consider £300 rather than £800" in got.text
    assert "£300 you could afford to lose" in got.text


def test_template_for_lend_with_care(no_key):
    got = advice.get_advice(assess(CAREFUL, 400, 1_000))
    assert got.text.startswith("Consider lending £200 rather than £400")


def test_template_for_unpaid_debt(no_key):
    result = assess({**BEST, "repayment": "They still owe money from before"}, 100, 500)
    assert "settled before lending more" in advice.get_advice(result).text


def test_template_for_think_twice(no_key):
    worst = {q.key: q.options[-1].label for q in QUESTIONS}
    worst["repayment"] = "They've never borrowed before"
    got = advice.get_advice(assess(worst, 400, 1_000))
    assert "keep it to around £100" in got.text


def test_ai_advice_and_request_shape(fake_api):
    got = advice.get_advice(assess(BEST, 200, 500))
    assert got == advice.Advice("Lend £200 and agree a date.", "ai")
    call = fake_api.calls[0]
    assert call["model"] == "claude-opus-5-5"
    assert call["fallbacks"] == "default"
    assert call["output_config"] == {"effort": "low"}
    payload = json.loads(call["messages"][0]["content"])
    assert payload["verdict"] == "Lend"
    assert payload["safe_amount"] == 200


def test_prompt_keeps_ai_inside_the_verdict():
    assert "never suggest lending more than the safe amount" in advice.SYSTEM_PROMPT
    assert "personal characteristic" in advice.SYSTEM_PROMPT


def test_identical_requests_are_cached(fake_api):
    result = assess(BEST, 200, 500)
    advice.get_advice(result)
    advice.get_advice(result)
    assert len(fake_api.calls) == 1


def test_switched_off(fake_api):
    got = advice.get_advice(assess(BEST, 200, 500), use_ai=False)
    assert got.source == "template"
    assert fake_api.calls == []


@pytest.mark.parametrize(
    ("error", "note"),
    [
        (
            anthropic.RateLimitError(
                "x", response=httpx2.Response(429, request=REQUEST), body=None
            ),
            "the API rate limit was reached",
        ),
        (anthropic.APIConnectionError(request=REQUEST), "the API could not be reached"),
    ],
)
def test_failures_fall_back_to_template(fake_api, error, note):
    fake_api.error = error
    got = advice.get_advice(assess(BEST, 200, 500))
    assert got.source == "template"
    assert got.note == note


def test_refusal_falls_back(fake_api):
    fake_api.response = SimpleNamespace(stop_reason="refusal", content=[])
    assert advice.get_advice(assess(BEST, 200, 500)).source == "template"
