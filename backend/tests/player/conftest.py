# backend/tests/player/conftest.py
"""Shared fixtures for player module tests."""

from __future__ import annotations

import sys
import os
from pathlib import Path

# DEBUG: Print detailed info
print(f"[conftest] __file__: {__file__}", flush=True)
print(f"[conftest] sys.path[0]: {sys.path[0]}", flush=True)
print(f"[conftest] CWD: {os.getcwd()}", flush=True)

# Calculate backend dir: tests/player/conftest.py -> tests/player -> tests -> backend
_file = Path(__file__)
_backend_dir = (_file.parent / ".." / "..").resolve()
print(f"[conftest] Calculated _backend_dir: {_backend_dir}", flush=True)
print(f"[conftest] _backend_dir exists: {_backend_dir.exists()}", flush=True)

# Add to sys.path if not already there
_backend_str = str(_backend_dir)
if _backend_str not in sys.path:
    sys.path.insert(0, _backend_str)
    print(f"[conftest] Added {_backend_str} to sys.path", flush=True)
else:
    print(f"[conftest] {_backend_str} already in sys.path", flush=True)

print(f"[conftest] sys.path now: {sys.path[:3]}...", flush=True)

# Now import
print(f"[conftest] About to import player.loader...", flush=True)
try:
    import player.loader
    print(f"[conftest] player.loader imported from: {player.loader.__file__}", flush=True)
    from player.loader import MatchEvent
    print(f"[conftest] MatchEvent imported: {MatchEvent}", flush=True)
except ImportError as e:
    print(f"[conftest] Import FAILED: {e}", flush=True)
    raise

import pytest
import json


# ---------------------------------------------------------------------------
# Sample match data
# ---------------------------------------------------------------------------

SAMPLE_MATCH_ID = "test_match_001"
SAMPLE_HOME_TEAM = "Home United"
SAMPLE_AWAY_TEAM = "Away City"


def make_event(
    idx: int = 0,
    timestamp: str = "00:00:00.000",
    period: int = 1,
    event_type: str = "Pass",
    team: str = "Home United",
    player: str = "Test Player",
    location: list | None = None,
    extra: dict | None = None,
) -> dict:
    """Build a raw StatsBomb event dict."""
    loc: list = location if location is not None else [60.0, 40.0]
    ev: dict = {
        "id": f"event_{idx}",
        "timestamp": timestamp,
        "period": period,
        "type": {"name": event_type},
        "team": {"name": team},
        "player": {"name": player} if player else {"name": "Unknown"},
        "location": loc,
    }
    if extra is not None:
        ev.update(extra)
    return ev


@pytest.fixture
def sample_match_data():
    """Minimal match JSON with events across both teams."""
    return [
        make_event(0, "00:00:00.000", 1, "Pass", "Home United", "Player A", [20.0, 40.0]),
        make_event(1, "00:01:00.000", 1, "Pass", "Away City", "Player B", [80.0, 40.0]),
        make_event(2, "00:02:30.000", 1, "Shot", "Home United", "Player C", [95.0, 45.0], {
            "shot": {"statsbomb_xg": 0.35, "outcome": {"name": "Goal"}}
        }),
        make_event(3, "00:03:00.000", 1, "Pass", "Away City", "Player D", [70.0, 30.0]),
        make_event(4, "00:50:00.000", 2, "Pass", "Home United", "Player A", [50.0, 40.0]),
        make_event(5, "00:51:00.000", 2, "Foul Committed", "Away City", "Player E", [60.0, 35.0], {
            "foul_committed": {"card": {"name": "Yellow Card"}}
        }),
    ]


@pytest.fixture
def sample_lineup_data():
    """Sample lineup JSON."""
    return [
        {
            "team_name": "Home United",
            "lineup": [
                {"player_name": "Player A", "jersey_number": 1, "positions": [{"position": "Goalkeeper"}]},
                {"player_name": "Player C", "jersey_number": 9, "positions": [{"position": "Forward"}]},
            ]
        },
        {
            "team_name": "Away City",
            "lineup": [
                {"player_name": "Player B", "jersey_number": 1, "positions": [{"position": "Goalkeeper"}]},
            ]
        }
    ]


@pytest.fixture
def mock_match_file(tmp_path, sample_match_data, sample_lineup_data):
    """Create temporary match and lineup JSON files."""
    match_file = tmp_path / f"{SAMPLE_MATCH_ID}.json"
    with open(match_file, "w", encoding="utf-8") as fp:
        json.dump(sample_match_data, fp)

    lineup_file = tmp_path / f"{SAMPLE_MATCH_ID}.json"
    with open(lineup_file, "w", encoding="utf-8") as fp:
        json.dump(sample_lineup_data, fp)

    return {
        "match_file": str(match_file),
        "lineup_file": str(lineup_file),
        "match_id": SAMPLE_MATCH_ID,
    }


@pytest.fixture
def mock_match_events(sample_match_data):
    """Create MatchEvent objects from sample data."""
    events: list[MatchEvent] = []
    for i, ev in enumerate(sample_match_data):
        events.append(MatchEvent(
            id=ev["id"],
            timestamp_sec=90.0 * i,  # 90s apart for easy testing
            event_type=ev["type"]["name"],
            team=ev["team"]["name"],
            player=ev["player"]["name"],
            position=tuple(ev["location"]),
            end_position=None,
            details={},
            index=i,
            is_home=ev["team"]["name"] == SAMPLE_HOME_TEAM,
        ))
    return events


@pytest.fixture
def critical_events():
    """Events for SpeedCurve testing."""
    return [
        MatchEvent(
            id="shot1", timestamp_sec=300.0, event_type="Shot",
            team="Home United", player="Striker", position=(95.0, 45.0),
            end_position=None, details={"shot_outcome": "Goal"}, index=0, is_home=True,
        ),
        MatchEvent(
            id="shot2", timestamp_sec=1800.0, event_type="Shot",
            team="Away City", player="Forward", position=(90.0, 40.0),
            end_position=None, details={"shot_outcome": "Saved"}, index=1, is_home=False,
        ),
    ]

print("[conftest] Module loaded successfully", flush=True)