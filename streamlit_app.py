"""Should I lend to my friend? Run with: streamlit run streamlit_app.py"""

import datetime as dt
import json
import os

import streamlit as st
from dotenv import load_dotenv
from streamlit.errors import StreamlitSecretNotFoundError

from lend_check import advice
from lend_check.assessment import CARE_MIN, LEND_MIN, QUESTIONS, assess

SESSION_AI_LIMIT = 10
DAILY_AI_LIMIT = 200
VERDICT_STYLE = {
    "Lend": ("green", ":material/check_circle:"),
    "Lend with care": ("orange", ":material/warning:"),
    "Think twice": ("red", ":material/do_not_disturb_on:"),
}


def configure_api_key() -> None:
    load_dotenv()
    try:
        key = st.secrets.get("ANTHROPIC_API_KEY")
    except StreamlitSecretNotFoundError:
        key = None
    if key:
        os.environ.setdefault("ANTHROPIC_API_KEY", key)


@st.cache_resource
def daily_ai_usage() -> dict:
    return {"date": dt.date.today(), "count": 0}


def ai_budget_left() -> int:
    usage = daily_ai_usage()
    if usage["date"] != dt.date.today():
        usage.update(date=dt.date.today(), count=0)
    session_left = SESSION_AI_LIMIT - st.session_state.ai_calls
    return max(0, min(session_left, DAILY_AI_LIMIT - usage["count"]))


def questions() -> dict:
    answers = {}
    for number, q in enumerate(QUESTIONS, start=1):
        with st.container(border=True):
            choice = st.radio(
                f"**{number}. {q.title}.** {q.prompt}",
                [o.label for o in q.options],
                index=None,
                key=q.key,
            )
        if choice is not None:
            answers[q.key] = choice
    return answers


def amounts() -> tuple:
    left, right = st.columns(2)
    amount = left.number_input(
        "How much do they want to borrow? (£)", min_value=1, value=200, step=10, key="amount"
    )
    loss = right.number_input(
        "How much could you afford to lose? (£)",
        min_value=0,
        value=200,
        step=10,
        key="affordable_loss",
        help="If the money never came back, how much could you cope without? "
        "A good rule is never to lend more than this.",
    )
    return amount, loss


def advice_panel(result) -> None:
    st.subheader("What to do")
    payload_key = json.dumps(advice.advice_payload(result), sort_keys=True)
    ai_text = st.session_state.ai_texts.get(payload_key)
    if ai_text:
        st.info(ai_text, icon=":material/auto_awesome:")
        st.caption(
            f"Written by Claude ({advice.model_name()}) from the result above. "
            "The verdict and amount come from the rules, not from the AI."
        )
        return

    st.write(advice.template_advice(result))
    if not advice.ai_available():
        return
    budget = ai_budget_left()
    if st.button(
        "Get friendlier advice from Claude",
        icon=":material/auto_awesome:",
        disabled=budget == 0,
    ):
        with st.spinner("Asking Claude…"):
            got = advice.get_advice(result)
        if got.source == "ai":
            st.session_state.ai_calls += 1
            daily_ai_usage()["count"] += 1
            st.session_state.ai_texts[payload_key] = got.text
            st.rerun()
        st.warning(f"Showing the standard advice instead: {got.note}.")
    if budget == 0:
        st.caption("The limit for Claude advice has been reached for now.")


def show_result(result) -> None:
    color, icon = VERDICT_STYLE[result.verdict]
    verdict_col, amount_col = st.columns(2)
    with verdict_col:
        st.caption("Verdict")
        st.badge(result.verdict, icon=icon, color=color)
        st.progress(result.score / 100, text=f"Score {result.score} / 100")
    amount_col.metric(
        "Suggested amount",
        advice.money(result.safe_amount),
        help="Never more than you can afford to lose, and less when the verdict is cautious.",
    )

    good, bad = st.columns(2)
    with good:
        st.markdown("**In their favour**")
        for item in result.strengths:
            st.markdown(f":green[:material/check:] {item}")
        if not result.strengths:
            st.caption("Nothing stood out")
    with bad:
        st.markdown("**Worth thinking about**")
        for item in result.concerns:
            st.markdown(f":orange[:material/priority_high:] {item}")
        if not result.concerns:
            st.caption("Nothing stood out")

    advice_panel(result)


def how_it_works() -> None:
    with st.expander("How the score works"):
        st.write(
            f"Each answer earns points; the seven questions add up to 100. {LEND_MIN}+ is "
            f"**Lend**, {CARE_MIN}–{LEND_MIN - 1} is **Lend with care**, and below "
            f"{CARE_MIN} is **Think twice**. If they still owe money from before, the "
            "verdict is Think twice whatever the score."
        )
        st.dataframe(
            [{"Question": q.title, "Max points": q.max_points} for q in QUESTIONS],
            hide_index=True,
        )
        st.write(
            "Repayment history carries the most weight because past repayment is the best "
            "guide to future repayment. It's the same idea lenders use, built on things "
            "you already know about your friend instead of a credit file."
        )


def main() -> None:
    st.set_page_config(page_title="Should I lend to my friend?", page_icon=":material/handshake:")
    configure_api_key()
    st.session_state.setdefault("ai_calls", 0)
    st.session_state.setdefault("ai_texts", {})

    st.title("Should I lend to my friend?")
    st.caption(
        "Seven quick questions about things you already know. No bank statements or "
        "credit scores needed, and nothing you enter is stored."
    )

    amount, loss = amounts()
    answers = questions()

    st.divider()
    if len(answers) < len(QUESTIONS):
        st.info(
            f"Answer all {len(QUESTIONS)} questions to see the result "
            f"({len(answers)} of {len(QUESTIONS)} done).",
            icon=":material/checklist:",
        )
    else:
        show_result(assess(answers, amount, loss))

    how_it_works()
    st.caption("A rough guide to help you think it through, not financial advice.")


main()
