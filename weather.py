import os
import requests
import pandas as pd
from datetime import datetime
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
env_path = os.path.join(BASE_DIR, ".env")

load_dotenv(dotenv_path=env_path)

API_KEY = os.getenv("OPENWEATHER_API_KEY")

print("DEBUG API KEY:", API_KEY)
BASE_URL = "https://api.openweathermap.org/data/2.5/weather"

def get_current_weather(city="Kolkata"):
    if not API_KEY:
        raise ValueError("Missing OPENWEATHER_API_KEY")

    params = {
        "q": city,
        "appid": API_KEY,
        "units": "metric"
    }

    response = requests.get(BASE_URL, params=params)

    if response.status_code != 200:
        raise Exception(f"Weather API error: {response.text}")

    data = response.json()

    # Extract relevant features (for regression)
    weather_df = pd.DataFrame([{
        "timestamp": datetime.utcnow(),
        "city": city,
        "temp": data["main"]["temp"],
        "feels_like": data["main"]["feels_like"],
        "humidity": data["main"]["humidity"],
        "pressure": data["main"]["pressure"],
        "wind_speed": data["wind"]["speed"],
        "clouds": data["clouds"]["all"]
    }])

    return weather_df

def get_weather_forecast(city="Kolkata", days=5):
    url = f"http://api.openweathermap.org/data/2.5/forecast?q={city}&appid={API_KEY}&units=metric"

    response = requests.get(url).json()

    if "list" not in response:
        raise ValueError("Weather API error: " + str(response))

    data = []

    for item in response["list"]:
        data.append({
            "ds": pd.to_datetime(item["dt_txt"]),
            "temp": item["main"]["temp"],
            "humidity": item["main"]["humidity"],
            "pressure": item["main"]["pressure"],
            "wind_speed": item["wind"]["speed"]
        })

    df = pd.DataFrame(data)
    df["ds"] = pd.to_datetime(df["ds"]).dt.floor("D")
    df = df.groupby("ds").mean(numeric_only=True).reset_index()

    return df.head(days)
