"""
database.py
-----------
Thin data-access layer over the SQLite warehouse. Connections are opened in
read-only mode (file:...?mode=ro) so even a query that somehow slipped past the
SQL guard cannot mutate data.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

import pandas as pd

from app import config
from app.sql_guard import guard


@dataclass
class QueryResult:
    sql: str               # the exact SQL that ran (after guarding)
    dataframe: pd.DataFrame
    row_count: int
    truncated: bool


def _connect() -> sqlite3.Connection:
    uri = f"file:{config.DB_PATH}?mode=ro"
    return sqlite3.connect(uri, uri=True)


def list_tables() -> list[str]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
    return [r[0] for r in rows]


def schema_ddl() -> str:
    """Return CREATE statements for every table, for the agent's context."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND sql IS NOT NULL ORDER BY name"
        ).fetchall()
    return "\n\n".join(r[0].strip() for r in rows)


def sample_rows(table: str, n: int = config.SAMPLE_ROWS_IN_PROMPT) -> pd.DataFrame:
    with _connect() as conn:
        return pd.read_sql(f"SELECT * FROM {table} LIMIT {int(n)}", conn)


def run_query(sql: str, row_limit: int = config.ROW_LIMIT) -> QueryResult:
    """Guard, execute, and return a query as a DataFrame."""
    guarded = guard(sql, row_limit=row_limit)
    with _connect() as conn:
        df = pd.read_sql(guarded.sql, conn)
    truncated = guarded.limit_applied and len(df) >= row_limit
    return QueryResult(sql=guarded.sql, dataframe=df, row_count=len(df), truncated=truncated)


if __name__ == "__main__":
    print("Tables:", list_tables())
    print("\nSample subscriptions:")
    print(sample_rows("subscriptions"))
    print("\nTest query:")
    res = run_query("SELECT country, COUNT(*) AS n FROM customers GROUP BY 1 ORDER BY n DESC")
    print(res.dataframe.head())
