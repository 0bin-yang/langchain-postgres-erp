import os
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
import os

load_dotenv()

DB_PARAMS = {
    "host": os.getenv("localhost"),
    "database": os.getenv("erp_system"),
    "user": os.getenv("erp_system_admin"),
    "password": os.getenv("12345"),
    "port": "5432"
}

def get_engine():
    conn_str = (
        f"postgresql+psycopg2://{DB_PARAMS['user']}:{DB_PARAMS['password']}"
        f"@{DB_PARAMS['host']}:{DB_PARAMS['port']}/{DB_PARAMS['database']}"
    )
    return create_engine(conn_str, pool_pre_ping=True)

def test_connection():
    engine = get_engine()
    with engine.connect() as conn:
        result = conn.execute(text("SELECT 1"))
        print("DB Connected:", result.scalar())
