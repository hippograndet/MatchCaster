# backend/director/classifier.py
# Rule-based event priority classifier + sequence detector.

from __future__ import annotations

import logging
from collections import deque

from config import PRIORITY_WEIGHTS
from replay.loader import MatchEvent

logger = logging.getLogger("[CLASSIFIER]")

# ---------------------------------------------------------------------------
# Priority levels
# ---------------------------------------------------------------------------
CRITICAL = "critical"
NOTABLE = "notable"
ROUTINE = "routine"

# Events that are ALWAYS critical regardless of sub-type
CRITICAL_EVENT_TYPES = {
    "goal",        # Sometimes embedded in Shot outcome
    "own goal",
}

# Map StatsBomb event_type → base weight
_TYPE_WEIGHT_MAP: dict[str, int] = {
    "Pass":             PRIORITY_WEIGHTS.get("pass", 5),
    "Carry":            PRIORITY_WEIGHTS.get("carry", 3),
    "Pressure":         PRIORITY_WEIGHTS.get("pressure", 10),
    "Shot":             PRIORITY_WEIGHTS.get("shot", 80),
    "Foul Committed":   PRIORITY_WEIGHTS.get("foul", 30),
    "Foul Won":         PRIORITY_WEIGHTS.get("foul", 30),
    "Dribble":          PRIORITY_WEIGHTS.get("dribble", 20),
    "Interception":     PRIORITY_WEIGHTS.get("interception", 25),
    "Clearance":        PRIORITY_WEIGHTS.get("clearance", 15),
    "Block":            PRIORITY_WEIGHTS.get("block", 20),
    "Goal Keeper":      PRIORITY_WEIGHTS.get("keeper", 35),
    "Substitution":     PRIORITY_WEIGHTS.get("substitution", 40),
    "Bad Behaviour":    PRIORITY_WEIGHTS.get("yellow_card", 50),
    "Ball Receipt*":    2,
    "Ball Recovery":    10,
    "Dispossessed":     15,
    "Dribbled Past":    15,
    "Error":            40,
    "Miscontrol":       10,
    "Offside":          20,
    "Shield":           5,
    "50/50":            10,
    "Starting XI":      0,
    "Tactical Shift":   0,
    "Half Start":       0,
    "Half End":         0,
    "Referee Ball-Drop": 0,
    "Injury Stoppage":  30,
    "Player Off":       40,
    "Player On":        40,
}


def _weight(event: MatchEvent) -> int:
    """Return numerical priority weight for an event."""
    base = _TYPE_WEIGHT_MAP.get(event.event_type, 5)

    # Boost for specific outcomes
    if event.event_type == "Shot":
        outcome = event.details.get("shot_outcome", "")
        if outcome == "Goal":
            return 100
        elif outcome in ("Saved", "Saved to Post"):
            return 85
        elif outcome in ("Post", "Blocked"):
            return 75

    if event.event_type in ("Foul Committed", "Foul Won"):
        card = event.details.get("foul_card", "")
        if card == "Red Card":
            return PRIORITY_WEIGHTS.get("red_card", 90)
        elif card in ("Yellow Card", "Second Yellow"):
            return PRIORITY_WEIGHTS.get("yellow_card", 50)

    if event.event_type == "Bad Behaviour":
        card = event.details.get("card", "")
        if card == "Red Card":
            return PRIORITY_WEIGHTS.get("red_card", 90)
        elif card == "Yellow Card":
            return PRIORITY_WEIGHTS.get("yellow_card", 50)

    if event.event_type == "Pass":
        if event.details.get("goal_assist"):
            return 70
        if event.details.get("shot_assist"):
            return 50
        if event.details.get("cross"):
            return 25

    return base


def classify(event: MatchEvent) -> str:
    """Return 'critical', 'notable', or 'routine' for a MatchEvent."""
    w = _weight(event)
    if w >= 70:
        return CRITICAL
    elif w >= 20:
        return NOTABLE
    else:
        return ROUTINE


def classify_and_tag(event: MatchEvent) -> MatchEvent:
    """Classify the event and attach its priority + any detected patterns."""
    event.priority = classify(event)
    return event


# ---------------------------------------------------------------------------
# Sequence detector
# ---------------------------------------------------------------------------

class SequenceDetector:
    """
    Maintains a rolling window of recent events and detects patterns:
    - possession_sequence: 3+ passes in 10 match-seconds by same team
    - attacking_move: carry/dribble → shot within 8 seconds
    - pressing_sequence: 3+ pressure events in 6 seconds by same team
    """

    WINDOW_SEC = 15.0

    def __init__(self) -> None:
        self._window: deque[MatchEvent] = deque(maxlen=30)

    def add(self, event: MatchEvent) -> list[str]:
        """Add event and return list of detected pattern names (may be empty)."""
        self._window.append(event)
        self._trim()
        return self._detect(event)

    def _trim(self) -> None:
        if not self._window:
            return
        latest = self._window[-1].timestamp_sec
        cutoff = latest - self.WINDOW_SEC
        while self._window and self._window[0].timestamp_sec < cutoff:
            self._window.popleft()

    def _detect(self, latest: MatchEvent) -> list[str]:
        patterns: list[str] = []
        window = list(self._window)

        # --- Possession sequence: ≥3 passes by same team in last 10 sec ---
        team_passes = [
            e for e in window
            if e.team == latest.team
            and e.event_type == "Pass"
            and e.details.get("pass_outcome", "Complete") in ("Complete", None, "")
            and latest.timestamp_sec - e.timestamp_sec <= 10.0
        ]
        if len(team_passes) >= 3:
            patterns.append("possession_sequence")

        # --- Attacking move: dribble/carry → shot within 8 sec ---
        if latest.event_type == "Shot":
            recent = [
                e for e in window
                if e.team == latest.team
                and e.event_type in ("Dribble", "Carry")
                and latest.timestamp_sec - e.timestamp_sec <= 8.0
            ]
            if recent:
                patterns.append("attacking_move")

        # --- Pressing sequence: ≥3 pressures in 6 sec by same team ---
        if latest.event_type == "Pressure":
            recent_pressure = [
                e for e in window
                if e.team == latest.team
                and e.event_type == "Pressure"
                and latest.timestamp_sec - e.timestamp_sec <= 6.0
            ]
            if len(recent_pressure) >= 3:
                patterns.append("pressing_sequence")

        # --- Counter-attack: quick transition after winning ball ---
        if latest.event_type in ("Shot", "Pass"):
            recoveries = [
                e for e in window
                if e.team == latest.team
                and e.event_type in ("Interception", "Ball Recovery", "Clearance")
                and latest.timestamp_sec - e.timestamp_sec <= 8.0
            ]
            if recoveries:
                patterns.append("counter_attack")

        return patterns
