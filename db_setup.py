import os
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv(dotenv_path=".env")

# Read environment variables correctly
DB_PARAMS = {
    "host": os.getenv("DB_HOST"),
    "database": os.getenv("DB_NAME"),
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD"),
    "port": os.getenv("DB_PORT", "5432")
}

#  Validate all required params (fail fast)
for key, value in DB_PARAMS.items():
    if not value:
        raise ValueError(f"Missing environment variable: {key.upper()}")

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
        print(" DB Connected:", result.scalar())
