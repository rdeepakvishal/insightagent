"""
sql_guard.py
-------------
Defence-in-depth for an LLM that writes SQL. The model only ever runs queries
that pass these checks, and the database is also opened read-only at the
connection layer (see database.py). Two independent guarantees are better than
one.

Rules enforced:
  * exactly one statement (no stacked queries)
  * must be a SELECT or WITH ... SELECT
  * no DML / DDL / PRAGMA / ATTACH keywords anywhere
  * a LIMIT is injected if the query has none, capping rows returned
"""

from __future__ import annotations

import re
from dataclasses import dataclass

DEFAULT_ROW_LIMIT = 1000

_FORBIDDEN = (
    "insert", "update", "delete", "drop", "alter", "create", "replace",
    "truncate", "attach", "detach", "pragma", "vacuum", "reindex", "grant",
    "revoke", "commit", "rollback", "begin",
)
_FORBIDDEN_RE = re.compile(r"\b(" + "|".join(_FORBIDDEN) + r")\b", re.IGNORECASE)


class UnsafeQueryError(ValueError):
    """Raised when a query violates the read-only contract."""


@dataclass
class GuardedQuery:
    sql: str
    limit_applied: bool


def _strip_comments(sql: str) -> str:
    sql = re.sub(r"--[^\n]*", " ", sql)          # line comments
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)  # block comments
    return sql


def guard(sql: str, row_limit: int = DEFAULT_ROW_LIMIT) -> GuardedQuery:
    """Validate and normalise a query, or raise UnsafeQueryError."""
    if not sql or not sql.strip():
        raise UnsafeQueryError("Empty query.")

    cleaned = _strip_comments(sql).strip().rstrip(";").strip()

    if ";" in cleaned:
        raise UnsafeQueryError("Only a single statement is allowed.")

    lowered = cleaned.lower()
    if not (lowered.startswith("select") or lowered.startswith("with")):
        raise UnsafeQueryError("Only SELECT / WITH queries are allowed.")

    if _FORBIDDEN_RE.search(cleaned):
        raise UnsafeQueryError("Query contains a forbidden keyword.")

    limit_applied = False
    if not re.search(r"\blimit\b", lowered):
        cleaned = f"{cleaned}\nLIMIT {row_limit}"
        limit_applied = True

    return GuardedQuery(sql=cleaned, limit_applied=limit_applied)


if __name__ == "__main__":
    # quick self-test
    ok = [
        "SELECT * FROM customers",
        "WITH t AS (SELECT 1 AS x) SELECT * FROM t",
        "select country, count(*) from customers group by 1 limit 5",
    ]
    bad = [
        "DROP TABLE customers",
        "SELECT 1; DELETE FROM payments",
        "UPDATE subscriptions SET status='active'",
        "SELECT * FROM customers; PRAGMA table_info(customers)",
        "INSERT INTO plans VALUES (9,'x','y',1.0)",
    ]
    for s in ok:
        g = guard(s)
        print("OK  ", repr(s), "->", "limit_added" if g.limit_applied else "kept")
    for s in bad:
        try:
            guard(s)
            print("FAIL (allowed!):", repr(s))
        except UnsafeQueryError as e:
            print("BLOCKED", repr(s), "->", e)
