"""
generate_data.py
-----------------
Builds a synthetic but behaviourally realistic subscription-streaming dataset
and writes it to a single SQLite database (data/streamflix.db).

The data is modelled, not random: the relationships an analyst cares about are
baked in so an agent can actually *discover* them.

Designed relationships
-----------------------
1. Involuntary churn is driven by payment failures.
   Risky payment methods (Gift Card, Debit Card) fail far more often. Two
   consecutive months of uncollectable charges, or a hard "Card Expired"
   failure, cancels the subscription as churn_type = 'involuntary'.

2. Voluntary churn is driven by low engagement and tenure.
   Low-streaming customers cancel on purpose at much higher rates, with spikes
   early (buyer's remorse) and near the 12-month mark.

3. ARPU, plan mix, channel quality and country vary in believable ways.

Run:
    python data/generate_data.py
"""

from __future__ import annotations

import os
import sqlite3

import numpy as np
import pandas as pd

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #
SEED = 42
N_CUSTOMERS = 6000
DATA_AS_OF = pd.Timestamp("2025-06-01")        # "today" for the dataset
SIGNUP_START = pd.Timestamp("2023-01-01")
SIGNUP_END = pd.Timestamp("2025-03-01")
DB_PATH = os.path.join(os.path.dirname(__file__), "streamflix.db")

rng = np.random.default_rng(SEED)

# --------------------------------------------------------------------------- #
# Reference / dimension data
# --------------------------------------------------------------------------- #
PLANS = [
    (1, "Basic",          "Basic",     7.99),
    (2, "Standard",       "Standard", 12.99),
    (3, "Premium",        "Premium",  18.99),
    (4, "Annual Premium", "Premium",  15.99),
]
PLAN_WEIGHTS = [0.34, 0.40, 0.18, 0.08]

COUNTRIES = ["US", "UK", "IN", "DE", "FR", "BR", "JP", "CA", "AU", "MX"]
COUNTRY_WEIGHTS = [0.30, 0.12, 0.14, 0.08, 0.07, 0.08, 0.06, 0.05, 0.05, 0.05]

CHANNELS = ["Organic", "Paid Search", "Social", "Referral", "Partner Bundle"]
CHANNEL_WEIGHTS = [0.30, 0.24, 0.20, 0.14, 0.12]
CHANNEL_QUALITY = {            # higher = stickier customer
    "Organic": 1.20,
    "Paid Search": 0.95,
    "Social": 0.78,
    "Referral": 1.30,
    "Partner Bundle": 1.05,
}

PAYMENT_METHODS = ["Credit Card", "Debit Card", "PayPal", "Gift Card", "UPI"]
PAYMENT_WEIGHTS = [0.46, 0.22, 0.16, 0.06, 0.10]
# Probability that a whole monthly charge ends up uncollectable (after retries).
METHOD_MONTH_FAILURE = {
    "Credit Card": 0.010,
    "Debit Card": 0.045,
    "PayPal": 0.008,
    "Gift Card": 0.090,   # balance runs out -> strong involuntary-churn driver
    "UPI": 0.028,
}
FAILURE_REASONS = ["Insufficient Funds", "Card Expired", "Card Declined", "Network Error"]
FAILURE_REASON_WEIGHTS = [0.46, 0.18, 0.26, 0.10]

AGE_BANDS = ["18-24", "25-34", "35-44", "45-54", "55+"]
AGE_WEIGHTS = [0.18, 0.32, 0.24, 0.16, 0.10]

MAX_RETRIES = 3                # retries inside one billing cycle
INVOLUNTARY_TRIGGER = 2        # consecutive uncollectable months -> involuntary churn
HARD_FAIL_CHURN_PROB = 0.45    # a single "Card Expired" month can end it outright


def _month_floor(ts: pd.Timestamp) -> pd.Timestamp:
    return ts.normalize().replace(day=1)


def build_customers() -> pd.DataFrame:
    n = N_CUSTOMERS
    span_days = (SIGNUP_END - SIGNUP_START).days
    signup = SIGNUP_START + pd.to_timedelta(rng.integers(0, span_days, n), unit="D")

    plan_idx = rng.choice(len(PLANS), size=n, p=PLAN_WEIGHTS)
    channel = rng.choice(CHANNELS, size=n, p=CHANNEL_WEIGHTS)

    df = pd.DataFrame(
        {
            "customer_id": np.arange(1, n + 1),
            "signup_date": [_month_floor(pd.Timestamp(d)) for d in signup],
            "country": rng.choice(COUNTRIES, size=n, p=COUNTRY_WEIGHTS),
            "age_band": rng.choice(AGE_BANDS, size=n, p=AGE_WEIGHTS),
            "acquisition_channel": channel,
            "payment_method": rng.choice(PAYMENT_METHODS, size=n, p=PAYMENT_WEIGHTS),
            "plan_id": [PLANS[i][0] for i in plan_idx],
        }
    )
    # Latent traits driving behaviour (used in sim, not stored).
    df["lat_affinity"] = np.clip(
        rng.beta(2.0, 3.0, n) * df["acquisition_channel"].map(CHANNEL_QUALITY).values, 0.02, 1.0
    )
    df["lat_pay_risk"] = np.clip(rng.beta(1.6, 6.0, n), 0.0, 1.0)
    return df


def _emit_payment(rows, pay_id, cust_id, month, amount, status, method, reason, retry):
    rows.append(
        {
            "payment_id": pay_id,
            "customer_id": int(cust_id),
            "payment_date": month.date().isoformat(),
            "amount": round(float(amount), 2),
            "status": status,
            "payment_method": method,
            "failure_reason": reason,
            "retry_count": retry,
        }
    )


def simulate(customers: pd.DataFrame):
    plan_lookup = {p[0]: {"name": p[1], "tier": p[2], "price": p[3]} for p in PLANS}
    sub_rows, pay_rows, eng_rows = [], [], []
    pay_id = 0

    for row in customers.itertuples(index=False):
        cust_id = row.customer_id
        plan = plan_lookup[row.plan_id]
        mrr = plan["price"]
        p_month_fail = METHOD_MONTH_FAILURE[row.payment_method] * (0.6 + 0.9 * row.lat_pay_risk)
        affinity = row.lat_affinity

        month = _month_floor(row.signup_date)
        status, churn_type, churn_date = "active", None, None
        consecutive_fail = 0
        tenure = 0

        while month <= DATA_AS_OF and status == "active":
            tenure += 1

            # ---- engagement -------------------------------------------------
            decay = 0.992 ** tenure
            base_hours = affinity * 40.0 * decay
            streaming_hours = max(0.0, rng.normal(base_hours, 3.5))
            days_active = int(np.clip(round(streaming_hours / 1.6 + rng.normal(0, 2)), 0, 30))
            titles_watched = int(np.clip(round(streaming_hours / 1.1 + rng.normal(0, 3)), 0, 200))
            eng_rows.append(
                {
                    "customer_id": int(cust_id),
                    "activity_month": month.date().isoformat(),
                    "streaming_hours": round(float(streaming_hours), 2),
                    "titles_watched": titles_watched,
                    "days_active": days_active,
                }
            )

            # ---- billing ----------------------------------------------------
            month_failed = rng.random() < p_month_fail
            if month_failed:
                reason = str(rng.choice(FAILURE_REASONS, p=FAILURE_REASON_WEIGHTS))
                for attempt in range(MAX_RETRIES):
                    pay_id += 1
                    _emit_payment(pay_rows, pay_id, cust_id, month, mrr, "failed",
                                  row.payment_method, reason, attempt)
                consecutive_fail += 1
                hard_fail = reason == "Card Expired" and rng.random() < HARD_FAIL_CHURN_PROB
                if consecutive_fail >= INVOLUNTARY_TRIGGER or hard_fail:
                    status, churn_type, churn_date = "churned", "involuntary", month
                    break
            else:
                # sometimes a soft retry precedes success
                if rng.random() < p_month_fail * 1.4:
                    pay_id += 1
                    _emit_payment(pay_rows, pay_id, cust_id, month, mrr, "failed",
                                  row.payment_method,
                                  str(rng.choice(FAILURE_REASONS, p=FAILURE_REASON_WEIGHTS)), 0)
                    retry = 1
                else:
                    retry = 0
                pay_id += 1
                _emit_payment(pay_rows, pay_id, cust_id, month, mrr, "success",
                              row.payment_method, None, retry)
                consecutive_fail = 0
                if rng.random() < 0.012:                       # occasional refund
                    pay_id += 1
                    _emit_payment(pay_rows, pay_id, cust_id, month, -mrr, "refunded",
                                  row.payment_method, None, 0)

            # ---- voluntary churn hazard (engagement-driven) -----------------
            hazard = 1 / (1 + np.exp((streaming_hours - 8.0) / 4.0)) * 0.13
            if tenure <= 2:
                hazard += 0.035
            if 11 <= tenure <= 13:
                hazard += 0.030
            hazard = float(np.clip(hazard, 0.001, 0.6))
            if rng.random() < hazard:
                status, churn_type, churn_date = "churned", "voluntary", month
                break

            month = _month_floor(month + pd.DateOffset(months=1))

        sub_rows.append(
            {
                "subscription_id": int(cust_id),
                "customer_id": int(cust_id),
                "plan_id": int(row.plan_id),
                "mrr": round(mrr, 2),
                "start_date": row.signup_date.date().isoformat(),
                "status": status,
                "churn_type": churn_type if status == "churned" else "active",
                "churn_date": churn_date.date().isoformat() if churn_date is not None else None,
                "tenure_months": tenure,
            }
        )

    return pd.DataFrame(sub_rows), pd.DataFrame(pay_rows), pd.DataFrame(eng_rows)


def main() -> None:
    print("Generating customers ...")
    customers = build_customers()
    print("Simulating subscriptions, payments and engagement ...")
    subs, payments, engagement = simulate(customers)

    customers_out = customers.drop(columns=["lat_affinity", "lat_pay_risk"]).copy()
    customers_out["signup_date"] = customers_out["signup_date"].dt.date.astype(str)
    plans = pd.DataFrame(PLANS, columns=["plan_id", "plan_name", "tier", "monthly_price"])

    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    conn = sqlite3.connect(DB_PATH)
    try:
        plans.to_sql("plans", conn, index=False)
        customers_out.to_sql("customers", conn, index=False)
        subs.to_sql("subscriptions", conn, index=False)
        payments.to_sql("payments", conn, index=False)
        engagement.to_sql("engagement", conn, index=False)
        cur = conn.cursor()
        for stmt in [
            "CREATE INDEX idx_pay_cust ON payments(customer_id)",
            "CREATE INDEX idx_pay_status ON payments(status)",
            "CREATE INDEX idx_eng_cust ON engagement(customer_id)",
            "CREATE INDEX idx_sub_status ON subscriptions(status)",
            "CREATE INDEX idx_sub_churntype ON subscriptions(churn_type)",
        ]:
            cur.execute(stmt)
        conn.commit()
    finally:
        conn.close()

    print(f"\nWrote {DB_PATH}")
    print(f"  plans:         {len(plans):>7,}")
    print(f"  customers:     {len(customers_out):>7,}")
    print(f"  subscriptions: {len(subs):>7,}")
    print(f"  payments:      {len(payments):>7,}")
    print(f"  engagement:    {len(engagement):>7,}")


if __name__ == "__main__":
    main()
