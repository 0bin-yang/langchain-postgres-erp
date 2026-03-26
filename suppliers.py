# =============================================================
# suppliers.py  |  Owner: Backend/Agents (LangChain)
# Responsibilities: supplier catalogue, scoring, selection
# =============================================================
import pandas as pd
from sqlalchemy import text
from db_setup import get_engine

# ------------------------------------------------------------------
# PROMPT TUNING LOG
# How we arrived at the supplier selection prompt:
#
# v1 -- "Pick the cheapest supplier."
#      Problem: agent always picked lowest price, ignored 40-day lead
#      times that caused stockouts. Reliability ignored entirely.
#
# v2 -- "Pick the supplier with the best price and shortest lead time."
#      Problem: agent flip-flopped between two suppliers depending on
#      which metric it parsed first. No tiebreaker. Reliability still
#      ignored -- SupplierC (60% on-time) kept getting selected.
#
# v3 -- "Score each supplier: score = 0.4*(1 - norm_price) +
#        0.35*(1 - norm_lead_time) + 0.25*reliability.
#        Select the highest score. Reject any supplier with
#        reliability < 0.70 regardless of score."
#      Problem: agent computed scores correctly but didn't explain
#      reasoning, making it hard to audit. Also didn't flag risk.
#
# v4 (FINAL) -- Explicit scoring formula + mandatory reasoning trace +
#      hard reliability floor (0.70) + risk flag when best supplier
#      has reliability < 0.85. This version is used in the agent prompt.
#      Result: consistent selection, auditable reasoning, risk alerts
#      surface in UI when supplier reliability is borderline.
# ------------------------------------------------------------------

SUPPLIER_SELECTION_PROMPT = """
You are a procurement agent. For each item that needs reordering, select the
best supplier using this STRICT scoring formula:

    score = (0.40 * price_score) + (0.35 * lead_score) + (0.25 * reliability)

Where:
    price_score    = 1 - (supplier_price / max_price_in_category)
    lead_score     = 1 - (lead_time_days / max_lead_in_category)
    reliability    = supplier on-time delivery rate (0.0 to 1.0)

Rules:
1. REJECT any supplier with reliability < 0.70, regardless of score.
2. If the winning supplier has reliability < 0.85, add a RISK ALERT:
   "Supplier X has {pct}% chance of delay -- consider dual sourcing."
3. Always show your score calculation in your reasoning trace.
4. Draft the PO using the winning supplier's unit_cost and lead_time_days.
"""


def init_supplier_table():
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS suppliers (
                supplier_id   SERIAL PRIMARY KEY,
                supplier_name TEXT NOT NULL,
                item_name     TEXT NOT NULL,
                unit_cost     FLOAT NOT NULL,
                lead_time_days INT NOT NULL,
                reliability   FLOAT NOT NULL,
                created_at    TIMESTAMP DEFAULT NOW()
            )
        """))
        count = conn.execute(text("SELECT COUNT(*) FROM suppliers")).scalar()
        if count == 0:
            seeds = [
                # (supplier_name, item_name, unit_cost, lead_time_days, reliability)
                ("SupplierA", "Non-urgent orders",    7.80, 5,  0.95),
                ("SupplierB", "Non-urgent orders",    8.10, 3,  0.88),
                ("SupplierC", "Non-urgent orders",    6.50, 12, 0.65),  # below floor
                ("SupplierA", "Urgent orders",       13.50, 2,  0.97),
                ("SupplierB", "Urgent orders",       14.00, 2,  0.91),
                ("SupplierC", "Urgent orders",       11.00, 8,  0.68),  # below floor
                ("SupplierA", "Order type A",        11.20, 4,  0.93),
                ("SupplierB", "Order type A",        12.50, 3,  0.89),
                ("SupplierA", "Order type B",         9.50, 4,  0.92),
                ("SupplierB", "Order type B",        10.20, 5,  0.94),
                ("SupplierA", "Order type C",        10.00, 5,  0.90),
                ("SupplierB", "Order type C",        11.50, 4,  0.83),  # risk alert
                ("SupplierA", "Fiscal sector orders",18.00, 8,  0.91),
                ("SupplierB", "Fiscal sector orders",20.00, 6,  0.96),
            ]
            for s, i, c, l, r in seeds:
                conn.execute(text("""
                    INSERT INTO suppliers (supplier_name, item_name, unit_cost, lead_time_days, reliability)
                    VALUES (:s, :i, :c, :l, :r)
                """), {"s": s, "i": i, "c": c, "l": l, "r": r})


def get_suppliers(item_name: str = None) -> pd.DataFrame:
    engine = get_engine()
    if item_name:
        return pd.read_sql(
            "SELECT * FROM suppliers WHERE item_name = %(n)s ORDER BY supplier_id",
            engine, params={"n": item_name}
        )
    return pd.read_sql("SELECT * FROM suppliers ORDER BY item_name, supplier_id", engine)


def select_best_supplier(item_name: str) -> dict:
    """
    Apply the v4 scoring formula. Returns best supplier dict + risk alert if any.
    """
    df = get_suppliers(item_name)
    # Hard reliability floor
    df = df[df["reliability"] >= 0.70].copy()
    if df.empty:
        return {"error": f"No reliable suppliers (>=0.70) found for {item_name}"}

    max_price = df["unit_cost"].max()
    max_lead  = df["lead_time_days"].max()

    df["price_score"] = 1 - (df["unit_cost"] / max_price)
    df["lead_score"]  = 1 - (df["lead_time_days"] / max_lead)
    df["score"]       = (0.40 * df["price_score"] +
                         0.35 * df["lead_score"]  +
                         0.25 * df["reliability"])

    best = df.loc[df["score"].idxmax()].to_dict()

    risk_alert = None
    if best["reliability"] < 0.85:
        delay_pct = round((1 - best["reliability"]) * 100)
        risk_alert = (f"WARNING: {best['supplier_name']} has {delay_pct}% chance of delay "
                      f"-- consider dual sourcing for {item_name}.")

    return {
        "supplier_name":  best["supplier_name"],
        "unit_cost":      best["unit_cost"],
        "lead_time_days": int(best["lead_time_days"]),
        "reliability":    best["reliability"],
        "score":          round(best["score"], 4),
        "risk_alert":     risk_alert,
        "all_scores":     df[["supplier_name", "unit_cost", "lead_time_days",
                               "reliability", "score"]].to_dict(orient="records"),
    }
