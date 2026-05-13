"""
ActionSummaryAgent — short-horizon build-up narrative candidate.

Generates a 1-2 sentence description of the sequence of play that led to
a critical moment (shot, goal, red card). Competes with PBP as a candidate
for the same time-block window; the coordinator picks the better voice.
"""
from __future__ import annotations

from config import COMPACT_PROMPTS, OLLAMA_BASE_URL, OLLAMA_MODEL
from analyser.state import SharedMatchState
from player.loader import MatchEvent
from commentator.orchestration.models import CommentaryCandidate

from .base import BaseAgent, _events_to_text, _state_to_summary
from .prompts import (
    build_action_summary_system,
    build_action_summary_user,
    get_personality_modifier,
)


class ActionSummaryAgent(BaseAgent):
    """Generates a build-up narrative candidate for critical-event windows."""

    def __init__(self, personality: str = "neutral") -> None:
        self.personality = personality
        super().__init__(
            name="action_summary",
            system_prompt=build_action_summary_system(personality, compact=COMPACT_PROMPTS),
            ollama_url=OLLAMA_BASE_URL,
            model=OLLAMA_MODEL,
        )
        self.temperature = 0.75

    def build_prompt(self, events: list[MatchEvent], state: SharedMatchState) -> str:
        return build_action_summary_user(
            events_text=_events_to_text(events),
            state_summary=_state_to_summary(state),
            recent_utterances=state.recent_utterances_text(3),
        )

    def update_system_prompt(self, prompt: str) -> None:
        self.system_prompt = prompt

    async def generate_candidate(
        self,
        *,
        window_start: float,
        window_end: float,
        events: list[MatchEvent],
        state: SharedMatchState,
        tone: str = "neutral",
        context_hint: str = "",
    ) -> CommentaryCandidate:
        """
        Generate a build-up narrative candidate for [window_start, window_end).
        Returns a CommentaryCandidate for coordinator selection.
        """
        if tone != self.personality:
            self.system_prompt = build_action_summary_system(tone, compact=COMPACT_PROMPTS)
            self.personality = tone

        events_text = _events_to_text(events)
        state_summary = _state_to_summary(state)
        recent = state.recent_utterances_text(3)

        user_prompt = build_action_summary_user(
            events_text=events_text,
            state_summary=state_summary,
            recent_utterances=recent,
        )
        if context_hint:
            user_prompt = f"CONTEXT: {context_hint}\n\n{user_prompt}"

        try:
            raw = await self._call_llm(user_prompt)
            text = self._clean(raw)
        except Exception:
            text = self._action_fallback(events)

        if not text:
            text = self._action_fallback(events)

        # Confidence: higher when events clearly contain a shot/goal
        has_shot = any(ev.event_type == "Shot" for ev in events)
        confidence = 0.85 if has_shot else 0.70

        return CommentaryCandidate(
            agent_kind="action_summary",
            text=text,
            match_time=state.current_match_time,
            trigger_type="shot" if has_shot else "dense_action",
            confidence=confidence,
            block_start=window_start,
            block_end=window_end,
        )

    def _action_fallback(self, events: list[MatchEvent]) -> str:
        shots = [e for e in events if e.event_type == "Shot"]
        if shots:
            ev = shots[-1]
            outcome = ev.details.get("shot_outcome", "")
            if outcome == "Goal":
                return f"A brilliant move ends with {ev.player} finding the net."
            return f"Good build-up play creates the chance — {ev.player} pulls the trigger."
        passes = [e for e in events if e.event_type == "Pass"]
        if passes:
            return f"Sharp combination play through the lines, {len(passes)} passes linking up the move."
        return ""
