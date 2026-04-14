# backend/commentator/agents/play_by_play.py
# Play-by-play agent: narrates live action with excitement scaled to priority.

from __future__ import annotations

from commentator.agents.base import BaseAgent, _events_to_text, _state_to_summary
from commentator.agents.prompts import build_pbp_system, build_pbp_prompt
from player.loader import MatchEvent
from analyser.state import SharedMatchState


class PlayByPlayAgent(BaseAgent):
    def __init__(self, **kwargs) -> None:
        super().__init__(
            name="play_by_play",
            system_prompt=build_pbp_system("neutral"),
            **kwargs,
        )

    def build_prompt(self, events: list[MatchEvent], state: SharedMatchState) -> str:
        events_text = _events_to_text(events)
        state_summary = _state_to_summary(state)
        recent_utterances = state.recent_utterances_text(3)
        return build_pbp_prompt(events_text, state_summary, recent_utterances)

    def _fallback(self, events: list[MatchEvent], state: SharedMatchState) -> str:
        """Override fallback with more energetic play-by-play style."""
        if not events:
            return ""
        ev = events[-1]  # Most recent event

        from analyser.spatial import coords_to_description
        loc = coords_to_description(*ev.position)

        if ev.event_type == "Shot":
            outcome = ev.details.get("shot_outcome", "")
            if outcome == "Goal":
                return f"GOAL! {ev.player} puts it in the back of the net!"
            elif outcome in ("Saved", "Saved to Post"):
                return f"Great save! Keeper denies {ev.player} from {loc}."
            elif outcome in ("Post", "Bar"):
                return f"Off the post! {ev.player} so close from {loc}."
            elif outcome == "Blocked":
                return f"Blocked! {ev.player} fires in — cleared on the line."
            return f"{ev.player} shoots from {loc}!"

        elif ev.event_type == "Dribble":
            outcome = ev.details.get("dribble_outcome", "Complete")
            if outcome == "Complete":
                return f"{ev.player} beats his man {loc}."
            return f"{ev.player} loses possession {loc}."

        elif ev.event_type in ("Foul Committed",):
            card = ev.details.get("foul_card", "")
            if card == "Red Card":
                return f"RED CARD! {ev.player} is sent off!"
            elif card == "Yellow Card":
                return f"Yellow card for {ev.player}."
            return f"Foul — {ev.player} brings down the attacker {loc}."

        elif ev.event_type == "Substitution":
            replacement = ev.details.get("sub_replacement", "")
            if replacement:
                return f"{ev.player} off, {replacement} on."
            return f"Change for {ev.team}."

        elif ev.event_type == "Goal Keeper":
            gk_type = ev.details.get("gk_type", "")
            if gk_type == "Shot Saved":
                return f"Superb save from {ev.player}!"
            return f"{ev.player} comes to claim {loc}."

        elif ev.event_type == "Pass":
            recipient = ev.details.get("pass_recipient")
            if ev.details.get("goal_assist"):
                return f"ASSIST! {ev.player} finds {recipient} — what a ball!"
            if ev.details.get("cross"):
                return f"{ev.player} whips in a cross from {loc}."
            if recipient:
                return f"{ev.player} plays it to {recipient}."
            return f"{ev.player} with the ball {loc}."

        return f"{ev.player} — {ev.event_type.lower()} for {ev.team}."
