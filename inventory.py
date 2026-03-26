# =============================================================
# inventory.py  |  Owner: Data/Forecasting (Prophet)
# Responsibilities: ROP/EOQ calculations, inventory DB table
# =============================================================
import math
import pandas as pd
from sqlalchemy import text
from db_setup import get_engine


# ------------------------------------------------------------------
# Table bootstrap
# ------------------------------------------------------------------
def init_inventory_table():
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS inventory (
                item_id     SERIAL PRIMARY KEY,
                item_name   TEXT NOT NULL,
                stock_qty   FLOAT NOT NULL,
                unit_cost   FLOAT NOT NULL,
                lead_time_days INT NOT NULL,
                holding_cost_pct FLOAT NOT NULL DEFAULT 0.20,
                order_cost  FLOAT NOT NULL DEFAULT 50.0,
                created_at  TIMESTAMP DEFAULT NOW()
            )
        """))
        # Seed with DDFO order types if empty
        count = conn.execute(text("SELECT COUNT(*) FROM inventory")).scalar()
        if count == 0:
            seeds = [
                ("Non-urgent orders",   1200, 8.50,  7),
                ("Urgent orders",        400, 15.00,  3),
                ("Order type A",         600, 12.00,  5),
                ("Order type B",         800, 10.00,  5),
                ("Order type C",         500, 11.00,  6),
                ("Fiscal sector orders", 300, 20.00, 10),
            ]
            for name, qty, cost, lead in seeds:
                conn.execute(text("""
                    INSERT INTO inventory (item_name, stock_qty, unit_cost, lead_time_days)
                    VALUES (:n, :q, :c, :l)
                """), {"n": name, "q": qty, "c": cost, "l": lead})


# ------------------------------------------------------------------
# ROP  =  avg_daily_demand * lead_time  +  safety_stock
# EOQ  =  sqrt(2 * D * S / H)
# ------------------------------------------------------------------
def calculate_rop_eoq(avg_daily_demand: float, lead_time_days: int,
                      annual_demand: float, order_cost: float,
                      unit_cost: float, holding_cost_pct: float = 0.20,
                      z: float = 1.65, std_daily_demand: float = None) -> dict:

    if std_daily_demand is None:
        std_daily_demand = avg_daily_demand * 0.20   # assume 20% variability

    safety_stock = z * std_daily_demand * math.sqrt(lead_time_days)
    rop  = (avg_daily_demand * lead_time_days) + safety_stock
    H    = unit_cost * holding_cost_pct
    eoq  = math.sqrt((2 * annual_demand * order_cost) / H) if H > 0 else 0

    return {
        "avg_daily_demand":  round(avg_daily_demand, 2),
        "lead_time_days":    lead_time_days,
        "safety_stock":      round(safety_stock, 2),
        "rop":               round(rop, 2),
        "eoq":               round(eoq, 2),
        "annual_demand":     round(annual_demand, 2),
    }


# ------------------------------------------------------------------
# Query inventory from DB -- used as agent tool
# ------------------------------------------------------------------
def get_inventory_status() -> pd.DataFrame:
    engine = get_engine()
    df = pd.read_sql("SELECT * FROM inventory ORDER BY item_id", engine)
    return df


def get_inventory_with_rop_eoq(avg_daily_demand: float, forecast_std: float = None) -> pd.DataFrame:
    df = get_inventory_status()
    rows = []
    for _, row in df.iterrows():
        metrics = calculate_rop_eoq(
            avg_daily_demand  = avg_daily_demand,
            lead_time_days    = int(row["lead_time_days"]),
            annual_demand     = avg_daily_demand * 365,
            order_cost        = float(row["order_cost"]),
            unit_cost         = float(row["unit_cost"]),
            holding_cost_pct  = float(row["holding_cost_pct"]),
            std_daily_demand  = forecast_std,
        )
        needs_reorder = row["stock_qty"] <= metrics["rop"]
        # Days until stockout = current stock / avg daily demand
        days_to_stockout = round(row["stock_qty"] / avg_daily_demand, 1) if avg_daily_demand > 0 else None
        rows.append({
            "item_id":          row["item_id"],
            "item_name":        row["item_name"],
            "stock_qty":        row["stock_qty"],
            "unit_cost":        row["unit_cost"],
            **metrics,
            "needs_reorder":    needs_reorder,
            "days_to_stockout": days_to_stockout,
            "stockout_date":    (
                (pd.Timestamp.now() + pd.Timedelta(days=days_to_stockout)).strftime("%Y-%m-%d")
                if days_to_stockout is not None else "N/A"
            ),
        })
    return pd.DataFrame(rows)
