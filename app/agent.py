"""
agent.py
--------
The agentic core. Given a natural-language question, the agent:
  1. reasons about what data it needs,
  2. calls the `execute_sql` tool (one read-only SELECT at a time),
  3. inspects results and refines if needed,
  4. returns a business answer plus a chart spec.

This is a tool-use loop, not a one-shot text-to-SQL call: the model can run
several queries, see the results, and adapt, which is what makes it "agentic".

Provider-flexible: defaults to Anthropic Claude; set LLM_PROVIDER=openai to use
OpenAI instead. Both expose the same tool, so the loop is identical.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

import pandas as pd

from app import config, database, semantic_layer
from app.sql_guard import UnsafeQueryError

# --------------------------------------------------------------------------- #
# Tool definition (shared shape; adapted per provider below)
# --------------------------------------------------------------------------- #
_TOOL_NAME = "execute_sql"
_TOOL_DESCRIPTION = (
    "Run a single read-only SQL SELECT query against the SQLite database and "
    "return the result rows as CSV. Aggregate in SQL; do not select raw rows "
    "when a summary will do."
)
_TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {"type": "string", "description": "A single SQLite SELECT statement."}
    },
    "required": ["query"],
}


@dataclass
class AgentResult:
    question: str
    answer: str
    sql_log: list[str] = field(default_factory=list)   # every query the agent ran
    result_df: pd.DataFrame | None = None              # last successful result
    chart_spec: dict | None = None
    steps: int = 0
    error: str | None = None


# --------------------------------------------------------------------------- #
# Tool execution shared by both providers
# --------------------------------------------------------------------------- #
def _run_tool(query: str, sql_log: list[str]) -> tuple[str, pd.DataFrame | None]:
    """Execute a guarded query; return (text_for_model, dataframe_or_none)."""
    try:
        res = database.run_query(query)
        sql_log.append(res.sql)
        preview = res.dataframe.head(50).to_csv(index=False)
        note = ""
        if res.truncated:
            note = f"\n[note: result truncated to {config.ROW_LIMIT} rows]"
        return (f"Returned {res.row_count} rows.\n{preview}{note}", res.dataframe)
    except UnsafeQueryError as e:
        return (f"ERROR (blocked by guardrail): {e}", None)
    except Exception as e:  # noqa: BLE001  surface DB errors back to the model
        return (f"ERROR: {e}", None)


def _extract_chart_spec(text: str) -> tuple[str, dict | None]:
    """Pull a trailing ```json chart spec out of the answer text, if present."""
    match = re.search(r"```json\s*(\{.*?\})\s*```", text, flags=re.DOTALL)
    if not match:
        return text.strip(), None
    try:
        spec = json.loads(match.group(1))
    except json.JSONDecodeError:
        return text.strip(), None
    clean = (text[: match.start()] + text[match.end():]).strip()
    return clean, spec


# --------------------------------------------------------------------------- #
# Anthropic implementation
# --------------------------------------------------------------------------- #
def _ask_anthropic(question: str, system: str) -> AgentResult:
    import anthropic

    client = anthropic.Anthropic()
    tools = [{"name": _TOOL_NAME, "description": _TOOL_DESCRIPTION, "input_schema": _TOOL_SCHEMA}]
    messages = [{"role": "user", "content": question}]
    sql_log: list[str] = []
    last_df: pd.DataFrame | None = None
    steps = 0

    while steps < config.MAX_AGENT_STEPS:
        steps += 1
        resp = client.messages.create(
            model=config.ANTHROPIC_MODEL,
            max_tokens=1500,
            system=system,
            tools=tools,
            messages=messages,
        )
        messages.append({"role": "assistant", "content": resp.content})

        if resp.stop_reason != "tool_use":
            text = "".join(b.text for b in resp.content if b.type == "text")
            answer, spec = _extract_chart_spec(text)
            return AgentResult(question, answer, sql_log, last_df, spec, steps)

        tool_results = []
        for block in resp.content:
            if block.type == "tool_use" and block.name == _TOOL_NAME:
                out, df = _run_tool(block.input.get("query", ""), sql_log)
                if df is not None:
                    last_df = df
                tool_results.append(
                    {"type": "tool_result", "tool_use_id": block.id, "content": out}
                )
        messages.append({"role": "user", "content": tool_results})

    return AgentResult(
        question, "Reached the step limit before finishing. Try a narrower question.",
        sql_log, last_df, None, steps, error="max_steps",
    )


# --------------------------------------------------------------------------- #
# OpenAI implementation
# --------------------------------------------------------------------------- #
def _ask_openai(question: str, system: str) -> AgentResult:
    from openai import OpenAI

    client = OpenAI()
    tools = [{
        "type": "function",
        "function": {"name": _TOOL_NAME, "description": _TOOL_DESCRIPTION, "parameters": _TOOL_SCHEMA},
    }]
    messages = [{"role": "system", "content": system}, {"role": "user", "content": question}]
    sql_log: list[str] = []
    last_df: pd.DataFrame | None = None
    steps = 0

    while steps < config.MAX_AGENT_STEPS:
        steps += 1
        resp = client.chat.completions.create(
            model=config.OPENAI_MODEL, messages=messages, tools=tools, max_tokens=1500,
        )
        msg = resp.choices[0].message
        messages.append(msg.model_dump(exclude_none=True))

        if not msg.tool_calls:
            answer, spec = _extract_chart_spec(msg.content or "")
            return AgentResult(question, answer, sql_log, last_df, spec, steps)

        for call in msg.tool_calls:
            args = json.loads(call.function.arguments or "{}")
            out, df = _run_tool(args.get("query", ""), sql_log)
            if df is not None:
                last_df = df
            messages.append({"role": "tool", "tool_call_id": call.id, "content": out})

    return AgentResult(
        question, "Reached the step limit before finishing. Try a narrower question.",
        sql_log, last_df, None, steps, error="max_steps",
    )


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #
def ask(question: str) -> AgentResult:
    system = semantic_layer.build_system_prompt()
    if config.LLM_PROVIDER == "openai":
        return _ask_openai(question, system)
    return _ask_anthropic(question, system)


if __name__ == "__main__":
    import sys

    q = " ".join(sys.argv[1:]) or "What is driving involuntary churn?"
    r = ask(q)
    print("Q:", r.question)
    print("A:", r.answer)
    print("SQL ran:", *r.sql_log, sep="\n  ")
    print("Chart:", r.chart_spec)
