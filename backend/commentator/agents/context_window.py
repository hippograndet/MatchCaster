"""
ContextWindowAgent — 5m/15m match significance framing candidate.

Generates a 1-2 sentence tactical/contextual insight grounded in the recent
5-minute and 15-minute match trends. Competes with Analyst as a candidate
during dead-ball, timer, and post-goal windows; coordinator picks the better voice.
"""
from __future__ import annotations

from config import COMPACT_PROMPTS, OLLAMA_BASE_URL, OLLAMA_MODEL
from analyser.state import SharedMatchState
from player.loader import MatchEvent
from commentator.orchestration.models import CommentaryCandidate

from .base import BaseAgent, _state_to_summary
from .prompts import (
    build_context_window_system,
    build_context_window_user,
)

# Confidence by trigger type — event-anchored triggers warrant higher confidence
_CONFIDENCE: dict[str, float] = {
    "substitution": 0.80,
    "post_goal":    0.80,
    "dead_ball":    0.70,
    "timer":        0.65,
}


class ContextWindowAgent(BaseAgent):
    """Generates a match-significance candidate using 5m/15m context windows."""

    def __init__(self, personality: str = "neutral") -> None:
        self.personality = personality
        super().__init__(
            name="context_window",
            system_prompt=build_context_window_system(personality, compact=COMPACT_PROMPTS),
            ollama_url=OLLAMA_BASE_URL,
            model=OLLAMA_MODEL,
        )
        self.temperature = 0.55

    def build_prompt(self, events: list[MatchEvent], state: SharedMatchState) -> str:
        return build_context_window_user(
            context_5m="",
            context_15m="",
            state_summary=_state_to_summary(state),
            trigger_type="timer",
            recent_utterances=state.recent_utterances_text(3),
        )

    def update_system_prompt(self, prompt: str) -> None:
        self.system_prompt = prompt

    async def generate_candidate(
        self,
        *,
        match_time: float,
        context_5m: str,
        context_15m: str,
        match_context: str = "",
        state: SharedMatchState,
        tone: str = "neutral",
        trigger_type: str = "timer",
    ) -> CommentaryCandidate:
        """
        Generate a match-significance candidate from 5m/15m context windows.
        Returns a CommentaryCandidate for coordinator selection.
        """
        if tone != self.personality:
            self.system_prompt = build_context_window_system(tone, compact=COMPACT_PROMPTS)
            self.personality = tone

        state_summary = _state_to_summary(state)
        recent = state.recent_utterances_text(3)

        user_prompt = build_context_window_user(
            context_5m=context_5m,
            context_15m=context_15m,
            state_summary=state_summary,
            trigger_type=trigger_type,
            recent_utterances=recent,
            match_context=match_context,
        )

        try:
            raw = await self._call_llm(user_prompt)
            text = self._clean(raw)
        except Exception:
            text = self._context_fallback(state, trigger_type)

        if not text:
            text = self._context_fallback(state, trigger_type)

        return CommentaryCandidate(
            agent_kind="context_window",
            text=text,
            match_time=match_time,
            trigger_type=trigger_type,
            confidence=_CONFIDENCE.get(trigger_type, 0.65),
        )

    def _context_fallback(self, state: SharedMatchState, trigger_type: str) -> str:
        poss = state.possession_pct()
        home_poss = poss.get(state.home_team, 50)
        dominant = state.home_team if home_poss > 55 else (
            state.away_team if home_poss < 45 else None
        )
        if dominant:
            return f"{dominant} have controlled territory in this period — the pattern is clear."
        if trigger_type == "dead_ball":
            return "Both sides are finely balanced. The next phase of play will be decisive."
        return "The match remains in the balance — either side could push on from here."
