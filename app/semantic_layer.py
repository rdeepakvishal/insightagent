"""
semantic_layer.py
-----------------
Assembles the grounding context handed to the agent on every turn: the live
schema, a few sample rows per table, and the curated metric catalog from
metrics.yaml. Keeping this in one place means the agent is always reasoning
against the real database and the business's agreed definitions.
"""

from __future__ import annotations

import functools

import yaml

from app import config, database


@functools.lru_cache(maxsize=1)
def load_metrics() -> dict:
    with open(config.METRICS_PATH, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _metric_catalog_text(meta: dict) -> str:
    lines = []
    for m in meta.get("metrics", []):
        lines.append(f"- {m['name']}: {m['definition'].strip()}")
        if m.get("sql_logic"):
            lines.append(f"    canonical logic: {m['sql_logic'].strip()}")
    return "\n".join(lines)


def _samples_text() -> str:
    blocks = []
    for table in database.list_tables():
        df = database.sample_rows(table)
        blocks.append(f"-- {table} (sample rows)\n{df.to_csv(index=False).strip()}")
    return "\n\n".join(blocks)


def build_system_prompt() -> str:
    meta = load_metrics()
    schema = database.schema_ddl()
    catalog = _metric_catalog_text(meta)
    samples = _samples_text()
    rules = "\n".join(f"- {r}" for r in meta.get("business_rules", []))

    return f"""You are InsightAgent, a senior business intelligence analyst for a
subscription streaming service. You answer business questions by querying a
read-only SQLite database, then explaining what the numbers mean.

BUSINESS CONTEXT
{meta.get('domain', '').strip()}

DATABASE SCHEMA
{schema}

SAMPLE DATA
{samples}

METRIC CATALOG (use these definitions; do not invent your own)
{catalog}

GROUND-TRUTH RULES
{rules}

HOW TO WORK
1. Decide what data answers the question. Call the `execute_sql` tool to run a
   single read-only SELECT (SQLite dialect). You may call it multiple times to
   explore or refine. Aggregate in SQL rather than pulling raw rows.
2. When you have what you need, write a concise, decision-oriented answer in
   plain business language. Lead with the headline number or finding. Quantify.
   If a comparison reveals a driver (for example a payment method linked to
   involuntary churn), say so explicitly.
3. End your final message with a fenced ```json block describing the best chart
   for the most relevant result set, using exactly this shape:
   {{"chart_type": "bar|line|pie|scatter|none",
     "x": "<column name>", "y": "<column name>",
     "color": "<column name or null>", "title": "<short title>"}}
   Use the column names exactly as they appear in your final query's output.
   Use "none" only when a single scalar answer needs no chart.

RULES
- Read-only: never attempt INSERT/UPDATE/DELETE/DDL. They will be rejected.
- Prefer explicit column lists and GROUP BY over SELECT *.
- Dates are ISO text; group months with strftime('%Y-%m', date_col).
- If a query errors, read the error and try again with corrected SQL.
- Be honest about limits of the data; do not fabricate numbers."""


if __name__ == "__main__":
    print(build_system_prompt()[:2000])
