# backend/commentator/agents/tactical.py
# Tactical agent: explains patterns, formations, pressing, transitions.

from __future__ import annotations

from commentator.agents.base import BaseAgent, _events_to_text, _state_to_summary
from commentator.agents.prompts import build_tactical_system, build_tactical_prompt
from player.loader import MatchEvent
from analyser.state import SharedMatchState


class TacticalAgent(BaseAgent):
    def __init__(self, **kwargs) -> None:
        super().__init__(
            name="tactical",
            system_prompt=build_tactical_system("neutral"),
            **kwargs,
        )

    def build_prompt(self, events: list[MatchEvent], state: SharedMatchState) -> str:
        events_text = _events_to_text(events)
        state_summary = _state_to_summary(state)
        recent_utterances = state.recent_utterances_text(3)

        # Add pattern context
        patterns: set[str] = set()
        for ev in events:
            patterns.update(ev.detected_patterns)
        if patterns:
            events_text += f"\nDetected patterns: {', '.join(patterns)}"

        return build_tactical_prompt(events_text, state_summary, recent_utterances)

    def _fallback(self, events: list[MatchEvent], state: SharedMatchState) -> str:
        """Template fallbacks for tactical observations."""
        if not events:
            return ""

        patterns: set[str] = set()
        for ev in events:
            patterns.update(ev.detected_patterns)

        poss = state.possession_pct()
        dominant = max(poss, key=lambda t: poss[t])
        dominant_pct = poss[dominant]

        if "possession_sequence" in patterns:
            return f"{dominant} are patiently building, recycling the ball to draw defenders out."
        if "pressing_sequence" in patterns:
            ev = events[0]
            return f"{ev.team} are pressing with intensity in the middle third right now."
        if "counter_attack" in patterns:
            ev = events[0]
            return f"{ev.team} caught the opposition high — this is a direct counter."
        if "attacking_move" in patterns:
            ev = events[0]
            return f"Good combination play from {ev.team}, arriving in numbers."

        phase = state.current_phase
        if phase == "set_piece":
            return f"{dominant} looking to exploit the set piece delivery."
        if dominant_pct > 60:
            return f"{dominant} are dominating possession at {dominant_pct:.0f}% — dictating the tempo."

        return f"Both sides probing, looking for the space to exploit in behind."
