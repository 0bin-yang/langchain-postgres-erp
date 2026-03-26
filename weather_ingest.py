from weather import get_current_weather
from db_setup import get_engine
from sqlalchemy import text

def ingest_weather():
    engine = get_engine()

    #  DEBUG: which DB are we writing to?
    with engine.connect() as conn:
        db_name = conn.execute(text("SELECT current_database();")).scalar()
        print("WRITING TO DB:", db_name)

    df = get_current_weather("Kolkata")

    print("DEBUG DF:")
    print(df)

    df.to_sql("weather_data", engine, if_exists="append", index=False)

    print("  Weather data inserted")

if __name__ == "__main__":
    ingest_weather()
