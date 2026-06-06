"""
demo_offline.py
---------------
Runs the canonical analyses directly against the database, no API key needed.
Useful as a sanity check, for generating README figures, and to show reviewers
the insights the agent is expected to surface.

Run:
    python scripts/demo_offline.py
"""

from __future__ import annotations

import os
import sqlite3

import pandas as pd

DB = os.path.join(os.path.dirname(__file__), "..", "data", "streamflix.db")


def q(conn, sql):
    return pd.read_sql(sql, conn)


def main():
    conn = sqlite3.connect(f"file:{os.path.abspath(DB)}?mode=ro", uri=True)
    try:
        print("\n1) Subscription status mix")
        print(q(conn, """
            SELECT status, churn_type, COUNT(*) AS subscribers,
                   ROUND(100.0*COUNT(*)/(SELECT COUNT(*) FROM subscriptions),1) AS pct
            FROM subscriptions GROUP BY 1,2 ORDER BY subscribers DESC
        """).to_string(index=False))

        print("\n2) Churn by payment method (the involuntary-churn driver)")
        print(q(conn, """
            SELECT c.payment_method,
                   COUNT(*) AS customers,
                   ROUND(100.0*SUM(s.churn_type='involuntary')/COUNT(*),1) AS involuntary_pct,
                   ROUND(100.0*SUM(s.churn_type='voluntary')/COUNT(*),1)   AS voluntary_pct
            FROM subscriptions s JOIN customers c ON c.customer_id=s.customer_id
            GROUP BY 1 ORDER BY involuntary_pct DESC
        """).to_string(index=False))

        print("\n3) Engagement by churn type (voluntary intent signal)")
        print(q(conn, """
            SELECT s.churn_type, ROUND(AVG(e.streaming_hours),1) AS avg_monthly_hours
            FROM subscriptions s JOIN engagement e ON e.customer_id=s.customer_id
            GROUP BY 1 ORDER BY avg_monthly_hours DESC
        """).to_string(index=False))

        print("\n4) Churn rate by acquisition channel")
        print(q(conn, """
            SELECT c.acquisition_channel,
                   ROUND(100.0*SUM(s.status='churned')/COUNT(*),1) AS churn_pct
            FROM subscriptions s JOIN customers c ON c.customer_id=s.customer_id
            GROUP BY 1 ORDER BY churn_pct DESC
        """).to_string(index=False))

        print("\n5) Headline metrics")
        print(q(conn, """
            SELECT
              (SELECT COUNT(*) FROM subscriptions WHERE status='active')          AS active_subscribers,
              (SELECT ROUND(SUM(mrr),0) FROM subscriptions WHERE status='active')  AS mrr,
              (SELECT ROUND(AVG(mrr),2) FROM subscriptions WHERE status='active')  AS arpu,
              (SELECT ROUND(100.0*AVG(status='success'),1) FROM payments)          AS payment_success_pct
        """).to_string(index=False))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
