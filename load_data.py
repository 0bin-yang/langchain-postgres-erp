import pandas as pd
from db_setup import get_engine

def load_and_prepare_data():
    # --- Load CSV ---
    df = pd.read_csv("~/build_dir/langchainPostgresql-project/History/DDFO.csv")

    print("🔹 Raw Columns:")
    print(df.columns)

    # --- Drop unwanted column ---
    if "Unnamed: 0" in df.columns:
        df = df.drop(columns=["Unnamed: 0"])

    # --- Rename target column ---
    df.rename(columns={
        "Target (Total orders)": "orders"
    }, inplace=True)

    # --- Create timestamp (CRITICAL) ---
    df["timestamp"] = pd.date_range(
        start="2026-01-01",
        periods=len(df),
        freq="D"
    )

    # --- Clean column names (robust approach) ---
    df.columns = (
        df.columns
        .str.strip()
        .str.lower()
        .str.replace(" ", "_")
        .str.replace(r"[()]", "", regex=True)
        .str.replace(r"[^a-z0-9_]", "", regex=True)
    )

    print("\n🔹 Cleaned Columns:")
    print(df.columns)

    # --- Ensure correct order ---
    if "timestamp" not in df.columns or "orders" not in df.columns:
        raise ValueError(" Required columns missing after cleaning")

    cols = ["timestamp", "orders"] + [c for c in df.columns if c not in ["timestamp", "orders"]]
    df = df[cols]

    print("\n Cleaned Data Preview:")
    print(df.head())

    return df


def load_to_db():
    engine = get_engine()
    df = load_and_prepare_data()

    # --- Push to PostgreSQL ---
    df.to_sql("erp_data", engine, if_exists="replace", index=False)

    print("\n ERP data loaded into PostgreSQL")


if __name__ == "__main__":
    load_to_db()
