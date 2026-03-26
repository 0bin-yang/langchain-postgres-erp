# =============================================================
# agent.py  |  Owner: Backend/Agents (LangChain)
# Responsibilities: ReAct agent, tool definitions,
#                   autonomous pipeline orchestration
# =============================================================
import json
import os
import pandas as pd
from dotenv import load_dotenv
from suppliers import SUPPLIER_SELECTION_PROMPT

load_dotenv(dotenv_path=".env")


# ------------------------------------------------------------------
# Shared tool implementations
# ------------------------------------------------------------------
def _run_forecast(periods: int = 30) -> dict:
    from db_setup import get_engine
    from forecast import run_forecast_pipeline
    result = run_forecast_pipeline(get_engine(), periods=periods)
    return {
        "avg_daily_demand": result["avg_daily_demand"],
        "std_daily_demand": result["std_daily_demand"],
        "peak_demand":      result["peak_demand"],
        "mae":              result["metrics"]["mae"],
        "rmse":             result["metrics"]["rmse"],
        "periods":          periods,
    }


def _query_inventory(avg_daily_demand: float) -> pd.DataFrame:
    from inventory import get_inventory_with_rop_eoq
    return get_inventory_with_rop_eoq(avg_daily_demand)


def _select_supplier(item_name: str) -> dict:
    from suppliers import select_best_supplier
    return select_best_supplier(item_name)


def _draft_po(item_name, qty, unit_cost, trigger_reason, lead_time_days) -> dict:
    from purchase_order import draft_purchase_order
    return draft_purchase_order(item_name, qty, unit_cost, trigger_reason, lead_time_days)


# ------------------------------------------------------------------
# Savings report calculation
# ------------------------------------------------------------------
def calculate_savings_report(inv_df: pd.DataFrame, drafted_pos: list,
                              avg_daily_demand: float) -> dict:
    """
    Frame the agent as a cost-saver:
    - Stockout prevention: lost sales avoided = stockout_days * avg_demand * avg_unit_cost
    - Waste reduction:     overstock cost avoided by using EOQ instead of ad-hoc ordering
    - Ordering efficiency: fewer emergency orders at premium price
    """
    avg_unit_cost   = inv_df["unit_cost"].mean()
    total_po_value  = sum(p["total_cost"] for p in drafted_pos)

    # Lost sales prevented: items that would have stocked out within lead time
    at_risk = inv_df[inv_df["days_to_stockout"] <= inv_df["lead_time_days"]]
    lost_sales_prevented = float(
        at_risk["days_to_stockout"].fillna(0).sum() * avg_daily_demand * avg_unit_cost
    )

    # Waste reduction: EOQ ordering vs assumed 20% overstock on ad-hoc orders
    eoq_total   = sum(p["qty_ordered"] * p["unit_cost"] for p in drafted_pos)
    adhoc_total = eoq_total * 1.20   # ad-hoc orders typically 20% over
    waste_saved = round(adhoc_total - eoq_total, 2)

    # Emergency order premium avoided: 15% surcharge on urgent orders
    emergency_premium_avoided = round(total_po_value * 0.15, 2)

    total_monthly_saving = round(
        lost_sales_prevented + waste_saved + emergency_premium_avoided, 2
    )

    return {
        "total_po_value":              round(total_po_value, 2),
        "lost_sales_prevented":        round(lost_sales_prevented, 2),
        "waste_reduction":             waste_saved,
        "emergency_premium_avoided":   emergency_premium_avoided,
        "total_monthly_saving":        total_monthly_saving,
        "items_at_stockout_risk":      len(at_risk),
        "pos_drafted":                 len(drafted_pos),
    }


# ------------------------------------------------------------------
# Deterministic autonomous pipeline (no LLM required)
# ------------------------------------------------------------------
def run_autonomous_pipeline(periods: int = 30) -> dict:
    log = []

    # Step 1: Forecast
    log.append("Step 1: Running Prophet demand forecast...")
    forecast_stats = _run_forecast(periods)
    avg_demand = forecast_stats["avg_daily_demand"]
    log.append(f"  Avg daily demand: {avg_demand} units | MAE: {forecast_stats['mae']}")

    # Step 2: Inventory + ROP/EOQ + stockout dates
    log.append("Step 2: Querying inventory, calculating ROP/EOQ and stockout dates...")
    inv_df = _query_inventory(avg_demand)
    log.append(f"  {len(inv_df)} items monitored")

    for _, row in inv_df.iterrows():
        log.append(f"  {row['item_name']}: stock={row['stock_qty']} | "
                   f"ROP={row['rop']} | stockout in {row['days_to_stockout']}d ({row['stockout_date']})")

    # Step 3: Triggers
    triggered = inv_df[inv_df["needs_reorder"] == True]
    log.append(f"Step 3: Reorder check -- {len(triggered)} item(s) below ROP")

    # Step 4: Supplier selection + PO drafting
    drafted_pos  = []
    risk_alerts  = []
    supplier_log = []

    if triggered.empty:
        log.append("Step 4: No POs needed -- all stock levels healthy")
    else:
        log.append("Step 4: Selecting suppliers (price 40% / lead time 35% / reliability 25%)...")
        for _, row in triggered.iterrows():
            supplier = _select_supplier(row["item_name"])

            if "error" in supplier:
                log.append(f"  SKIP {row['item_name']}: {supplier['error']}")
                continue

            if supplier["risk_alert"]:
                risk_alerts.append(supplier["risk_alert"])
                log.append(f"  {supplier['risk_alert']}")

            supplier_log.append({
                "item":          row["item_name"],
                "winner":        supplier["supplier_name"],
                "score":         supplier["score"],
                "unit_cost":     supplier["unit_cost"],
                "lead_time":     supplier["lead_time_days"],
                "reliability":   supplier["reliability"],
                "all_scores":    supplier["all_scores"],
            })

            log.append(f"  OK {row['item_name']} -> {supplier['supplier_name']} "
                       f"(score={supplier['score']}, GBP {supplier['unit_cost']}/unit, "
                       f"{supplier['lead_time_days']}d lead, {supplier['reliability']*100:.0f}% reliable)")

            po = _draft_po(
                item_name      = row["item_name"],
                qty            = row["eoq"],
                unit_cost      = supplier["unit_cost"],
                trigger_reason = (f"Stock {row['stock_qty']} <= ROP {row['rop']} | "
                                  f"Stockout: {row['stockout_date']} | "
                                  f"Supplier: {supplier['supplier_name']} (score={supplier['score']})"),
                lead_time_days = supplier["lead_time_days"],
            )
            drafted_pos.append(po)
            log.append(f"  PO: {row['item_name']} | qty={row['eoq']} | "
                       f"total=GBP {po['total_cost']} | delivery={po['expected_delivery']}")

    # Step 5: Savings report
    savings = calculate_savings_report(inv_df, drafted_pos, avg_demand)
    log.append(f"Step 5: Savings report -- GBP {savings['total_monthly_saving']:,.2f} projected monthly saving")

    log.append(f"Pipeline complete -- {len(drafted_pos)} PO(s) created")

    return {
        "log":           log,
        "forecast":      forecast_stats,
        "inventory":     inv_df,
        "triggered":     triggered,
        "drafted_pos":   drafted_pos,
        "risk_alerts":   risk_alerts,
        "supplier_log":  supplier_log,
        "savings":       savings,
    }


# ------------------------------------------------------------------
# LangChain ReAct agent with tuned supplier selection prompt
# ------------------------------------------------------------------
def build_llm_agent():
    from langchain_classic.agents import create_react_agent, AgentExecutor
    from langchain_classic.tools import tool
    from langchain_openai import ChatOpenAI
    from langsmith import Client as LangSmithClient
    from langchain_core.prompts import PromptTemplate

    @tool
    def query_inventory(avg_daily_demand: float) -> str:
        """Query current inventory levels, ROP, EOQ and predicted stockout dates.
        Input: avg_daily_demand as a float (units per day)."""
        df = _query_inventory(avg_daily_demand)
        return df[["item_name", "stock_qty", "rop", "eoq",
                   "days_to_stockout", "stockout_date", "needs_reorder"]].to_string(index=False)

    @tool
    def run_forecast(periods: int = 30) -> str:
        """Run the Prophet demand forecast. Returns avg forecasted daily demand and std deviation.
        Input: periods (int) -- number of days to forecast."""
        return json.dumps(_run_forecast(periods))

    @tool
    def check_reorder_triggers(avg_daily_demand: float) -> str:
        """Check which inventory items have stock at or below their Reorder Point (ROP).
        Input: avg_daily_demand as a float."""
        df        = _query_inventory(avg_daily_demand)
        triggered = df[df["needs_reorder"] == True]
        if triggered.empty:
            return "No items currently require reordering."
        return triggered[["item_name", "stock_qty", "rop", "eoq",
                           "days_to_stockout", "unit_cost"]].to_string(index=False)

    @tool
    def select_supplier(item_name: str) -> str:
        """Select the best supplier for an item using price/lead-time/reliability scoring.
        Input: item_name as a string."""
        result = _select_supplier(item_name)
        return json.dumps(result)

    @tool
    def draft_po(item_name: str, qty: float, unit_cost: float,
                 trigger_reason: str, lead_time_days: int = 7) -> str:
        """Draft and save a Purchase Order. Use EOQ as qty and the selected supplier's cost.
        Inputs: item_name, qty, unit_cost, trigger_reason, lead_time_days."""
        return json.dumps(_draft_po(item_name, qty, unit_cost, trigger_reason, lead_time_days))

    # Pull base ReAct prompt and inject supplier selection rules
    base_prompt = LangSmithClient().pull_prompt("hwchase17/react")
    tuned_template = SUPPLIER_SELECTION_PROMPT + "\n\n" + base_prompt.template
    tuned_prompt = PromptTemplate(
        input_variables=base_prompt.input_variables,
        template=tuned_template
    )

    llm   = ChatOpenAI(model="gpt-4o-mini", temperature=0,
                       api_key=os.getenv("OPENAI_API_KEY", ""))
    tools = [query_inventory, run_forecast, check_reorder_triggers, select_supplier, draft_po]
    agent = create_react_agent(llm, tools, tuned_prompt)

    return AgentExecutor(agent=agent, tools=tools, verbose=True,
                         handle_parsing_errors=True, max_iterations=15)


def run_llm_agent(user_input: str = None) -> str:
    executor = build_llm_agent()
    task = user_input or (
        "1. Run the demand forecast for the next 30 days. "
        "2. Query inventory to find items below ROP and their stockout dates. "
        "3. For each triggered item, select the best supplier using the scoring formula. "
        "4. Draft a Purchase Order for each item using the winning supplier's price and lead time. "
        "5. Report any supplier risk alerts. "
        "6. Summarise total PO value and projected monthly savings."
    )
    result = executor.invoke({"input": task})
    return result["output"]
