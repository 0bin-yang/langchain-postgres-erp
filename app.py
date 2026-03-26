# =============================================================
# app.py  |  Owner: Frontend (Streamlit / Plotly)
# Responsibilities: UI layout, visualisation, user interaction
# =============================================================
import os
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime
from dotenv import load_dotenv
from db_setup import get_engine
from weather import get_current_weather
from forecast import run_forecast_pipeline
from inventory import init_inventory_table, get_inventory_with_rop_eoq
from purchase_order import init_po_table, get_purchase_orders
from suppliers import init_supplier_table, get_suppliers

load_dotenv(dotenv_path=".env")

st.set_page_config(page_title="ERP AI Dashboard [grp8]", layout="wide")
st.title("ERP AI-Powered Supply Chain Dashboard [grp8]")

# Bootstrap DB tables
init_inventory_table()
init_po_table()
init_supplier_table()

# ------------------------------------------------------------------
# Pre-load forecast once into session state (demo readiness)
# ------------------------------------------------------------------
if "forecast_result" not in st.session_state:
    try:
        engine = get_engine()
        st.session_state["forecast_result"] = run_forecast_pipeline(engine, periods=30)
    except Exception as e:
        st.session_state["forecast_result"] = None
        st.session_state["forecast_error"]  = str(e)

fc_result  = st.session_state.get("forecast_result")
avg_demand = fc_result["avg_daily_demand"] if fc_result else 50.0
std_demand = fc_result["std_daily_demand"] if fc_result else 10.0

tab1, tab2, tab3, tab4 = st.tabs([
    "Live Dashboard",
    "Forecast",
    "Agent & POs",
    "Savings Report",
])

# ==================================================================
# TAB 1 -- LIVE DASHBOARD
# ==================================================================
with tab1:
    st.subheader("Real-Time Inventory Monitor")

    try:
        inv_df    = get_inventory_with_rop_eoq(avg_demand, forecast_std=std_demand)
        triggered = inv_df[inv_df["needs_reorder"]]
        critical  = inv_df[inv_df["days_to_stockout"] <= inv_df["lead_time_days"]]

        # KPI row
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Items Monitored",   len(inv_df))
        k2.metric("Below ROP",         len(triggered),
                  delta=f"-{len(triggered)} critical", delta_color="inverse")
        k3.metric("Imminent Stockouts", len(critical),
                  delta=f"{len(critical)} at risk",   delta_color="inverse")
        k4.metric("Avg Daily Demand",  f"{avg_demand} units")

        # Risk alerts
        if not critical.empty:
            for _, row in critical.iterrows():
                st.error(
                    f"STOCKOUT ALERT -- {row['item_name']}: "
                    f"only {row['days_to_stockout']} days of stock remaining. "
                    f"Predicted stockout: {row['stockout_date']}. "
                    f"Lead time: {int(row['lead_time_days'])} days. Agent intervention required."
                )

        from suppliers import select_best_supplier
        for _, row in triggered.iterrows():
            s = select_best_supplier(row["item_name"])
            if isinstance(s, dict) and s.get("risk_alert"):
                st.warning(s["risk_alert"])

        st.divider()

        # Stock level bar chart vs ROP
        fig_stock = go.Figure()
        fig_stock.add_trace(go.Bar(
            name="Current Stock",
            x=inv_df["item_name"],
            y=inv_df["stock_qty"],
            marker_color=[
                "#e74c3c" if r else "#2ecc71"
                for r in inv_df["needs_reorder"]
            ],
            text=inv_df["stock_qty"].round(0),
            textposition="outside",
        ))
        fig_stock.add_trace(go.Scatter(
            name="Reorder Point (ROP)",
            x=inv_df["item_name"],
            y=inv_df["rop"],
            mode="markers+lines",
            marker=dict(symbol="line-ew", size=12, color="orange",
                        line=dict(width=3, color="orange")),
            line=dict(dash="dash", color="orange"),
        ))
        fig_stock.update_layout(
            title="Stock Levels vs Reorder Points",
            xaxis_title="Item", yaxis_title="Units",
            legend=dict(orientation="h"),
            hovermode="x unified",
            height=400,
        )
        st.plotly_chart(fig_stock, use_container_width=True)

        # Stockout timeline
        fig_so = px.bar(
            inv_df.sort_values("days_to_stockout"),
            x="days_to_stockout", y="item_name",
            orientation="h",
            color="days_to_stockout",
            color_continuous_scale=["#e74c3c", "#f39c12", "#2ecc71"],
            labels={"days_to_stockout": "Days Until Stockout", "item_name": "Item"},
            title="Predicted Stockout Timeline",
            text="stockout_date",
        )
        fig_so.update_traces(textposition="outside")
        fig_so.add_vline(x=7, line_dash="dash", line_color="red",
                         annotation_text="7-day danger zone")
        fig_so.update_layout(height=350, coloraxis_showscale=False)
        st.plotly_chart(fig_so, use_container_width=True)

        # Inventory table
        st.subheader("Inventory Detail")
        def _highlight(row):
            color = "#ffe0e0" if row["needs_reorder"] else ""
            return [f"background-color: {color}"] * len(row)

        st.dataframe(
            inv_df[["item_name", "stock_qty", "rop", "eoq", "safety_stock",
                    "days_to_stockout", "stockout_date", "needs_reorder"]]
            .style.apply(_highlight, axis=1),
            use_container_width=True
        )

    except Exception as e:
        st.error("Dashboard Error")
        st.code(str(e))

# ==================================================================
# TAB 2 -- FORECAST
# ==================================================================
with tab2:
    st.subheader("Demand Forecast (Prophet + Weather Regressors)")

    if not fc_result:
        st.error("Forecast failed to load")
        st.code(st.session_state.get("forecast_error", "Unknown error"))
    else:
        metrics    = fc_result["metrics"]
        df_prophet = fc_result["df_prophet"]
        forecast   = fc_result["forecast"]
        future     = fc_result["future"]

        st.success("Model learning complete")

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("MAE",          metrics["mae"])
        c2.metric("RMSE",         metrics["rmse"])
        c3.metric("Train rows",   metrics["train_n"])
        c4.metric("Holdout rows", metrics["holdout_n"])

        holdout = metrics["actual"].merge(metrics["predicted"][["ds", "yhat"]], on="ds")
        holdout.columns = ["Date", "Actual Orders", "Predicted Orders"]
        st.dataframe(holdout)

        fig_fc = go.Figure()
        fig_fc.add_trace(go.Scatter(
            x=df_prophet["ds"], y=df_prophet["y"],
            name="Historical Orders", mode="lines",
            line=dict(color="steelblue", width=2)
        ))
        fig_fc.add_trace(go.Scatter(
            x=forecast["ds"], y=forecast["yhat"],
            name="Forecast", mode="lines",
            line=dict(color="orange", width=2)
        ))
        fig_fc.add_trace(go.Scatter(
            x=pd.concat([forecast["ds"], forecast["ds"][::-1]]),
            y=pd.concat([forecast["yhat_upper"], forecast["yhat_lower"][::-1]]),
            fill="toself", fillcolor="rgba(255,165,0,0.15)",
            line=dict(color="rgba(255,255,255,0)"),
            name="95% Confidence Interval"
        ))
        fig_fc.add_vline(
            x=datetime.now().timestamp() * 1000,
            line_dash="dot", line_color="grey",
            annotation_text="Today", annotation_position="top right"
        )
        fig_fc.update_layout(
            title="30-Day Demand Forecast with Confidence Intervals",
            xaxis_title="Date", yaxis_title="Orders",
            legend=dict(orientation="h"), hovermode="x unified", height=450
        )
        st.plotly_chart(fig_fc, use_container_width=True)

        st.subheader("Forecast Table (Next 30 Days)")
        st.dataframe(
            future[["ds", "yhat", "yhat_lower", "yhat_upper"]]
            .rename(columns={"ds": "Date", "yhat": "Forecast",
                              "yhat_lower": "Lower", "yhat_upper": "Upper"})
            .reset_index(drop=True)
        )

        try:
            engine       = get_engine()
            weather_live = get_current_weather("Kolkata")
            st.subheader("Live Weather (External Regressor)")
            st.dataframe(weather_live)
        except Exception:
            pass

# ==================================================================
# TAB 3 -- AGENT & POs
# ==================================================================
with tab3:
    st.subheader("LangChain ReAct Agent -- Autonomous Procurement")
    st.info(f"Forecast: avg daily demand = {avg_demand} units/day  |  std = {std_demand}")

    with st.expander("Supplier Catalogue & Scoring Rules"):
        st.markdown("""
**Supplier selection formula (v4 -- final tuned prompt):**
```
score = 0.40 x price_score  +  0.35 x lead_score  +  0.25 x reliability
```
- Hard floor: suppliers with reliability < 0.70 are rejected
- Risk alert triggered when winning supplier reliability < 0.85
        """)
        try:
            sup_df = get_suppliers()
            st.dataframe(sup_df[["supplier_name", "item_name", "unit_cost",
                                  "lead_time_days", "reliability"]], use_container_width=True)
        except Exception as e:
            st.code(str(e))

    st.divider()

    st.subheader("Autonomous Pipeline")
    if st.button("Run Autonomous Pipeline", type="primary"):
        with st.spinner("Agent running full pipeline..."):
            try:
                from agent import run_autonomous_pipeline
                res = run_autonomous_pipeline(periods=30)

                if res["risk_alerts"]:
                    for alert in res["risk_alerts"]:
                        st.warning(alert)

                with st.expander("Pipeline Log", expanded=True):
                    for line in res["log"]:
                        st.text(line)

                if res["supplier_log"]:
                    st.subheader("Supplier Selection Scores")
                    rows = []
                    for s in res["supplier_log"]:
                        for sc in s["all_scores"]:
                            rows.append({
                                "Item":        s["item"],
                                "Supplier":    sc["supplier_name"],
                                "Unit Cost":   sc["unit_cost"],
                                "Lead (days)": sc["lead_time_days"],
                                "Reliability": f"{sc['reliability']*100:.0f}%",
                                "Score":       round(sc["score"], 4),
                                "Selected":    sc["supplier_name"] == s["winner"],
                            })
                    score_df = pd.DataFrame(rows)
                    def _hl_winner(row):
                        return ["background-color: #d4edda" if row["Selected"] else "" for _ in row]
                    st.dataframe(score_df.style.apply(_hl_winner, axis=1), use_container_width=True)

                if res["drafted_pos"]:
                    st.subheader(f"{len(res['drafted_pos'])} Purchase Order(s) Drafted")
                    st.json(res["drafted_pos"])

                sv = res["savings"]
                st.subheader("Projected Monthly Savings")
                s1, s2, s3, s4 = st.columns(4)
                s1.metric("Lost Sales Prevented",      f"GBP {sv['lost_sales_prevented']:,.0f}")
                s2.metric("Waste Reduction (EOQ)",     f"GBP {sv['waste_reduction']:,.0f}")
                s3.metric("Emergency Premium Avoided", f"GBP {sv['emergency_premium_avoided']:,.0f}")
                s4.metric("Total Monthly Saving",      f"GBP {sv['total_monthly_saving']:,.0f}")

                st.session_state["pipeline_result"] = res

            except Exception as e:
                st.error("Pipeline Error")
                st.code(str(e))

    st.divider()

    st.subheader("LangChain ReAct Agent (LLM)")
    if not os.getenv("OPENAI_API_KEY", ""):
        st.warning("OPENAI_API_KEY not set in .env")
    else:
        user_prompt = st.text_area(
            "Agent task",
            value=(
                "Run the demand forecast, check which items breach their ROP, "
                "select the best supplier for each using the scoring formula, "
                "draft Purchase Orders, flag any supplier risk alerts, "
                "and report projected monthly savings."
            ),
            height=80
        )
        if st.button("Run LLM Agent"):
            with st.spinner("LLM agent running..."):
                try:
                    from agent import run_llm_agent
                    output = run_llm_agent(user_prompt)
                    st.success("Agent completed")
                    st.markdown(output)
                except Exception as e:
                    st.error("LLM Agent Error")
                    st.code(str(e))

    st.divider()

    st.subheader("Purchase Order History")
    try:
        po_df = get_purchase_orders()
        if po_df.empty:
            st.info("No purchase orders yet -- run the pipeline above.")
        else:
            st.dataframe(po_df, use_container_width=True)
    except Exception as e:
        st.error("PO History Error")
        st.code(str(e))

# ==================================================================
# TAB 4 -- SAVINGS REPORT
# ==================================================================
with tab4:
    st.subheader("Projected Monthly Savings Report")
    st.markdown(
        "The agent acts as a cost-saver by preventing stockouts, eliminating "
        "wasteful over-ordering, and avoiding emergency procurement premiums -- all autonomously."
    )

    res = st.session_state.get("pipeline_result")
    if not res:
        st.info("Run the Autonomous Pipeline in the Agent tab first to generate the savings report.")
    else:
        sv  = res["savings"]

        st.markdown("### Monthly Impact")
        m1, m2, m3 = st.columns(3)
        m1.metric("Lost Sales Prevented",
                  f"GBP {sv['lost_sales_prevented']:,.0f}",
                  help="Revenue saved by restocking before stockout")
        m2.metric("Waste Reduction",
                  f"GBP {sv['waste_reduction']:,.0f}",
                  help="Savings from EOQ vs ad-hoc over-ordering (20% excess)")
        m3.metric("Emergency Premium Avoided",
                  f"GBP {sv['emergency_premium_avoided']:,.0f}",
                  help="15% surcharge avoided by proactive ordering")

        st.divider()
        st.metric("Total Projected Monthly Saving",
                  f"GBP {sv['total_monthly_saving']:,.0f}",
                  delta="vs reactive manual procurement")

        # Waterfall chart
        fig_sav = go.Figure(go.Waterfall(
            name="Savings",
            orientation="v",
            measure=["relative", "relative", "relative", "total"],
            x=["Lost Sales\nPrevented", "Waste\nReduction",
               "Emergency Premium\nAvoided", "Total Monthly\nSaving"],
            y=[sv["lost_sales_prevented"], sv["waste_reduction"],
               sv["emergency_premium_avoided"], 0],
            connector=dict(line=dict(color="rgb(63,63,63)")),
            increasing=dict(marker=dict(color="#2ecc71")),
            totals=dict(marker=dict(color="#3498db")),
            text=[f"GBP {sv['lost_sales_prevented']:,.0f}",
                  f"GBP {sv['waste_reduction']:,.0f}",
                  f"GBP {sv['emergency_premium_avoided']:,.0f}",
                  f"GBP {sv['total_monthly_saving']:,.0f}"],
            textposition="outside",
        ))
        fig_sav.update_layout(
            title="Monthly Savings Breakdown (Waterfall)",
            yaxis_title="GBP Savings",
            height=400,
        )
        st.plotly_chart(fig_sav, use_container_width=True)

        # Pie chart
        fig_pie = px.pie(
            values=[sv["lost_sales_prevented"], sv["waste_reduction"],
                    sv["emergency_premium_avoided"]],
            names=["Lost Sales Prevented", "Waste Reduction", "Emergency Premium Avoided"],
            title="Savings Composition",
            color_discrete_sequence=["#2ecc71", "#3498db", "#e67e22"],
        )
        st.plotly_chart(fig_pie, use_container_width=True)

        # Narrative table
        st.markdown("### How the Agent Saved This")
        st.markdown(f"""
| Action | Impact |
|---|---|
| Detected {sv['items_at_stockout_risk']} items at imminent stockout risk | Prevented lost sales worth GBP {sv['lost_sales_prevented']:,.0f} |
| Drafted {sv['pos_drafted']} EOQ-optimised POs | Eliminated GBP {sv['waste_reduction']:,.0f} in over-ordering waste |
| Proactive ordering before stockout | Avoided GBP {sv['emergency_premium_avoided']:,.0f} in emergency surcharges |
| Supplier scoring (price / lead / reliability) | Selected lowest-cost reliable suppliers automatically |
| **Total monthly saving** | **GBP {sv['total_monthly_saving']:,.0f}** |
        """)

        # Prompt tuning log
        st.markdown("### Agent Prompt Tuning Log")
        st.markdown("""
| Version | Prompt Strategy | Problem | Outcome |
|---|---|---|---|
| v1 | Pick cheapest supplier | Ignored lead time -- caused stockouts | Rejected |
| v2 | Best price + shortest lead time | Flip-flopped, ignored reliability | Rejected |
| v3 | Weighted score formula | No reasoning trace, no risk flag | Partial |
| v4 | Score formula + reliability floor (0.70) + risk alert (<0.85) + mandatory trace | -- | Final |
        """)

if st.button("Refresh"):
    st.rerun()
