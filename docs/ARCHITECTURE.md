# InsightAgent — Architecture

**A natural-language analytics agent over a subscription-streaming warehouse.**
Ask a business question in plain English; the agent writes and runs its own SQL,
explains the result, and visualizes it.

🔗 **Live demo:** [insightagent-dvr.streamlit.app](https://insightagent-dvr.streamlit.app)

> Built on fully synthetic data. No real customers, credentials, or proprietary
> systems — a clean, portfolio-safe analog of a production BI assistant.

---

## 1. Problem

Ad-hoc data questions ("what's driving involuntary churn?", "how has monthly
churn trended?") normally require an analyst to hand-write SQL against a warehouse,
knowing the schema, the metric definitions, and the right filters. That's slow and
doesn't scale to non-technical stakeholders.

**InsightAgent** lets anyone ask in natural language and get a validated answer —
the SQL, the result table, a chart, and a written interpretation — in seconds.

---

## 2. Core Flow

```
User question (natural language)
        │
        ▼
Agent reasons over a semantic layer  ──►  schema + sample rows + metric catalog
        │
        ▼
Agent emits a single SELECT  ──►  SQL guardrail (read-only, one statement, row cap)
        │
        ▼
Query runs against a read-only SQLite connection
        │
        ▼
Agent inspects results, refines if needed (multi-step tool-use loop)
        │
        ▼
Business answer  +  chart spec  ──►  rule-based chart rendering
```

The loop is **agentic**, not one-shot text-to-SQL: the model can run several
queries, observe the results, and adapt — the way an analyst explores — before
composing a final answer.

---

## 3. Architecture Layers

| Layer | Technology | Responsibility |
|---|---|---|
| **Frontend** | Streamlit + shadcn-ui | Chat UI, KPI cards, collapsible metric/data browser, SQL transparency panels, feedback logging |
| **Agent core** | Anthropic Claude (tool-use loop); pluggable to OpenAI | Reasons about the question, calls the `execute_sql` tool, refines, writes the answer + chart spec |
| **Semantic layer** | `semantic_layer.py` + `metrics.yaml` | Grounds the agent in live schema, sample rows, and a curated metric catalog with canonical SQL — the "knowledge base" |
| **SQL guardrail** | `sql_guard.py` | Defence-in-depth: single statement, `SELECT`/`WITH` only, forbidden-keyword block, auto-injected `LIMIT` |
| **Query engine** | SQLite (read-only connection) | Executes guarded queries; returns rows as a DataFrame |
| **Visualization** | Plotly + rule layer (`charting.py`) | Turns the agent's chart spec into a figure under business rules (see §5) |
| **Config** | `config.py` | Model/provider selection, row limits, agent step cap — all env-overridable |

---

## 4. Key Design Decisions

**Agentic loop over single-shot text-to-SQL.** Real questions need exploration.
Letting the model query, observe, and refine handles follow-ups and
self-correction. Step count is capped (`MAX_AGENT_STEPS`) to bound cost/latency.

**A semantic layer, not raw schema alone.** Metric definitions live in
`metrics.yaml` with canonical SQL, so a term like "involuntary churn rate" means
the same thing every time. This is the demo's stand-in for a production knowledge
base, and the natural seam to swap in RAG once the catalog outgrows the context
window.

**Defence-in-depth on SQL.** The model is *told* to write read-only SQL, but it's
also *enforced*: every query passes a guardrail (one statement; `SELECT`/`WITH`
only; DML/DDL/PRAGMA/ATTACH blocked; row cap injected) **and** the database
connection itself is opened read-only. Two independent guarantees.

**Trust through transparency.** Every answer ships with the exact SQL the agent
ran and the underlying rows, in expandable panels. Stakeholders can audit;
analysts can lift the query.

**Provider-flexible.** Anthropic by default, OpenAI via one env var. Both expose
the same `execute_sql` tool, so the agent loop is identical regardless of model.

---

## 5. Visualization Rules

Charting is decoupled from the agent so the visual conventions are easy to tune.
The agent proposes a chart; a rule layer enforces sensible defaults:

- **Rates over time** → line chart (only when the x-axis is actually temporal).
- **Rates across categories** → bar chart (a line would imply a trend that isn't there).
- **Absolute counts over time** → bar chart.
- **Rate + count over the same period** → **combo** chart (bars + line on dual axes).
- **Never** pie charts.
- Rate columns render as **percentages**; numeric color legends are suppressed to
  avoid clutter.

---

## 6. Data

Synthetic but *behaviourally modelled* — relationships an analyst would care about
are baked in so the agent can actually discover them:

- **Involuntary churn** is driven by payment failures (risky payment methods fail
  more; consecutive failures or a hard decline cancel the subscription).
- **Voluntary churn** is driven by low engagement and tenure (early buyer's
  remorse and a ~12-month cliff).

~30 months of monthly history across 5 tables (~6k customers, ~78k payments,
~73k engagement rows), enough to support real trend analysis.

---

## 7. Where It Would Go Next

| Dimension | Today (demo) | Production direction |
|---|---|---|
| Knowledge base | In-context metric catalog | RAG / vector store as the catalog grows past the context window |
| Warehouse | SQLite | Redshift / Snowflake / BigQuery via the same guarded-query seam |
| Validation | Guardrail + read-only conn | Add an `EXPLAIN`-style pre-check for syntax/schema |
| Models | Single model | Cheaper model for validation/summarization, stronger model for reasoning |
| Memory | Per-session | Cross-session memory + follow-up context tracking |
| Hosting | Streamlit Community Cloud | Containerized / managed agent hosting with auth |

---

*This document describes a personal project built on synthetic data. It is
intended to illustrate architecture and design reasoning that transfer across
BI-agent systems.*
