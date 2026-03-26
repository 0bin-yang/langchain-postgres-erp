# =============================================================
# purchase_order.py  |  Owner: Backend/Agents (LangChain)
# Responsibilities: PO generation, DB persistence
# =============================================================
import json
from datetime import datetime, timedelta
import pandas as pd
from sqlalchemy import text
from db_setup import get_engine


def init_po_table():
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS purchase_orders (
                po_id        SERIAL PRIMARY KEY,
                item_name    TEXT NOT NULL,
                qty_ordered  FLOAT NOT NULL,
                unit_cost    FLOAT NOT NULL,
                total_cost   FLOAT NOT NULL,
                trigger_reason TEXT,
                status       TEXT DEFAULT 'DRAFT',
                created_at   TIMESTAMP DEFAULT NOW(),
                expected_delivery DATE
            )
        """))


def draft_purchase_order(item_name: str, qty: float, unit_cost: float,
                          trigger_reason: str, lead_time_days: int = 7) -> dict:
    po = {
        "item_name":         item_name,
        "qty_ordered":       round(qty, 2),
        "unit_cost":         round(unit_cost, 2),
        "total_cost":        round(qty * unit_cost, 2),
        "trigger_reason":    trigger_reason,
        "status":            "DRAFT",
        "created_at":        datetime.utcnow().isoformat(),
        "expected_delivery": (datetime.utcnow() + timedelta(days=lead_time_days)).date().isoformat(),
    }

    # Persist to DB
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO purchase_orders
                (item_name, qty_ordered, unit_cost, total_cost, trigger_reason, status, expected_delivery)
            VALUES
                (:item_name, :qty_ordered, :unit_cost, :total_cost, :trigger_reason, :status, :expected_delivery)
        """), po)

    return po


def get_purchase_orders() -> pd.DataFrame:
    engine = get_engine()
    return pd.read_sql(
        "SELECT * FROM purchase_orders ORDER BY created_at DESC LIMIT 50", engine
    )
