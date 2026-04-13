# backend/analysis/engine.py
# Non-AI real-time pattern analysis engine.
# Tracks short-term momentum/sequences and long-term trends,
# then formats them as context strings for the AI commentary agents.

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from typing import Optional

from replay.loader import MatchEvent


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class ShotRecord:
    player: str
    team: str
    position: tuple[float, float]
    xg: float
    outcome: str          # Goal / Saved / Blocked / Off T / Wayward
    timestamp_sec: float


@dataclass
class ZoneVector:
    """Average pass direction in a pitch grid zone."""
    dx: float = 0.0
    dy: float = 0.0
    count: int = 0

    def add(self, dx: float, dy: float) -> None:
        self.dx = (self.dx * self.count + dx) / (self.count + 1)
        self.dy = (self.dy * self.count + dy) / (self.count + 1)
        self.count += 1


@dataclass
class AnalysisSnapshot:
    """Returned by get_context_snapshot() — carries both text context for AI
    and structured data for the frontend."""
    # For AI agents
    short_term_text: str = ""
    long_term_text: str = ""

    # For frontend
    momentum_home: float = 50.0    # 0–100
    momentum_away: float = 50.0
    shots: list[ShotRecord] = field(default_factory=list)
    build_up_vectors: dict = field(default_factory=dict)  # {team: {zone_key: {dx,dy,count}}}
    dangerous_entries: dict = field(default_factory=dict)  # {team: count}
    xg_home: float = 0.0
    xg_away: float = 0.0


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Rolling window for short-term analysis
SHORT_TERM_WINDOW_SEC = 180.0  # 3 game-minutes

# Pitch thirds (x-axis, StatsBomb 0–120)
DEFENSIVE_X_MAX = 40.0
ATTACKING_X_MIN = 80.0

# Penalty box: x > 102, y 18–62 (home team's attack on right side)
# or x < 18, y 18–62 (away team's attack on left side)
BOX_X_FAR  = 102.0
BOX_X_NEAR = 18.0
BOX_Y_LOW  = 18.0
BOX_Y_HIGH = 62.0

# Momentum weights (per event in short-term window)
MOMENTUM_WEIGHTS = {
    "Shot":               6,
    "Goal":               15,
    "Dangerous Entry":    4,
    "Pressure":           2,
    "Dribble":            3,
    "Interception":       3,
    "Block":              2,
    "Carry":              1,
    "Pass":               0.5,
}

# Build-up vector grid: 6 cols × 4 rows
VECTOR_COLS = 6
VECTOR_ROWS = 4


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class MatchAnalysisEngine:
    """
    Continuously updated analysis of match patterns.
    Call update(events, match_time) on every batch.
    Call get_context_snapshot() to get structured output.
    """

    def __init__(self, home_team: str, away_team: str) -> None:
        self.home_team = home_team
        self.away_team = away_team

        # Rolling window of (timestamp_sec, team, weight, label)
        self._window: deque[tuple[float, str, float, str]] = deque()

        # All shots for shot map
        self.shots: list[ShotRecord] = []

        # Cumulative xG
        self._xg: dict[str, float] = {home_team: 0.0, away_team: 0.0}

        # Dangerous entries count
        self._entries: dict[str, int] = {home_team: 0, away_team: 0}

        # Build-up vectors: team → zone_key → ZoneVector
        self._vectors: dict[str, dict[str, ZoneVector]] = {
            home_team: {},
            away_team: {},
        }

        # Current pass chain tracking
        self._chain_team: Optional[str] = None
        self._chain_len: int = 0
        self._chain_max_recent: int = 0   # longest chain in last 3 min

        # Pass chain history for context
        self._recent_chains: deque[tuple[str, int]] = deque(maxlen=10)

        # Pressing stats (pressure events in last 3 min)
        self._press_window: deque[tuple[float, str]] = deque()

        # Long-term phase tracking: which team dominated each 5-min block
        self._phase_blocks: list[tuple[float, str]] = []  # (game_time, dominant_team)
        self._last_phase_check: float = 0.0

        # Current match time
        self._current_time: float = 0.0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update(self, events: list[MatchEvent], match_time: float) -> None:
        """Process a batch of events and update all tracking structures."""
        self._current_time = match_time
        self._evict_old(match_time)

        for ev in events:
            self._process(ev, match_time)

        self._update_phase(match_time)

    def get_context_snapshot(self) -> AnalysisSnapshot:
        """Return a snapshot with text context for AI and data for frontend."""
        short = self._build_short_term_text()
        long_ = self._build_long_term_text()
        mom = self._compute_momentum()

        return AnalysisSnapshot(
            short_term_text=short,
            long_term_text=long_,
            momentum_home=mom[self.home_team],
            momentum_away=mom[self.away_team],
            shots=list(self.shots),
            build_up_vectors=self._serialize_vectors(),
            dangerous_entries=dict(self._entries),
            xg_home=self._xg.get(self.home_team, 0.0),
            xg_away=self._xg.get(self.away_team, 0.0),
        )

    # ------------------------------------------------------------------
    # Processing
    # ------------------------------------------------------------------

    def _process(self, ev: MatchEvent, match_time: float) -> None:
        team = ev.team
        et = ev.event_type

        # --- Shot tracking ---
        if et == "Shot":
            xg = float(ev.details.get("xg") or 0.0)
            outcome = ev.details.get("shot_outcome", "Unknown")
            self.shots.append(ShotRecord(
                player=ev.player,
                team=team,
                position=ev.position,
                xg=xg,
                outcome=outcome,
                timestamp_sec=ev.timestamp_sec,
            ))
            self._xg[team] = self._xg.get(team, 0.0) + xg
            weight = MOMENTUM_WEIGHTS["Shot"] + (MOMENTUM_WEIGHTS["Goal"] if outcome == "Goal" else 0)
            self._add_window(match_time, team, weight, "Shot")

        # --- Pass build-up vectors ---
        elif et == "Pass" and ev.end_position:
            dx = ev.end_position[0] - ev.position[0]
            dy = ev.end_position[1] - ev.position[1]
            zone = self._zone_key(ev.position)
            if team not in self._vectors:
                self._vectors[team] = {}
            if zone not in self._vectors[team]:
                self._vectors[team][zone] = ZoneVector()
            self._vectors[team][zone].add(dx, dy)

            # Chain tracking
            if team == self._chain_team:
                self._chain_len += 1
            else:
                if self._chain_team and self._chain_len >= 4:
                    self._recent_chains.append((self._chain_team, self._chain_len))
                self._chain_team = team
                self._chain_len = 1

            self._add_window(match_time, team, MOMENTUM_WEIGHTS["Pass"], "Pass")

        # --- Dangerous entry ---
        elif et in ("Pass", "Carry"):
            if ev.end_position and self._is_dangerous_entry(ev):
                self._entries[team] = self._entries.get(team, 0) + 1
                self._add_window(match_time, team, MOMENTUM_WEIGHTS["Dangerous Entry"], "Entry")

        # --- Pressure (pressing) ---
        elif et == "Pressure":
            self._press_window.append((match_time, team))
            self._add_window(match_time, team, MOMENTUM_WEIGHTS["Pressure"], "Pressure")

        # --- Dribble / Carry ---
        elif et == "Dribble":
            self._add_window(match_time, team, MOMENTUM_WEIGHTS["Dribble"], "Dribble")

        elif et == "Carry":
            self._add_window(match_time, team, MOMENTUM_WEIGHTS["Carry"], "Carry")

        elif et == "Interception":
            self._add_window(match_time, team, MOMENTUM_WEIGHTS["Interception"], "Interception")

        elif et == "Block":
            self._add_window(match_time, team, MOMENTUM_WEIGHTS["Block"], "Block")

    # ------------------------------------------------------------------
    # Helper: window management
    # ------------------------------------------------------------------

    def _add_window(self, t: float, team: str, weight: float, label: str) -> None:
        self._window.append((t, team, weight, label))

    def _evict_old(self, match_time: float) -> None:
        cutoff = match_time - SHORT_TERM_WINDOW_SEC
        while self._window and self._window[0][0] < cutoff:
            self._window.popleft()
        while self._press_window and self._press_window[0][0] < cutoff:
            self._press_window.popleft()

    # ------------------------------------------------------------------
    # Momentum
    # ------------------------------------------------------------------

    def _compute_momentum(self) -> dict[str, float]:
        scores: dict[str, float] = {self.home_team: 0.0, self.away_team: 0.0}
        now = self._current_time
        for t, team, weight, _ in self._window:
            # Recency factor: events in last 60s count double
            recency = 2.0 if (now - t) < 60 else 1.0
            scores[team] = scores.get(team, 0.0) + weight * recency

        total = scores[self.home_team] + scores[self.away_team]
        if total < 1:
            return {self.home_team: 50.0, self.away_team: 50.0}

        hpct = round(scores[self.home_team] / total * 100, 1)
        return {self.home_team: hpct, self.away_team: round(100 - hpct, 1)}

    # ------------------------------------------------------------------
    # Dangerous entry
    # ------------------------------------------------------------------

    def _is_dangerous_entry(self, ev: MatchEvent) -> bool:
        """Return True if the end of this event enters a penalty box."""
        if not ev.end_position:
            return False
        ex, ey = ev.end_position
        in_y = BOX_Y_LOW <= ey <= BOX_Y_HIGH

        if not in_y:
            return False

        # Home team attacking right → box at x > 102
        # Away team attacking left → box at x < 18
        # We don't know which direction a team is attacking without kick-off info,
        # so use both boxes and assume the team is entering the opponent's box
        team_is_home = ev.team == self.home_team
        if team_is_home:
            return ex > BOX_X_FAR
        else:
            return ex < BOX_X_NEAR

    # ------------------------------------------------------------------
    # Phase / dominance tracking
    # ------------------------------------------------------------------

    def _update_phase(self, match_time: float) -> None:
        if match_time - self._last_phase_check < 300:  # every 5 game-minutes
            return
        self._last_phase_check = match_time
        mom = self._compute_momentum()
        dominant = max(mom, key=lambda k: mom[k])
        if mom[dominant] > 55:
            self._phase_blocks.append((match_time, dominant))

    # ------------------------------------------------------------------
    # Zone key for build-up vectors
    # ------------------------------------------------------------------

    @staticmethod
    def _zone_key(pos: tuple[float, float]) -> str:
        col = min(VECTOR_COLS - 1, int(pos[0] / 120 * VECTOR_COLS))
        row = min(VECTOR_ROWS - 1, int(pos[1] / 80 * VECTOR_ROWS))
        return f"{col},{row}"

    def _serialize_vectors(self) -> dict:
        result = {}
        for team, zones in self._vectors.items():
            result[team] = {}
            for zk, zv in zones.items():
                if zv.count >= 3:  # Only include zones with enough data
                    result[team][zk] = {"dx": zv.dx, "dy": zv.dy, "count": zv.count}
        return result

    # ------------------------------------------------------------------
    # Text context builders
    # ------------------------------------------------------------------

    def _build_short_term_text(self) -> str:
        if not self._window:
            return ""

        mom = self._compute_momentum()
        hm = mom[self.home_team]
        am = mom[self.away_team]

        lines = []
        lines.append(
            f"MOMENTUM (last 3 min): {self.home_team} {hm:.0f} | {self.away_team} {am:.0f}"
        )

        # Pressing intensity
        home_press = sum(1 for _, t in self._press_window if t == self.home_team)
        away_press = sum(1 for _, t in self._press_window if t == self.away_team)
        if home_press + away_press > 0:
            if home_press > away_press * 1.5:
                lines.append(f"{self.home_team} pressing intensely ({home_press} pressure events)")
            elif away_press > home_press * 1.5:
                lines.append(f"{self.away_team} pressing intensely ({away_press} pressure events)")

        # Recent longest pass chain
        if self._recent_chains:
            team, length = max(self._recent_chains, key=lambda x: x[1])
            if length >= 5:
                lines.append(f"Notable sequence: {length}-pass chain by {team}")

        # Dangerous entries in window
        entry_counts: dict[str, int] = {}
        for _, team, _, label in self._window:
            if label == "Entry":
                entry_counts[team] = entry_counts.get(team, 0) + 1
        for team, cnt in entry_counts.items():
            if cnt >= 2:
                lines.append(f"{team} threatening — {cnt} box entries this spell")

        return " | ".join(lines)

    def _build_long_term_text(self) -> str:
        lines = []

        # xG balance
        hxg = self._xg.get(self.home_team, 0.0)
        axg = self._xg.get(self.away_team, 0.0)
        if hxg + axg > 0.1:
            lines.append(
                f"xG: {self.home_team} {hxg:.2f} vs {self.away_team} {axg:.2f}"
            )
            # Narrative note if xG diverges from score
            if hxg > axg + 0.5:
                lines.append(f"{self.home_team} creating more clear chances despite the scoreline")
            elif axg > hxg + 0.5:
                lines.append(f"{self.away_team} edging the xG battle")

        # Total shots
        home_shots = sum(1 for s in self.shots if s.team == self.home_team)
        away_shots = sum(1 for s in self.shots if s.team == self.away_team)
        if home_shots + away_shots > 0:
            lines.append(f"Shots: {self.home_team} {home_shots} vs {self.away_team} {away_shots}")

        # Dangerous entries total
        he = self._entries.get(self.home_team, 0)
        ae = self._entries.get(self.away_team, 0)
        if he + ae > 0:
            lines.append(f"Box entries: {self.home_team} {he} vs {self.away_team} {ae}")

        # Dominant phases
        if len(self._phase_blocks) >= 2:
            last_dominant = self._phase_blocks[-1][1]
            lines.append(f"Recent phase: {last_dominant} have controlled the last spell")

        return " | ".join(lines)
