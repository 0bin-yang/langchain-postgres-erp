import pandas as pd
from db_setup import get_engine

engine = get_engine()

# Replace with your actual dataset
df = pd.read_csv("~/build_dir/langchainPostgresql-project/History/HistoricalData_1774389462421.csv")

df.to_sql("erp_data", engine, if_exists="replace", index=False)

print(" Data loaded:", df.shape)
