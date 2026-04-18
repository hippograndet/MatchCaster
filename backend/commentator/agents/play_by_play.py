# backend/commentator/agents/play_by_play.py
# Play-by-Play agent: pre-generates a batch of tagged commentary lines for a
# window of upcoming events, then individual lines are dispatched on event arrival.

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Optional

from commentator.agents.base import BaseAgent, _events_to_text, _state_to_summary
from commentator.agents.prompts import (
    build_pbp_batch_system,
    build_pbp_batch_prompt,
    build_flow_block_system,
    build_flow_block_user,
)
from commentator.queue import CommentaryLine, CommentaryBlock
from commentator.tts.engine import get_tts_engine
from player.loader import MatchEvent
from analyser.state import SharedMatchState

logger = logging.getLogger("[PLAY_BY_PLAY]")


class PlayByPlayAgent(BaseAgent):
    def __init__(self, personality: str = "neutral", **kwargs) -> None:
        super().__init__(
            name="play_by_play",
            system_prompt=build_pbp_batch_system(personality),
            **kwargs,
        )
        self.personality = personality

    def build_prompt(self, events: list[MatchEvent], state: SharedMatchState) -> str:
        """Legacy single-event prompt (used by BaseAgent.generate fallback path)."""
        events_text = _events_to_text(events)
        state_summary = _state_to_summary(state)
        recent_utterances = state.recent_utterances_text(3)
        return build_pbp_batch_prompt(events_text, state_summary, recent_utterances)

    # ------------------------------------------------------------------
    # Batch generation — main entry point used by Director
    # ------------------------------------------------------------------

    async def generate_batch(
        self,
        events: list[MatchEvent],
        state: SharedMatchState,
        analysis_context: str = "",
        analyst_context: str = "",
        is_opening: bool = False,
        is_high_speed: bool = False,
        match_meta: str = "",
        trace: Any = None,
    ) -> list[CommentaryLine]:
        """
        Generate a batch of commentary lines for a window of events.
        Returns a list of CommentaryLine with text set but audio_bytes=None
        (TTS is synthesized separately by the Director).
        """
        if not events:
            return []

        events_text = _events_to_text(events)
        state_summary = _state_to_summary(state)
        recent_utterances = state.recent_utterances_text(3)

        prompt = build_pbp_batch_prompt(
            events_text=events_text,
            state_summary=state_summary,
            recent_utterances=recent_utterances,
            analyst_context=analyst_context,
            is_opening=is_opening,
            is_high_speed=is_high_speed,
            match_meta=match_meta,
        )
        if analysis_context:
            prompt = f"[MATCH INTELLIGENCE]\n{analysis_context}\n\n{prompt}"

        try:
            raw = await self._call_ollama(prompt, system_prompt=self.system_prompt, trace=trace)
            lines = self._parse_batch_json(raw, events)
            if lines:
                return lines
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning(f"Batch generation error ({type(exc).__name__}: {exc}), using fallback")

        return self._fallback_batch(events, state)

    def _parse_batch_json(
        self, raw: str, events: list[MatchEvent]
    ) -> list[CommentaryLine]:
        """
        Parse LLM JSON output into CommentaryLine list.
        Falls back to sequential line matching if JSON is malformed.
        """
        raw = raw.strip()

        # Strip any accidental markdown fences
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()
        if raw.endswith("```"):
            raw = raw[:-3].strip()

        # Try JSON parse
        try:
            data = json.loads(raw)
            if isinstance(data, list):
                lines = []
                for item in data:
                    if isinstance(item, dict) and "event_id" in item and "text" in item:
                        text = self._clean(str(item["text"]))
                        if text:
                            lines.append(CommentaryLine(
                                event_id=str(item["event_id"]),
                                text=text,
                                agent_name="play_by_play",
                            ))
                if lines:
                    logger.debug(f"Parsed {len(lines)} batch lines from JSON")
                    return lines
        except (json.JSONDecodeError, ValueError):
            pass

        # Sequential fallback: split by newline, match to events in order
        logger.debug("JSON parse failed — using sequential line fallback")
        text_lines = [l.strip() for l in raw.split("\n") if l.strip()]
        # Filter out lines that look like JSON artifacts
        text_lines = [l for l in text_lines if not l.startswith(("{", "}", "[", "]"))]
        text_lines = [self._clean(l) for l in text_lines if self._clean(l)]

        if not text_lines:
            return []

        # Match lines to notable events (skip events we have no line for)
        notable = [e for e in events if e.priority in ("critical", "notable")]
        if not notable:
            notable = events

        lines = []
        for i, text in enumerate(text_lines[:5]):  # max 5 lines
            if i < len(notable):
                lines.append(CommentaryLine(
                    event_id=notable[i].id,
                    text=text,
                    agent_name="play_by_play",
                ))
        return lines

    def _fallback_batch(
        self, events: list[MatchEvent], state: SharedMatchState
    ) -> list[CommentaryLine]:
        """Template-based fallback: one line for the most notable event."""
        notable = [e for e in events if e.priority == "critical"]
        if not notable:
            notable = [e for e in events if e.priority == "notable"]
        if not notable:
            notable = events[-1:] if events else []

        lines = []
        for ev in notable[:2]:
            text = self._fallback_single(ev, state)
            if text:
                lines.append(CommentaryLine(
                    event_id=ev.id,
                    text=text,
                    agent_name="play_by_play",
                ))
        return lines

    def _fallback_single(self, ev: MatchEvent, state: SharedMatchState) -> str:
        from analyser.spatial import coords_to_description
        loc = coords_to_description(*ev.position)

        if ev.event_type == "Shot":
            outcome = ev.details.get("shot_outcome", "")
            if outcome == "Goal":
                score = state.score
                score_str = f"{score.get('home', 0)}-{score.get('away', 0)}"
                return f"GOAL! {ev.player} puts it away! The score is now {score_str}."
            elif outcome in ("Saved", "Saved to Post"):
                return f"Great save! The keeper denies {ev.player} from {loc}."
            elif outcome in ("Post", "Bar"):
                return f"Off the woodwork! {ev.player} so close from {loc}."
            elif outcome == "Blocked":
                return f"Blocked! {ev.player} fires in — cleared on the line."
            return f"{ev.player} shoots from {loc}!"

        elif ev.event_type == "Dribble":
            if ev.details.get("dribble_outcome") == "Complete":
                return f"{ev.player} beats his man {loc}."
            return f"{ev.player} loses it {loc}."

        elif ev.event_type in ("Foul Committed",):
            card = ev.details.get("foul_card", "")
            if card == "Red Card":
                return f"RED CARD! {ev.player} is off!"
            elif card == "Yellow Card":
                return f"Yellow card for {ev.player}."
            return f"Foul — {ev.player} brings down the attacker {loc}."

        elif ev.event_type == "Substitution":
            replacement = ev.details.get("sub_replacement", "")
            if replacement:
                return f"{ev.player} makes way for {replacement}."
            return f"Change for {ev.team}."

        elif ev.event_type == "Goal Keeper":
            if ev.details.get("gk_type") == "Shot Saved":
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

    def _fallback(self, events: list[MatchEvent], state: SharedMatchState) -> str:
        """BaseAgent fallback for single-call path."""
        if not events:
            return ""
        return self._fallback_single(events[-1], state)

    # ------------------------------------------------------------------
    # Flow-block generation — main entry point for time-block PBP
    # ------------------------------------------------------------------

    async def generate_flow_block(
        self,
        block_start: float,
        block_end: float,
        events: list[MatchEvent],
        state: SharedMatchState,
        analysis_context: str = "",
        analyst_context: str = "",
        match_meta: str = "",
        is_opening: bool = False,
    ) -> CommentaryBlock:
        """
        Generate one flowing commentary paragraph covering the block window.
        Returns a CommentaryBlock with text set; audio_bytes synthesized separately.
        """
        is_quiet = len(events) < 3

        events_text = _events_to_text(events) if events else "(no events — dead ball or pause)"
        state_summary = _state_to_summary(state)
        recent_utterances = state.recent_utterances_text(3)

        system = build_flow_block_system(getattr(self, "personality", "neutral"))
        user = build_flow_block_user(
            events_text=events_text,
            state_summary=state_summary,
            recent_utterances=recent_utterances,
            analyst_context=analyst_context,
            match_meta=match_meta,
            is_opening=is_opening,
            is_quiet=is_quiet,
        )
        if analysis_context:
            user = f"[MATCH INTELLIGENCE]\n{analysis_context}\n\n{user}"

        text = ""
        try:
            raw = await self._call_ollama(user, system_prompt=system)
            text = self._clean(raw)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning(f"Flow-block generation error ({type(exc).__name__}: {exc}), using fallback")
            text = self._fallback_block(events, state, is_opening)

        if not text:
            text = self._fallback_block(events, state, is_opening)

        return CommentaryBlock(
            block_start=block_start,
            block_end=block_end,
            text=text,
            agent_name="play_by_play",
        )

    def _fallback_block(
        self, events: list[MatchEvent], state: SharedMatchState, is_opening: bool
    ) -> str:
        """Simple template fallback for flow blocks when Ollama fails."""
        if is_opening:
            home = state.home_team or "Home"
            away = state.away_team or "Away"
            return f"And we are underway — {home} vs {away}, it all begins now."
        if not events:
            return "Play has paused momentarily. Both sides take a breath."
        # Use the most notable event in the block
        critical = [e for e in events if e.priority == "critical"]
        notable = [e for e in events if e.priority == "notable"]
        ev = (critical or notable or events)[-1]
        return self._fallback_single(ev, state) or "Play continues."
