# backend/enrichment/match_meta.py
# Resolve rich match metadata (competition, date, stadium, managers)
# from the StatsBomb open data embedded lookup table.
# No external API needed — all known match IDs are hardcoded here.

from __future__ import annotations
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from config import LINEUPS_DIR

logger = logging.getLogger("[META]")


@dataclass
class FullMatchMeta:
    competition: str = ""
    season: str = ""
    date: str = ""          # ISO format: 2021-06-11
    kick_off: str = ""      # HH:MM
    stadium: str = ""
    city: str = ""
    country: str = ""
    home_manager: str = ""
    away_manager: str = ""
    home_team: str = ""
    away_team: str = ""
    # For weather lookup
    latitude: float = 0.0
    longitude: float = 0.0


# ---------------------------------------------------------------------------
# Known StatsBomb open-data match metadata
# Sources: StatsBomb's public repository and Wikipedia for venue coordinates
# ---------------------------------------------------------------------------

_KNOWN_MATCHES: dict[str, dict] = {
    # UEFA Euro 2020 — played in 2021
    "3788741": {
        "competition": "UEFA Euro 2020",
        "season": "2021",
        "date": "2021-06-11",
        "kick_off": "21:00",
        "stadium": "Stadio Olimpico",
        "city": "Rome",
        "country": "Italy",
        "home_manager": "Roberto Mancini",
        "away_manager": "Şenol Güneş",
        "latitude": 41.9335,
        "longitude": 12.4547,
    },
    "3788768": {
        "competition": "UEFA Euro 2020",
        "season": "2021",
        "date": "2021-06-21",
        "kick_off": "21:00",
        "stadium": "Krestovsky Stadium",
        "city": "Saint Petersburg",
        "country": "Russia",
        "home_manager": "Roberto Martínez",
        "away_manager": "Markku Kanerva",
        "latitude": 59.9727,
        "longitude": 30.2205,
    },
    "3788769": {
        "competition": "UEFA Euro 2020",
        "season": "2021",
        "date": "2021-06-21",
        "kick_off": "18:00",
        "stadium": "Parken Stadium",
        "city": "Copenhagen",
        "country": "Denmark",
        "home_manager": "Kasper Hjulmand",
        "away_manager": "Stanislav Cherchesov",
        "latitude": 55.7028,
        "longitude": 12.5783,
    },
    # FIFA World Cup 2018
    "7559": {
        "competition": "FIFA World Cup",
        "season": "2018",
        "date": "2018-06-25",
        "kick_off": "16:00",
        "stadium": "Volgograd Arena",
        "city": "Volgograd",
        "country": "Russia",
        "home_manager": "Héctor Cúper",
        "away_manager": "Juan Antonio Pizzi",
        "latitude": 48.7478,
        "longitude": 44.3518,
    },
    "7562": {
        "competition": "FIFA World Cup",
        "season": "2018",
        "date": "2018-06-26",
        "kick_off": "18:00",
        "stadium": "Fisht Olympic Stadium",
        "city": "Sochi",
        "country": "Russia",
        "home_manager": "Bert van Marwijk",
        "away_manager": "Ricardo Gareca",
        "latitude": 43.4119,
        "longitude": 39.9545,
    },
    # La Liga
    "69249": {
        "competition": "La Liga",
        "season": "2010-11",
        "date": "2010-11-29",
        "kick_off": "20:00",
        "stadium": "Camp Nou",
        "city": "Barcelona",
        "country": "Spain",
        "home_manager": "Pep Guardiola",
        "away_manager": "José Mourinho",
        "latitude": 41.3809,
        "longitude": 2.1228,
    },
    "69251": {
        "competition": "La Liga",
        "season": "2011-12",
        "date": "2011-09-17",
        "kick_off": "17:00",
        "stadium": "Mestalla",
        "city": "Valencia",
        "country": "Spain",
        "home_manager": "Unai Emery",
        "away_manager": "Pep Guardiola",
        "latitude": 39.4748,
        "longitude": -0.3582,
    },
}


def get_match_meta(match_id: str, home_team: str = "", away_team: str = "") -> FullMatchMeta:
    """Return full match metadata for a given match_id."""
    meta = FullMatchMeta(home_team=home_team, away_team=away_team)
    known = _KNOWN_MATCHES.get(str(match_id))
    if known:
        meta.competition = known.get("competition", "")
        meta.season = known.get("season", "")
        meta.date = known.get("date", "")
        meta.kick_off = known.get("kick_off", "")
        meta.stadium = known.get("stadium", "")
        meta.city = known.get("city", "")
        meta.country = known.get("country", "")
        meta.home_manager = known.get("home_manager", "")
        meta.away_manager = known.get("away_manager", "")
        meta.latitude = known.get("latitude", 0.0)
        meta.longitude = known.get("longitude", 0.0)
    else:
        logger.warning(f"No metadata for match {match_id} — using defaults")
    return meta
