from sqlalchemy import create_engine, text

# Replace with your actual credentials
DB_PARAMS = {
    'host': 'localhost',
    'database': 'postgres', # Default DB name
    'user': 'erp_system_admin',     # Default user
    'password': '12345', 
    'port': '5432'
}

DATABASE_URL = f"postgresql://{DB_PARAMS['user']}:{DB_PARAMS['password']}@{DB_PARAMS['host']}:{DB_PARAMS['port']}/{DB_PARAMS['database']}"

def check_connection():
    try:
        # 1. Check if URL format is valid
        engine = create_engine(DATABASE_URL)
        
        # 2. Try to connect and execute a simple query
        with engine.connect() as conn:
            result = conn.execute(text("SELECT version();"))
            print("  Connection Successful!")
            print(f"PostgreSQL Version: {result.fetchone()[0]}")
            
    except Exception as e:
        print(" Connection Failed.")
        print(f"Error details: {e}")

if __name__ == "__main__":
    check_connection()
