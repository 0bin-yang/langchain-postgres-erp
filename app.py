import streamlit as st
import pandas as pd
from sqlalchemy import text
from db_setup import get_engine

st.set_page_config(layout="wide")

st.title("ERP Dashboard")

engine = get_engine()

query = "SELECT * FROM erp_data LIMIT 100"

df = pd.read_sql_query(query, engine)

st.dataframe(df)

# Basic visualization
numeric_cols = df.select_dtypes(include=["int64", "float64"]).columns

if len(numeric_cols) > 0:
    st.line_chart(df[numeric_cols[0]])
