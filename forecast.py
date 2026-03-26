# =============================================================
# forecast.py  |  Owner: Data/Forecasting (Prophet)
# Responsibilities: model training, holdout evaluation,
#                   future demand prediction
# =============================================================
import numpy as np
import pandas as pd
from prophet import Prophet
from weather import get_weather_forecast


def train_prophet_model(merged_df):
    df = merged_df.copy()

    if "ds" not in df.columns:
        df = df.rename(columns={"timestamp": "ds", "orders": "y"}, errors="ignore")

    df["ds"] = pd.to_datetime(df["ds"]).dt.floor("D")
    df = df.groupby("ds").mean(numeric_only=True).reset_index()

    possible_regs = ["temp", "humidity", "pressure", "wind_speed"]
    regressors = [r for r in possible_regs if r in df.columns]

    # --- Holdout split: last 10 rows for testing ---
    HOLDOUT = 10
    train_df = df.iloc[:-HOLDOUT].copy()
    test_df  = df.iloc[-HOLDOUT:].copy()

    model = Prophet(daily_seasonality=False, weekly_seasonality=True, yearly_seasonality=False)
    for reg in regressors:
        model.add_regressor(reg)

    model.fit(train_df[["ds", "y"] + regressors])

    # --- Evaluate on holdout ---
    test_forecast = model.predict(test_df[["ds"] + regressors])
    mae  = np.mean(np.abs(test_forecast["yhat"].values - test_df["y"].values))
    rmse = np.sqrt(np.mean((test_forecast["yhat"].values - test_df["y"].values) ** 2))

    metrics = {
        "mae":       round(mae, 2),
        "rmse":      round(rmse, 2),
        "holdout_n": HOLDOUT,
        "train_n":   len(train_df),
        "actual":    test_df[["ds", "y"]].reset_index(drop=True),
        "predicted": test_forecast[["ds", "yhat", "yhat_lower", "yhat_upper"]].reset_index(drop=True),
    }

    return model, df, regressors, metrics


def run_forecast_pipeline(engine, periods: int = 30) -> dict:
    """Single entry point for the full forecast pipeline.
    Called by Frontend (app.py) and Backend (agent.py).
    Returns model, df_prophet, regressors, metrics, forecast df.
    """
    erp_df     = pd.read_sql("SELECT * FROM erp_data", engine)
    weather_df = pd.read_sql("SELECT * FROM weather_data", engine)

    erp_df["timestamp"]     = pd.to_datetime(erp_df["timestamp"])
    weather_df["timestamp"] = pd.to_datetime(weather_df["timestamp"])
    erp_df     = erp_df.sort_values("timestamp")
    weather_df = weather_df.sort_values("timestamp")

    merged_df = pd.merge_asof(erp_df, weather_df, on="timestamp", direction="nearest")
    model, df_prophet, regressors, metrics = train_prophet_model(merged_df)
    forecast = make_forecast(model, df_prophet, regressors, periods=periods)
    future   = forecast[forecast["ds"] > df_prophet["ds"].max()]

    return {
        "model":      model,
        "df_prophet": df_prophet,
        "regressors": regressors,
        "metrics":    metrics,
        "forecast":   forecast,
        "future":     future,
        "avg_daily_demand": round(float(future["yhat"].mean()), 2),
        "std_daily_demand": round(float(future["yhat"].std()),  2),
        "peak_demand":      round(float(future["yhat"].max()),  2),
    }


def make_forecast(model, df, regressors, periods=30):
    future_dates = model.make_future_dataframe(periods=periods)
    future_dates["ds"] = pd.to_datetime(future_dates["ds"]).dt.floor("D")

    weather_future = get_weather_forecast("Kolkata", periods)
    weather_future["ds"] = pd.to_datetime(weather_future["ds"]).dt.floor("D")
    weather_future = weather_future.drop_duplicates(subset=["ds"])

    future = future_dates[["ds"]].copy()

    available_regs = [r for r in regressors if r in weather_future.columns]
    if available_regs:
        future = future.merge(weather_future[["ds"] + available_regs], on="ds", how="left")
    for reg in regressors:
        if reg not in future.columns:
            future[reg] = None

    for reg in regressors:
        future[reg] = pd.to_numeric(future[reg], errors="coerce")
        last_known = pd.to_numeric(df[reg], errors="coerce").dropna().iloc[-1]
        future[reg] = future[reg].fillna(last_known)

    return model.predict(future)
