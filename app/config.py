"""Central configuration. Values can be overridden with environment variables."""

from __future__ import annotations

import os

# Resolve the database path relative to the repo root regardless of CWD.
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)

DB_PATH = os.environ.get("STREAMFLIX_DB", os.path.join(_ROOT, "data", "streamflix.db"))
METRICS_PATH = os.path.join(_HERE, "metrics.yaml")

# LLM settings. "anthropic" (default) or "openai".
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "anthropic").lower()
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o")

MAX_AGENT_STEPS = int(os.environ.get("MAX_AGENT_STEPS", "6"))
ROW_LIMIT = int(os.environ.get("ROW_LIMIT", "1000"))
SAMPLE_ROWS_IN_PROMPT = 3

FEEDBACK_LOG = os.path.join(_ROOT, "feedback.jsonl")
