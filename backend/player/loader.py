# backend/player/loader.py
# Load and parse StatsBomb open-data JSON events into normalized MatchEvent dataclasses.

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Optional
from pathlib import Path

from config import MATCHES_DIR, LINEUPS_DIR

logger = logging.getLogger("[LOADER]")


@dataclass
class MatchEvent:
    id: str
    timestamp_sec: float                          # seconds from kickoff
    event_type: str                               # "Pass", "Shot", "Goal Keeper", etc.
    team: str
    player: Optional[str]                         # None for team-level events (Starting XI etc.)
    position: tuple[float, float]                 # (x, y) StatsBomb coords
    end_position: Optional[tuple[float, float]]
    details: dict                                 # raw extra fields (xG, pass type, outcome…)
    priority: str = "routine"                     # set by classifier later
    detected_patterns: list[str] = field(default_factory=list)
    index: int = 0                                # original event order


@dataclass
class MatchInfo:
    match_id: str
    home_team: str
    away_team: str
    competition: str
    season: str
    home_lineup: list[dict]   # [{player, position, jersey_number}, ...]
    away_lineup: list[dict]


def _parse_timestamp(ts: str) -> float:
    """Convert StatsBomb timestamp string 'MM:SS.mmm' or 'HH:MM:SS.mmm' to seconds."""
    if not ts:
        return 0.0
    # StatsBomb format: "00:01:30.500" (HH:MM:SS.mmm)
    parts = ts.split(":")
    try:
        if len(parts) == 3:
            hours = int(parts[0])
            minutes = int(parts[1])
            seconds = float(parts[2])
            return hours * 3600 + minutes * 60 + seconds
        elif len(parts) == 2:
            minutes = int(parts[0])
            seconds = float(parts[1])
            return minutes * 60 + seconds
        else:
            return float(ts)
    except (ValueError, IndexError):
        return 0.0


def _extract_position(event: dict) -> tuple[float, float]:
    loc = event.get("location")
    if loc and isinstance(loc, list) and len(loc) >= 2:
        return (float(loc[0]), float(loc[1]))
    return (60.0, 40.0)  # center of pitch as default


def _extract_end_position(event: dict) -> Optional[tuple[float, float]]:
    """Try to find the end location from pass, shot, carry sub-objects."""
    for key in ("pass", "shot", "carry", "goalkeeper", "dribble"):
        sub = event.get(key, {})
        if isinstance(sub, dict):
            end = sub.get("end_location")
            if end and isinstance(end, list) and len(end) >= 2:
                return (float(end[0]), float(end[1]))
    return None


def _extract_player(event: dict) -> Optional[str]:
    """Return player name, or None for team-level events (e.g. Starting XI)."""
    player = event.get("player", {})
    if isinstance(player, dict):
        name = player.get("name")
        return name if name else None
    return str(player) if player else None


def _extract_team(event: dict) -> str:
    team = event.get("team", {})
    if isinstance(team, dict):
        return team.get("name", "Unknown")
    return str(team) if team else "Unknown"


def _build_details(event: dict) -> dict:
    """Collect useful sub-fields into a flat-ish details dict."""
    details: dict = {}

    # Pass details
    if "pass" in event:
        p = event["pass"]
        details["pass_recipient"] = p.get("recipient", {}).get("name") if isinstance(p.get("recipient"), dict) else None
        details["pass_outcome"] = p.get("outcome", {}).get("name") if isinstance(p.get("outcome"), dict) else "Complete"
        details["pass_type"] = p.get("type", {}).get("name") if isinstance(p.get("type"), dict) else None
        details["pass_height"] = p.get("height", {}).get("name") if isinstance(p.get("height"), dict) else None
        details["pass_length"] = p.get("length")
        details["pass_angle"] = p.get("angle")
        details["through_ball"] = p.get("technique", {}).get("name") if isinstance(p.get("technique"), dict) else None
        details["switch"] = p.get("switch", False)
        details["cross"] = p.get("cross", False)
        details["goal_assist"] = p.get("goal_assist", False)
        details["shot_assist"] = p.get("shot_assist", False)

    # Shot details
    if "shot" in event:
        s = event["shot"]
        details["shot_outcome"] = s.get("outcome", {}).get("name") if isinstance(s.get("outcome"), dict) else None
        details["shot_technique"] = s.get("technique", {}).get("name") if isinstance(s.get("technique"), dict) else None
        details["shot_type"] = s.get("type", {}).get("name") if isinstance(s.get("type"), dict) else None
        details["xg"] = s.get("statsbomb_xg")
        details["first_time"] = s.get("first_time", False)
        details["one_on_one"] = s.get("one_on_one", False)

    # Dribble
    if "dribble" in event:
        d = event["dribble"]
        details["dribble_outcome"] = d.get("outcome", {}).get("name") if isinstance(d.get("outcome"), dict) else None

    # Foul
    if "foul_committed" in event:
        fc = event["foul_committed"]
        details["foul_card"] = fc.get("card", {}).get("name") if isinstance(fc.get("card"), dict) else None
        details["foul_type"] = fc.get("type", {}).get("name") if isinstance(fc.get("type"), dict) else None

    # Bad behaviour card
    if "bad_behaviour" in event:
        bb = event["bad_behaviour"]
        details["card"] = bb.get("card", {}).get("name") if isinstance(bb.get("card"), dict) else None

    # Substitution
    if "substitution" in event:
        sub = event["substitution"]
        details["sub_replacement"] = sub.get("replacement", {}).get("name") if isinstance(sub.get("replacement"), dict) else None
        details["sub_reason"] = sub.get("outcome", {}).get("name") if isinstance(sub.get("outcome"), dict) else None

    # Goalkeeper
    if "goalkeeper" in event:
        gk = event["goalkeeper"]
        details["gk_type"] = gk.get("type", {}).get("name") if isinstance(gk.get("type"), dict) else None
        details["gk_outcome"] = gk.get("outcome", {}).get("name") if isinstance(gk.get("outcome"), dict) else None
        details["gk_technique"] = gk.get("technique", {}).get("name") if isinstance(gk.get("technique"), dict) else None

    # Pressure / clearance / interception
    if "clearance" in event:
        cl = event["clearance"]
        details["clearance_technique"] = cl.get("technique", {}).get("name") if isinstance(cl.get("technique"), dict) else None

    # Generic outcome
    if "outcome" in event:
        oc = event["outcome"]
        details["outcome"] = oc.get("name") if isinstance(oc, dict) else str(oc)

    # Period and minute for convenience
    details["period"] = event.get("period", 1)
    details["minute"] = event.get("minute", 0)
    details["second"] = event.get("second", 0)
    details["under_pressure"] = event.get("under_pressure", False)

    # Actual action duration from StatsBomb (seconds). Used by the frontend
    # to drive realistic animation speed instead of fixed visual constants.
    details["duration"] = event.get("duration")

    return details


def load_events(match_id: str) -> list[MatchEvent]:
    """Load and normalize all events for a given match_id."""
    events_path = Path(MATCHES_DIR) / f"{match_id}.json"
    if not events_path.exists():
        raise FileNotFoundError(f"Match events not found: {events_path}")

    with open(events_path, "r", encoding="utf-8") as f:
        raw_events: list[dict] = json.load(f)

    parsed: list[MatchEvent] = []
    for idx, ev in enumerate(raw_events):
        event_type_raw = ev.get("type", {})
        event_type = event_type_raw.get("name", "Unknown") if isinstance(event_type_raw, dict) else str(event_type_raw)

        ts = ev.get("timestamp", "00:00:00.000")
        # Add period offset: period 2 starts at 45 min, ET periods at 90/105
        period = ev.get("period", 1)
        period_offsets = {1: 0, 2: 45 * 60, 3: 90 * 60, 4: 105 * 60, 5: 120 * 60}
        offset = period_offsets.get(period, 0)
        ts_sec = _parse_timestamp(ts) + offset

        match_event = MatchEvent(
            id=ev.get("id", str(idx)),
            timestamp_sec=ts_sec,
            event_type=event_type,
            team=_extract_team(ev),
            player=_extract_player(ev),
            position=_extract_position(ev),
            end_position=_extract_end_position(ev),
            details=_build_details(ev),
            index=idx,
        )
        parsed.append(match_event)

    # Sort by timestamp, then original index for ties
    parsed.sort(key=lambda e: (e.timestamp_sec, e.index))
    logger.debug(f"Loaded {len(parsed)} events for match {match_id}")
    return parsed


def load_lineup(match_id: str, team: str) -> list[dict]:
    """Load lineup for a team in the given match. Returns list of player dicts."""
    lineup_path = Path(LINEUPS_DIR) / f"{match_id}.json"
    if not lineup_path.exists():
        return []

    with open(lineup_path, "r", encoding="utf-8") as f:
        lineups: list[dict] = json.load(f)

    for lineup in lineups:
        lineup_team = lineup.get("team_name", "")
        if lineup_team.lower() == team.lower():
            players = []
            for p in lineup.get("lineup", []):
                player_entry = {
                    "name": p.get("player_name", "Unknown"),
                    "jersey_number": p.get("jersey_number"),
                    "positions": [pos.get("position", "") for pos in p.get("positions", [])],
                    "country": p.get("country", {}).get("name", "") if isinstance(p.get("country"), dict) else "",
                }
                players.append(player_entry)
            return players
    return []


SNAPSHOT_INTERVAL_SEC = 300   # one snapshot every 5 real match-minutes
_SKIP_STAT_TYPES = {
    'Ball Receipt*', 'Ball Recovery', 'Starting XI',
    'Half Start', 'Half End', 'Referee Ball-Drop',
}


def compute_snapshots(events: list[MatchEvent], home_team: str, away_team: str) -> list[dict]:
    """
    Walk events in timestamp order and record a full state snapshot every
    SNAPSHOT_INTERVAL_SEC seconds.  Returns a list of dicts that can be
    sent over the wire and used to restore SharedMatchState on seek.

    Each snapshot has the shape:
      {
        "t": float,           # seconds from kick-off
        "score": {"home": int, "away": int},
        "stats": {
          team_name: {shots, shots_on_target, passes_completed,
                      passes_attempted, fouls, yellow_cards, red_cards,
                      goals, xg, possession_events},
          ...
        }
      }
    """
    def _blank() -> dict:
        return dict(shots=0, shots_on_target=0, passes_completed=0,
                    passes_attempted=0, fouls=0, yellow_cards=0,
                    red_cards=0, goals=0, xg=0.0, possession_events=0)

    stats: dict[str, dict] = {home_team: _blank(), away_team: _blank()}
    score = {"home": 0, "away": 0}

    def _snap(t: float) -> dict:
        return {
            "t": t,
            "score": dict(score),
            "stats": {k: dict(v) for k, v in stats.items()},
        }

    snapshots: list[dict] = [_snap(0.0)]   # t=0 starting state
    next_t = SNAPSHOT_INTERVAL_SEC

    for ev in events:
        team = ev.team
        if team not in stats:
            stats[team] = _blank()
        s = stats[team]
        is_home = team == home_team
        score_key = "home" if is_home else "away"

        if ev.event_type not in _SKIP_STAT_TYPES:
            s["possession_events"] += 1

        if ev.event_type == "Pass":
            s["passes_attempted"] += 1
            outcome = ev.details.get("pass_outcome", "Complete")
            if outcome in ("Complete", None, ""):
                s["passes_completed"] += 1

        elif ev.event_type == "Shot":
            s["shots"] += 1
            outcome = ev.details.get("shot_outcome", "")
            if outcome == "Goal":
                s["goals"] += 1
                score[score_key] += 1
            if outcome in ("Goal", "Saved", "Saved to Post"):
                s["shots_on_target"] += 1
            if ev.details.get("xg"):
                s["xg"] = round(s["xg"] + float(ev.details["xg"]), 3)

        elif ev.event_type == "Foul Committed":
            s["fouls"] += 1
            card = ev.details.get("foul_card", "")
            if card == "Yellow Card":
                s["yellow_cards"] += 1
            elif card in ("Red Card", "Second Yellow"):
                s["red_cards"] += 1

        elif ev.event_type == "Bad Behaviour":
            card = ev.details.get("card", "")
            if card == "Yellow Card":
                s["yellow_cards"] += 1
            elif card in ("Red Card", "Second Yellow"):
                s["red_cards"] += 1

        # Emit snapshot(s) for any interval we've crossed
        while ev.timestamp_sec >= next_t:
            snapshots.append(_snap(next_t))
            next_t += SNAPSHOT_INTERVAL_SEC

    return snapshots


def compute_goal_timeline(
    events: list[MatchEvent],
    home_team: str,
    away_team: str,
) -> list[dict]:
    """
    Return a lightweight list of goal events in chronological order.
    Each entry:
      {t, team, is_home, scorer, assist, score_home, score_away}
    'assist' is the player from the most recent same-team Pass with
    goal_assist=True within 10 seconds before the goal.
    """
    score_home = 0
    score_away = 0
    timeline: list[dict] = []

    for i, ev in enumerate(events):
        if ev.event_type != "Shot":
            continue
        if ev.details.get("shot_outcome") != "Goal":
            continue

        is_home = ev.team == home_team
        if is_home:
            score_home += 1
        else:
            score_away += 1

        # Look back for an assist pass (same team, goal_assist=True, within 10s)
        assist: Optional[str] = None
        for prev in reversed(events[:i]):
            if prev.timestamp_sec < ev.timestamp_sec - 10.0:
                break
            if (
                prev.event_type == "Pass"
                and prev.team == ev.team
                and prev.details.get("goal_assist")
            ):
                assist = prev.player
                break

        timeline.append({
            "t": ev.timestamp_sec,
            "team": ev.team,
            "is_home": is_home,
            "scorer": ev.player,
            "assist": assist,
            "score_home": score_home,
            "score_away": score_away,
        })

    return timeline


def get_score_at(goal_timeline: list[dict], t: float) -> dict:
    """Return {home, away} goal count at game time t (exclusive: goals at exactly t are included)."""
    home, away = 0, 0
    for g in goal_timeline:
        if g["t"] > t:
            break
        if g["is_home"]:
            home += 1
        else:
            away += 1
    return {"home": home, "away": away}


# Critical event types used for look-ahead speed control
_CRITICAL_EVENT_TYPES = {"Shot"}
_CRITICAL_CARD_TYPES  = {"Red Card", "Second Yellow"}


def compute_critical_timeline(events: list[MatchEvent]) -> list[MatchEvent]:
    """
    Return only the high-stakes events (shots, red cards) used for
    look-ahead speed-override in the replay engine.
    """
    out: list[MatchEvent] = []
    for ev in events:
        if ev.event_type in _CRITICAL_EVENT_TYPES:
            out.append(ev)
        elif ev.event_type in ("Foul Committed", "Bad Behaviour"):
            card = ev.details.get("foul_card") or ev.details.get("card", "")
            if card in _CRITICAL_CARD_TYPES:
                out.append(ev)
    return out


def list_available_matches() -> list[dict]:
    """Return a list of available match IDs and their file sizes."""
    matches_dir = Path(MATCHES_DIR)
    if not matches_dir.exists():
        return []

    result = []
    for f in matches_dir.glob("*.json"):
        # Try to quickly extract team names from first few events
        try:
            with open(f, "r", encoding="utf-8") as fp:
                data = json.load(fp)
            teams = list({
                ev.get("team", {}).get("name", "?")
                for ev in data[:20]
                if isinstance(ev.get("team"), dict)
            })
            # Estimate total match time from last event's index/minute
            # Use the period + minute of the last event for a rough total
            total_time = 5400  # 90 min default
            if data:
                last = data[-1]
                ts = last.get("timestamp", "00:00:00.000")
                period = last.get("period", 2)
                period_offsets_sec = {1: 0, 2: 45 * 60, 3: 90 * 60, 4: 105 * 60, 5: 120 * 60}
                total_time = int(_parse_timestamp(ts) + period_offsets_sec.get(period, 0))
            result.append({
                "match_id": f.stem,
                "teams": teams[:2],
                "event_count": len(data),
                "file": f.name,
                "total_time": total_time,
            })
        except Exception:
            result.append({"match_id": f.stem, "teams": [], "event_count": 0, "file": f.name, "total_time": 5400})

    return result
