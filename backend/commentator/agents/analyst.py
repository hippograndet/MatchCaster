# backend/commentator/agents/analyst.py
# Analyst agent: expert co-commentator.
# Provides macro insights — momentum, tactics, substitutions, stats.
# Replaces the old Tactical + Stats agents.

from __future__ import annotations

import logging
from typing import Any, Optional

from commentator.agents.base import BaseAgent, _state_to_summary
from commentator.agents.prompts import build_analyst_system, build_analyst_prompt
from player.loader import MatchEvent
from analyser.state import SharedMatchState

logger = logging.getLogger("[ANALYST]")


class AnalystAgent(BaseAgent):
    def __init__(self, **kwargs) -> None:
        super().__init__(
            name="analyst",
            system_prompt=build_analyst_system("neutral"),
            **kwargs,
        )

    def build_prompt(self, events: list[MatchEvent], state: SharedMatchState) -> str:
        """Legacy single-call prompt path."""
        state_summary = _state_to_summary(state)
        recent_utterances = state.recent_utterances_text(3)
        return build_analyst_prompt(
            state_summary=state_summary,
            snapshot_text="",
            recent_utterances=recent_utterances,
            trigger_type="timer",
        )

    async def generate_insight(
        self,
        state: SharedMatchState,
        snapshot_text: str = "",
        trigger_type: str = "timer",
        trigger_detail: str = "",
        trace: Any = None,
    ) -> str:
        """
        Generate a single macro insight line.
        Returns plain text (not event-tagged).
        """
        state_summary = _state_to_summary(state)
        recent_utterances = state.recent_utterances_text(3)

        prompt = build_analyst_prompt(
            state_summary=state_summary,
            snapshot_text=snapshot_text,
            recent_utterances=recent_utterances,
            trigger_type=trigger_type,
            trigger_detail=trigger_detail,
        )

        try:
            raw = await self._call_ollama(prompt, system_prompt=self.system_prompt, trace=trace)
            text = self._clean(raw)
            if text:
                logger.info(f"Insight ({trigger_type}): {text!r}")
                return text
        except Exception as exc:
            logger.warning(f"Analyst error ({exc}), using fallback")

        return self._fallback_insight(state, trigger_type, trigger_detail)

    def _fallback_insight(
        self,
        state: SharedMatchState,
        trigger_type: str,
        trigger_detail: str,
    ) -> str:
        poss = state.possession_pct()
        dominant = max(poss, key=lambda t: poss[t]) if poss else state.home_team
        dominant_pct = poss.get(dominant, 50)

        if trigger_type == "substitution" and trigger_detail:
            return f"A tactical change there — the manager looking to shift the balance of this game."
        if trigger_type == "post_goal":
            score = state.score
            if score.get("home", 0) != score.get("away", 0):
                return f"That goal changes the dynamic entirely. The trailing side must now commit forward."
            return f"We're level again — this match is perfectly poised."
        if trigger_type == "half_time":
            return (
                f"{dominant} have had {dominant_pct:.0f}% possession this half. "
                f"The second period will tell us everything."
            )

        # Generic timer fallback
        home_stats = state.get_stats(state.home_team)
        away_stats = state.get_stats(state.away_team)
        if home_stats and away_stats:
            h, a = home_stats, away_stats
            if h.shots != a.shots:
                more = state.home_team if h.shots > a.shots else state.away_team
                shots = max(h.shots, a.shots)
                return f"{more} have created more — {shots} shots so far and pressing for the breakthrough."
        return f"{dominant} have been the dominant side, keeping the ball well at {dominant_pct:.0f}%."

    def _fallback(self, events: list[MatchEvent], state: SharedMatchState) -> str:
        return self._fallback_insight(state, "timer", "")
