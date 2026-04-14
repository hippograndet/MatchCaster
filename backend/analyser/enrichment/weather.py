# backend/analyser/enrichment/weather.py
# Fetch historical match-day weather from Open-Meteo (free, no API key).
# https://open-meteo.com/en/docs/historical-weather-api

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

import httpx

logger = logging.getLogger("[WEATHER]")

OPEN_METEO_URL = "https://archive-api.open-meteo.com/v1/archive"
TIMEOUT_SEC = 6.0


@dataclass
class WeatherConditions:
    temperature_c: float = 0.0
    wind_speed_kph: float = 0.0
    precipitation_mm: float = 0.0
    description: str = ""       # e.g. "Clear, 22°C, light breeze"
    available: bool = False


def _describe(temp_c: float, wind_kph: float, precip_mm: float) -> str:
    parts = []

    # Temperature
    if temp_c < 5:
        parts.append(f"cold ({temp_c:.0f}°C)")
    elif temp_c < 15:
        parts.append(f"cool ({temp_c:.0f}°C)")
    elif temp_c < 25:
        parts.append(f"{temp_c:.0f}°C")
    else:
        parts.append(f"warm ({temp_c:.0f}°C)")

    # Wind
    if wind_kph < 10:
        parts.append("calm")
    elif wind_kph < 25:
        parts.append(f"light breeze ({wind_kph:.0f} km/h)")
    elif wind_kph < 45:
        parts.append(f"breezy ({wind_kph:.0f} km/h)")
    else:
        parts.append(f"windy ({wind_kph:.0f} km/h)")

    # Rain
    if precip_mm > 5:
        parts.append("heavy rain")
    elif precip_mm > 1:
        parts.append("light rain")
    elif precip_mm > 0:
        parts.append("drizzle")

    return ", ".join(parts)


async def fetch_weather(
    latitude: float,
    longitude: float,
    date: str,          # ISO: "2021-06-11"
    kick_off_hour: int = 20,
) -> WeatherConditions:
    """
    Fetch hourly weather for the match date at kick-off hour.
    Returns WeatherConditions; available=False on any failure.
    """
    if not latitude or not longitude or not date:
        return WeatherConditions(available=False)

    params = {
        "latitude": latitude,
        "longitude": longitude,
        "start_date": date,
        "end_date": date,
        "hourly": "temperature_2m,precipitation,windspeed_10m",
        "wind_speed_unit": "kmh",
        "temperature_unit": "celsius",
        "timezone": "auto",
    }

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_SEC) as client:
            resp = await client.get(OPEN_METEO_URL, params=params)
            resp.raise_for_status()
            data = resp.json()

        hourly = data.get("hourly", {})
        temps = hourly.get("temperature_2m", [])
        winds = hourly.get("windspeed_10m", [])
        precip = hourly.get("precipitation", [])

        # Find the hour closest to kick-off
        idx = min(kick_off_hour, len(temps) - 1) if temps else 0

        temp = float(temps[idx]) if temps else 0.0
        wind = float(winds[idx]) if winds else 0.0
        rain = float(precip[idx]) if precip else 0.0

        return WeatherConditions(
            temperature_c=temp,
            wind_speed_kph=wind,
            precipitation_mm=rain,
            description=_describe(temp, wind, rain),
            available=True,
        )

    except Exception as exc:
        logger.debug(f"Weather fetch failed: {exc}")
        return WeatherConditions(available=False)
