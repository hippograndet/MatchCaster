# backend/analyser/state.py
# SharedMatchState: single source of truth for all agents.

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from typing import Optional

from player.loader import MatchEvent

logger = logging.getLogger("[STATE]")


@dataclass
class AgentUtterance:
    agent_name: str
    text: str
    match_time: float
    event_type: str = ""


@dataclass
class TeamStats:
    name: str
    shots: int = 0
    shots_on_target: int = 0
    passes_attempted: int = 0
    passes_completed: int = 0
    fouls: int = 0
    yellow_cards: int = 0
    red_cards: int = 0
    goals: int = 0
    corners: int = 0
    offsides: int = 0
    possession_events: int = 0   # total events (proxy for possession)
    xg: float = 0.0


class SharedMatchState:
    """
    Singleton match state shared across all agents and the director.
    Updated by the director after each event batch.
    """

    def __init__(self, home_team: str = "Home", away_team: str = "Away") -> None:
        self.home_team = home_team
        self.away_team = away_team

        self.score: dict[str, int] = {"home": 0, "away": 0}
        self.recent_events: deque[MatchEvent] = deque(maxlen=20)
        self.agent_utterances: deque[AgentUtterance] = deque(maxlen=10)
        self.current_match_time: float = 0.0
        self.current_phase: str = "open_play"    # "open_play" | "set_piece" | "stoppage"
        self.last_utterance_time: float = -999.0  # real-time seconds
        self.last_event_time: float = 0.0          # match seconds

        self._team_stats: dict[str, TeamStats] = {
            home_team: TeamStats(name=home_team),
            away_team: TeamStats(name=away_team),
        }

    # ------------------------------------------------------------------
    # Update from events
    # ------------------------------------------------------------------

    def update(self, events: list[MatchEvent], match_time: float) -> None:
        self.current_match_time = match_time
        for ev in events:
            self.recent_events.append(ev)
            self.last_event_time = ev.timestamp_sec
            self._update_stats(ev)
            self._update_phase(ev)

    def _update_stats(self, ev: MatchEvent) -> None:
        stats = self._team_stats.get(ev.team)
        if stats is None:
            # Possibly an away team we didn't register; add dynamically
            self._team_stats[ev.team] = TeamStats(name=ev.team)
            stats = self._team_stats[ev.team]

        stats.possession_events += 1

        if ev.event_type == "Pass":
            stats.passes_attempted += 1
            outcome = ev.details.get("pass_outcome", "Complete")
            if outcome in ("Complete", None, ""):
                stats.passes_completed += 1

        elif ev.event_type == "Shot":
            stats.shots += 1
            outcome = ev.details.get("shot_outcome", "")
            if outcome == "Goal":
                stats.goals += 1
                if ev.team == self.home_team:
                    self.score["home"] += 1
                else:
                    self.score["away"] += 1
                logger.info(f"GOAL! {ev.team}: {self.score}")
            if outcome in ("Goal", "Saved", "Saved to Post"):
                stats.shots_on_target += 1
            if ev.details.get("xg"):
                stats.xg += ev.details["xg"]

        elif ev.event_type in ("Foul Committed",):
            stats.fouls += 1
            card = ev.details.get("foul_card", "")
            if card == "Yellow Card":
                stats.yellow_cards += 1
            elif card in ("Red Card", "Second Yellow"):
                stats.red_cards += 1

        elif ev.event_type == "Bad Behaviour":
            card = ev.details.get("card", "")
            if card == "Yellow Card":
                stats.yellow_cards += 1
            elif card in ("Red Card", "Second Yellow"):
                stats.red_cards += 1

        elif ev.event_type == "Offside":
            stats.offsides += 1

    def _update_phase(self, ev: MatchEvent) -> None:
        if ev.event_type in ("Foul Committed", "Foul Won", "Injury Stoppage"):
            self.current_phase = "stoppage"
        elif ev.event_type in ("Pass",) and ev.details.get("pass_type") in (
            "Free Kick", "Corner", "Throw-in", "Kick Off", "Goal Kick"
        ):
            self.current_phase = "set_piece"
        elif ev.event_type in ("Pass", "Carry", "Shot", "Dribble", "Pressure"):
            self.current_phase = "open_play"

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------

    def possession_pct(self) -> dict[str, float]:
        home = self._team_stats.get(self.home_team)
        away = self._team_stats.get(self.away_team)
        if home is None or away is None:
            return {self.home_team: 50.0, self.away_team: 50.0}
        total = home.possession_events + away.possession_events
        if total == 0:
            return {self.home_team: 50.0, self.away_team: 50.0}
        return {
            self.home_team: round(home.possession_events / total * 100, 1),
            self.away_team: round(away.possession_events / total * 100, 1),
        }

    def get_stats(self, team: str) -> Optional[TeamStats]:
        return self._team_stats.get(team)

    def get_all_stats(self) -> dict[str, TeamStats]:
        return dict(self._team_stats)

    def reset_to_snapshot(self, snapshot: dict) -> None:
        """
        Restore all cumulative stats from a pre-computed snapshot dict
        (as produced by loader.compute_snapshots).  Safe to call mid-session.
        """
        self.score = dict(snapshot["score"])
        self.current_match_time = snapshot["t"]
        self.recent_events.clear()
        self._team_stats = {}
        for team_name, sd in snapshot["stats"].items():
            ts = TeamStats(name=team_name)
            ts.shots             = sd.get("shots", 0)
            ts.shots_on_target   = sd.get("shots_on_target", 0)
            ts.passes_completed  = sd.get("passes_completed", 0)
            ts.passes_attempted  = sd.get("passes_attempted", 0)
            ts.fouls             = sd.get("fouls", 0)
            ts.yellow_cards      = sd.get("yellow_cards", 0)
            ts.red_cards         = sd.get("red_cards", 0)
            ts.goals             = sd.get("goals", 0)
            ts.xg                = sd.get("xg", 0.0)
            ts.possession_events = sd.get("possession_events", 0)
            self._team_stats[team_name] = ts

    def add_utterance(self, utterance: AgentUtterance) -> None:
        self.agent_utterances.append(utterance)
        self.last_utterance_time = utterance.match_time

    def recent_utterances_text(self, n: int = 3) -> str:
        """Return last n utterances as a formatted string for prompts."""
        recent = list(self.agent_utterances)[-n:]
        if not recent:
            return "(none)"
        lines = [f"{u.agent_name}: \"{u.text}\"" for u in recent]
        return "\n".join(lines)

    def score_str(self) -> str:
        return f"{self.home_team} {self.score['home']} - {self.score['away']} {self.away_team}"

    def minute_str(self) -> str:
        mins = int(self.current_match_time // 60)
        return f"{mins}'"

    def to_dict(self) -> dict:
        """Serialize for WebSocket transmission."""
        stats_out = {}
        for team, s in self._team_stats.items():
            stats_out[team] = {
                "shots": s.shots,
                "shots_on_target": s.shots_on_target,
                "passes_completed": s.passes_completed,
                "passes_attempted": s.passes_attempted,
                "fouls": s.fouls,
                "yellow_cards": s.yellow_cards,
                "red_cards": s.red_cards,
                "goals": s.goals,
                "xg": round(s.xg, 2),
            }
        return {
            "score": self.score,
            "home_team": self.home_team,
            "away_team": self.away_team,
            "match_time": self.current_match_time,
            "minute": self.minute_str(),
            "phase": self.current_phase,
            "possession": self.possession_pct(),
            "stats": stats_out,
        }
