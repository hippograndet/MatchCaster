# backend/commentator/agents/stats.py
# Stats agent: injects concise single-sentence stat facts.

from __future__ import annotations

from commentator.agents.base import BaseAgent, _events_to_text, _state_to_summary
from commentator.agents.prompts import build_stats_system, build_stats_prompt
from player.loader import MatchEvent
from analyser.state import SharedMatchState


class StatsAgent(BaseAgent):
    def __init__(self, **kwargs) -> None:
        super().__init__(
            name="stats",
            system_prompt=build_stats_system("neutral"),
            **kwargs,
        )

    def build_prompt(self, events: list[MatchEvent], state: SharedMatchState) -> str:
        events_text = _events_to_text(events)
        state_summary = _state_to_summary(state)
        recent_utterances = state.recent_utterances_text(3)
        return build_stats_prompt(events_text, state_summary, recent_utterances)

    def _fallback(self, events: list[MatchEvent], state: SharedMatchState) -> str:
        """Produce a meaningful stat from current match state."""
        if not events:
            return ""

        ev = events[0]
        home_stats = state.get_stats(state.home_team)
        away_stats = state.get_stats(state.away_team)
        ev_stats = state.get_stats(ev.team)

        if ev.event_type == "Shot" and ev_stats:
            return f"That's {ev_stats.shots} shots for {ev.team} in this match."

        if ev.event_type in ("Foul Committed",) and ev_stats:
            return f"{ev.team} have now committed {ev_stats.fouls} fouls."

        if ev.event_type == "Pass" and ev_stats and ev_stats.passes_attempted > 0:
            pct = int(ev_stats.passes_completed / ev_stats.passes_attempted * 100)
            return f"{ev.team} have a {pct}% pass completion rate today."

        if home_stats and away_stats:
            poss = state.possession_pct()
            dominant = max(poss, key=lambda t: poss[t])
            return f"{dominant} have had {poss[dominant]:.0f}% of possession this half."

        return f"{ev.team} continue to press for the advantage."
