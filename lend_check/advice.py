"""Practical advice for the verdict.

The rules in assessment.py decide the verdict and the safe amount. Claude only
turns that into a short, friendly suggestion. Without an ANTHROPIC_API_KEY,
or if a call fails, a template built from the same result is used instead.
"""

import json
import os
from dataclasses import dataclass
from functools import lru_cache

import anthropic

from .assessment import Result

DEFAULT_MODEL = "claude-opus-5-5"
_SERVER_FALLBACK_MODELS = {"claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5"}

SYSTEM_PROMPT = """\
You help someone decide whether to lend money to a friend. You receive the result \
of a simple rules-based check as JSON: a verdict, a 0-100 score, the amount asked \
for, a suggested safe amount, how much the lender could afford to lose, and the \
strengths and concerns behind the verdict.

The verdict and safe amount are already decided. Write two or three warm, practical \
sentences that:
- go with the verdict and never suggest lending more than the safe amount
- give one or two concrete steps, such as agreeing a repayment date in writing, \
lending a smaller amount first, or helping in another way
- talk about the situation, not the friend's character, and don't lecture
- never mention age, sex, ethnicity, religion, nationality, disability or any other \
personal characteristic

Use pounds (£). Return only the advice."""


@dataclass(frozen=True)
class Advice:
    text: str
    source: str  # "ai" or "template"
    note: str = ""


def money(value: float) -> str:
    return f"£{value:,.0f}" if float(value).is_integer() else f"£{value:,.2f}"


def ai_available() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def model_name() -> str:
    return os.environ.get("LEND_CHECK_MODEL", DEFAULT_MODEL)


_client = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(timeout=20.0, max_retries=2)
    return _client


def template_advice(result: Result) -> str:
    if result.knocked_out:
        return (
            "They still owe money from before, so it's worth asking for that to be "
            "settled before lending more."
        )
    over_budget = (
        f" Keep it within the {money(result.affordable_loss)} you could afford to lose."
        if result.amount > result.affordable_loss
        else ""
    )
    if result.verdict == "Lend":
        if result.safe_amount < result.amount:
            return (
                f"This looks like a reasonable loan, but consider {money(result.safe_amount)} "
                f"rather than {money(result.amount)}.{over_budget} Agree a repayment date "
                "and put it in a message so you both remember."
            )
        return (
            f"Lending {money(result.amount)} looks reasonable. Agree a repayment date "
            "together and put it in a message so you both remember."
        )
    if result.verdict == "Lend with care":
        return (
            f"Consider lending {money(result.safe_amount)} rather than {money(result.amount)}, "
            f"and agree a clear repayment date in writing.{over_budget}"
        )
    return (
        f"Think carefully before lending. If you do, keep it to around "
        f"{money(result.safe_amount)}, or look for another way to help."
    )


def advice_payload(result: Result) -> dict:
    return {
        "verdict": result.verdict,
        "score": result.score,
        "amount_requested": result.amount,
        "safe_amount": result.safe_amount,
        "affordable_loss": result.affordable_loss,
        "still_owes_money_from_before": result.knocked_out,
        "strengths": list(result.strengths),
        "concerns": list(result.concerns),
    }


@lru_cache(maxsize=512)
def _ai_text(model: str, payload: str) -> str | None:
    params = {
        "model": model,
        "max_tokens": 4096,
        "system": SYSTEM_PROMPT,
        "output_config": {"effort": "low"},
        "messages": [{"role": "user", "content": payload}],
    }
    if model in _SERVER_FALLBACK_MODELS:
        params["betas"] = ["server-side-fallback-2026-07-01"]
        params["fallbacks"] = "default"

    response = _get_client().beta.messages.create(**params)
    if response.stop_reason in ("refusal", "max_tokens"):
        return None
    text = "".join(block.text for block in response.content if block.type == "text").strip()
    return text or None


def get_advice(result: Result, use_ai: bool = True) -> Advice:
    template = template_advice(result)
    if not use_ai:
        return Advice(template, "template", "AI advice is switched off")
    if not ai_available():
        return Advice(template, "template", "no ANTHROPIC_API_KEY is set")

    payload = json.dumps(advice_payload(result), sort_keys=True)
    try:
        text = _ai_text(model_name(), payload)
    except anthropic.AuthenticationError:
        note = "the API key was rejected"
    except anthropic.RateLimitError:
        note = "the API rate limit was reached"
    except anthropic.APIStatusError as exc:
        note = f"the API returned an error ({exc.status_code})"
    except anthropic.APIConnectionError:
        note = "the API could not be reached"
    else:
        if text:
            return Advice(text, "ai")
        note = "the model returned no advice"
    return Advice(template, "template", note)
