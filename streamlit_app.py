"""
streamlit_app.py
----------------
Chat UI for InsightAgent. Ask a business question in plain English; the agent
queries the warehouse and returns a narrative answer, a chart, the exact SQL it
ran (for trust), and the underlying rows. Thumbs up/down are logged to
feedback.jsonl as a simple closed-loop feedback mechanism.

Run locally:
    streamlit run streamlit_app.py
"""

from __future__ import annotations

import json
import os
import time

import streamlit as st
from dotenv import load_dotenv

from app import charting, config, database
from app.agent import ask
from app.semantic_layer import load_metrics

load_dotenv()

st.set_page_config(page_title="InsightAgent · Talk to your data", page_icon="📊", layout="wide")


# --------------------------------------------------------------------------- #
# Custom dark + teal theme
# --------------------------------------------------------------------------- #
def _inject_css() -> None:
    st.markdown(
        """
        <style>
        :root {
            --teal: #2dd4bf;
            --teal-soft: rgba(45, 212, 191, 0.12);
            --bg: #0a0f14;
            --panel: #121a22;
        }
        .stApp {
            background:
                radial-gradient(1200px 600px at 12% -10%, rgba(45,212,191,0.10), transparent 60%),
                radial-gradient(1000px 500px at 110% 0%, rgba(45,212,191,0.06), transparent 55%),
                var(--bg);
        }
        /* Headings get a subtle teal gradient */
        h1 {
            background: linear-gradient(90deg, #e6f1ef 0%, var(--teal) 90%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            font-weight: 800 !important;
            letter-spacing: -0.5px;
        }
        /* Sidebar panel with teal left border */
        section[data-testid="stSidebar"] {
            background: var(--panel);
            border-right: 1px solid rgba(45,212,191,0.25);
        }
        /* Buttons: ghost style with teal hover */
        .stButton > button {
            background: transparent;
            border: 1px solid rgba(45,212,191,0.35);
            color: #e6f1ef;
            border-radius: 10px;
            transition: all 0.15s ease;
            text-align: left;
        }
        .stButton > button:hover {
            background: var(--teal-soft);
            border-color: var(--teal);
            color: var(--teal);
        }
        /* Chat bubbles + expanders on the panel color */
        .stChatMessage, div[data-testid="stExpander"] {
            background: var(--panel);
            border: 1px solid rgba(255,255,255,0.05);
            border-radius: 12px;
        }
        /* Chat input glow */
        div[data-testid="stChatInput"] textarea {
            border: 1px solid rgba(45,212,191,0.35) !important;
        }
        /* Links + code accents in teal */
        a { color: var(--teal) !important; }
        code { color: var(--teal) !important; }
        /* Tab + dataframe header accents */
        .stTabs [aria-selected="true"] { color: var(--teal) !important; }
        </style>
        """,
        unsafe_allow_html=True,
    )


_inject_css()

SAMPLE_QUESTIONS = [
    "What is driving involuntary churn?",
    "Compare voluntary and involuntary churn rates by payment method.",
    "How does average streaming engagement differ between churned and active customers?",
    "Which acquisition channel has the highest churn rate?",
    "What is our monthly recurring revenue and active subscriber count?",
    "Show the trend of new signups by month.",
    "What are the most common payment failure reasons?",
]


def _provider_ready() -> tuple[bool, str]:
    if config.LLM_PROVIDER == "openai":
        return bool(os.environ.get("OPENAI_API_KEY")), "OPENAI_API_KEY"
    return bool(os.environ.get("ANTHROPIC_API_KEY")), "ANTHROPIC_API_KEY"


def _log_feedback(question: str, answer: str, vote: str) -> None:
    record = {"ts": time.time(), "question": question, "answer": answer, "vote": vote}
    with open(config.FEEDBACK_LOG, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")


# --------------------------------------------------------------------------- #
# Sidebar
# --------------------------------------------------------------------------- #
with st.sidebar:
    st.markdown("### InsightAgent")
    st.caption("Natural-language analytics over a subscription-streaming warehouse.")
    ready, key_name = _provider_ready()
    st.markdown(f"**Provider:** `{config.LLM_PROVIDER}`")
    st.markdown(f"**Model:** `{config.ANTHROPIC_MODEL if config.LLM_PROVIDER=='anthropic' else config.OPENAI_MODEL}`")
    st.markdown("**API key:** " + ("connected ✅" if ready else f"missing ⚠️ (`{key_name}`)"))
    st.divider()
    st.markdown("**Try a question**")
    for q in SAMPLE_QUESTIONS:
        if st.button(q, key=f"s_{q}", use_container_width=True):
            st.session_state["pending"] = q
    st.divider()
    st.caption("5 tables · 6,000 customers · ~78k payments · ~73k engagement rows")
    st.markdown("**[View source on GitHub](https://github.com/rdeepakvishal/insightagent)**", unsafe_allow_html=True)

# --------------------------------------------------------------------------- #
# Cached loaders for intro + data browser
# --------------------------------------------------------------------------- #
@st.cache_data(show_spinner=False)
def _metrics_meta() -> dict:
    return load_metrics()


@st.cache_data(show_spinner=False)
def _tables() -> list[str]:
    return database.list_tables()


@st.cache_data(show_spinner=False)
def _table_preview(table: str, n: int) -> "object":
    return database.sample_rows(table, n)


# --------------------------------------------------------------------------- #
# Header + onboarding
# --------------------------------------------------------------------------- #
st.title("Talk to your data 📊")
st.markdown(
    "Ask anything about subscribers, payments, engagement, or churn. "
    "The agent writes and runs its own SQL, then explains what it found."
)

meta = _metrics_meta()

with st.container():
    st.markdown(
        f"""
        <div style="
            background: rgba(45,212,191,0.07);
            border: 1px solid rgba(45,212,191,0.25);
            border-radius: 12px;
            padding: 14px 18px;
            margin: 6px 0 4px 0;">
            <span style="color:#2dd4bf; font-weight:700;">What's this data?</span><br>
            {meta.get('domain', '').strip()}
        </div>
        """,
        unsafe_allow_html=True,
    )

col_a, col_b = st.columns(2)
with col_a:
    with st.expander("📖 Metric definitions — read before you ask", expanded=False):
        for m in meta.get("metrics", []):
            st.markdown(f"**{m['name']}** — {m['definition'].strip()}")
        if meta.get("business_rules"):
            st.markdown("**Good to know**")
            for rule in meta["business_rules"]:
                st.markdown(f"- {rule}")

with col_b:
    with st.expander("🔎 Browse the underlying synthetic data", expanded=False):
        tables = _tables()
        if tables:
            tbl = st.selectbox("Table", tables, key="data_browser_table")
            n = st.slider("Rows to preview", 5, 100, 20, step=5, key="data_browser_rows")
            st.dataframe(_table_preview(tbl, n), use_container_width=True)
            st.caption("Synthetic data generated for demo purposes — no real customers.")
        else:
            st.info("No tables found.")

st.divider()

if "history" not in st.session_state:
    st.session_state["history"] = []

# Replay prior turns
for turn in st.session_state["history"]:
    with st.chat_message("user"):
        st.markdown(turn["question"])
    with st.chat_message("assistant"):
        st.markdown(turn["answer"])
        if turn.get("figure") is not None:
            st.plotly_chart(turn["figure"], use_container_width=True, key=f"hist_{turn['id']}")


def handle(question: str) -> None:
    ready, key_name = _provider_ready()
    with st.chat_message("user"):
        st.markdown(question)
    with st.chat_message("assistant"):
        if not ready:
            st.error(f"Set `{key_name}` in your environment or .env file to run the agent.")
            return
        with st.spinner("Thinking, querying, and composing an answer..."):
            try:
                result = ask(question)
            except Exception as e:  # noqa: BLE001
                st.error(f"The agent hit an error: {e}")
                return

        st.markdown(result.answer)

        figure = charting.build_figure(result.result_df, result.chart_spec)
        if figure is not None:
            st.plotly_chart(figure, use_container_width=True, key=f"fig_{len(st.session_state['history'])}")

        if result.sql_log:
            with st.expander(f"SQL the agent ran ({len(result.sql_log)} quer"
                             f"{'y' if len(result.sql_log)==1 else 'ies'})"):
                for i, sql in enumerate(result.sql_log, 1):
                    st.code(sql, language="sql")
        if result.result_df is not None and not result.result_df.empty:
            with st.expander("Result rows"):
                st.dataframe(result.result_df, use_container_width=True)

        c1, c2, _ = st.columns([1, 1, 8])
        if c1.button("👍", key=f"up_{len(st.session_state['history'])}"):
            _log_feedback(question, result.answer, "up")
            st.toast("Thanks, logged.")
        if c2.button("👎", key=f"down_{len(st.session_state['history'])}"):
            _log_feedback(question, result.answer, "down")
            st.toast("Thanks, logged.")

        st.session_state["history"].append(
            {"id": len(st.session_state["history"]), "question": question,
             "answer": result.answer, "figure": figure}
        )


pending = st.session_state.pop("pending", None)
typed = st.chat_input("e.g. What is driving involuntary churn?")
question = typed or pending
if question:
    handle(question)
