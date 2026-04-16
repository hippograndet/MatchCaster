# backend/commentator/agents/base.py
# BaseAgent ABC: defines the generate() interface and Ollama integration.

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Any, Optional

import httpx

from config import (
    OLLAMA_BASE_URL,
    OLLAMA_MODEL,
    OLLAMA_TIMEOUT_SEC,
    MAX_OUTPUT_TOKENS,
    AGENT_TEMPERATURES,
)
from player.loader import MatchEvent
from analyser.state import SharedMatchState
from analyser.spatial import coords_to_description

logger = logging.getLogger("[AGENT]")


class BaseAgent(ABC):
    """Abstract base for all commentary agents."""

    def __init__(
        self,
        name: str,
        system_prompt: str,
        ollama_url: str = OLLAMA_BASE_URL,
        model: str = OLLAMA_MODEL,
    ) -> None:
        self.name = name
        self.system_prompt = system_prompt
        self.ollama_url = ollama_url
        self.model = model
        self.temperature = AGENT_TEMPERATURES.get(name, 0.7)
        self._log = logging.getLogger(f"[{name.upper()}]")

    @abstractmethod
    def build_prompt(self, events: list[MatchEvent], state: SharedMatchState) -> str:
        """Build the user-turn message given current match context."""
        pass

    def update_system_prompt(self, prompt: str) -> None:
        """Allows director to refresh system prompt (e.g. when personality changes)."""
        self.system_prompt = prompt

    async def generate(
        self,
        events: list[MatchEvent],
        state: SharedMatchState,
        analysis_context: str = "",
        trace: Any = None,
    ) -> str:
        """
        Call Ollama /api/generate, stream tokens, enforce MAX_OUTPUT_TOKENS.
        Returns generated commentary text (stripped).
        Falls back to a template string on any error.
        """
        from debug.override import override_store

        # Capture the 4 prompt layers before building the assembled prompt
        if trace is not None:
            trace.layer_general_context = self.system_prompt
            trace.layer_match_context = _state_to_summary(state)
            trace.layer_recent_play = state.recent_utterances_text(3)
            trace.layer_immediate = _events_to_text(events)

        prompt = self.build_prompt(events, state)
        if analysis_context:
            prompt = f"[MATCH INTELLIGENCE]\n{analysis_context}\n\n{prompt}"

        # Apply one-shot dev override if queued (consumed exactly once)
        override = override_store.consume(self.name)
        effective_system = self.system_prompt
        if override:
            if "system_prompt" in override:
                effective_system = override["system_prompt"]
            if "user_prompt" in override:
                prompt = override["user_prompt"]

        if trace is not None:
            trace.user_prompt_assembled = prompt

        try:
            text = await self._call_ollama(prompt, system_prompt=effective_system, trace=trace)
            text = self._clean(text)
            if text:
                if trace is not None:
                    trace.llm_cleaned_text = text
                self._log.info(f"Generated: {text!r}")
                return text
        except asyncio.CancelledError:
            raise   # propagate cancellation
        except Exception as exc:
            self._log.warning(f"Ollama error ({exc}), using fallback")

        if trace is not None:
            trace.llm_used_fallback = True
        return self._fallback(events, state)

    async def _call_ollama(self, prompt: str, system_prompt: Optional[str] = None, trace: Any = None) -> str:
        """Stream /api/generate and collect output up to MAX_OUTPUT_TOKENS."""
        import json
        import time as _time

        url = f"{self.ollama_url}/api/generate"
        payload = {
            "model": self.model,
            "system": system_prompt if system_prompt is not None else self.system_prompt,
            "prompt": prompt,
            "stream": True,
            "options": {
                "temperature": self.temperature,
                "num_predict": MAX_OUTPUT_TOKENS,
                "num_ctx": 2048,
                "stop": ["\n\n", "###", "---"],
            },
        }

        tokens: list[str] = []
        token_count = 0
        _start = _time.monotonic()

        async with httpx.AsyncClient(timeout=OLLAMA_TIMEOUT_SEC) as client:
            async with client.stream("POST", url, json=payload) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    try:
                        chunk = json.loads(line)
                    except ValueError:
                        continue

                    tok = chunk.get("response", "")
                    if tok:
                        tokens.append(tok)
                        token_count += 1

                    if chunk.get("done") or token_count >= MAX_OUTPUT_TOKENS:
                        break

        raw = "".join(tokens)
        if trace is not None:
            trace.llm_raw_response = raw
            trace.llm_token_count = token_count
            trace.llm_generation_ms = (_time.monotonic() - _start) * 1000
        return raw

    def _clean(self, text: str) -> str:
        """Strip leading/trailing whitespace, remove internal newlines."""
        text = text.strip()
        # Remove lines that are clearly preamble / repetition of instructions
        bad_starts = ("sure", "here", "okay", "of course", "commentary:", "output:", "your commentary")
        first_line = text.split("\n")[0].strip().lower()
        if any(first_line.startswith(b) for b in bad_starts):
            # Take the second line if available
            lines = [l.strip() for l in text.split("\n") if l.strip()]
            text = lines[1] if len(lines) > 1 else lines[0] if lines else ""
        # Collapse newlines to single space
        text = " ".join(text.split())
        return text

    def _fallback(self, events: list[MatchEvent], state: SharedMatchState) -> str:
        """Template-based fallback when Ollama is unavailable."""
        if not events:
            return ""
        ev = events[0]
        loc = coords_to_description(*ev.position)
        if ev.event_type == "Shot":
            outcome = ev.details.get("shot_outcome", "")
            if outcome == "Goal":
                return f"GOAL! {ev.player} scores for {ev.team}!"
            return f"{ev.player} shoots from {loc}."
        elif ev.event_type == "Pass":
            recipient = ev.details.get("pass_recipient", "")
            if recipient:
                return f"{ev.player} plays it to {recipient}."
            return f"{ev.player} with the ball {loc}."
        elif ev.event_type in ("Foul Committed", "Foul Won"):
            return f"Foul by {ev.player} {loc}."
        elif ev.event_type == "Dribble":
            return f"{ev.player} takes on the defender {loc}."
        elif ev.event_type == "Substitution":
            replacement = ev.details.get("sub_replacement", "")
            if replacement:
                return f"{ev.player} is replaced by {replacement}."
            return f"Substitution for {ev.team}."
        return f"{ev.event_type} — {ev.player} for {ev.team}."


# Normalize raw StatsBomb event type names before they reach the LLM
_EVENT_TYPE_DISPLAY: dict[str, str] = {
    "Ball Receipt*":     "receives ball",
    "Ball Recovery":     "recovers ball",
    "50/50":             "50/50 contest",
    "Referee Ball-Drop": "referee ball drop",
    "Half Start":        "half start",
    "Half End":          "half end",
    "Starting XI":       "starting lineup",
}


def _events_to_text(events: list[MatchEvent]) -> str:
    """Convert a list of events to a human-readable string for prompts."""
    lines = []
    for ev in events:
        loc = coords_to_description(*ev.position)
        display_type = _EVENT_TYPE_DISPLAY.get(ev.event_type, ev.event_type)
        line = f"[{display_type}] {ev.player} ({ev.team}) — {loc}"
        if ev.end_position:
            end_loc = coords_to_description(*ev.end_position)
            line += f" → {end_loc}"
        # Add key details
        extras = []
        if ev.details.get("shot_outcome"):
            extras.append(f"outcome: {ev.details['shot_outcome']}")
        if ev.details.get("xg"):
            pass  # Don't expose xG to agents per spec
        if ev.details.get("pass_recipient"):
            extras.append(f"to: {ev.details['pass_recipient']}")
        if ev.details.get("cross"):
            extras.append("cross")
        if ev.details.get("foul_card"):
            extras.append(f"card: {ev.details['foul_card']}")
        if ev.detected_patterns:
            extras.append(f"patterns: {', '.join(ev.detected_patterns)}")
        if extras:
            line += f" ({', '.join(extras)})"
        lines.append(line)
    return "\n".join(lines) if lines else "(no events)"


def _state_to_summary(state: SharedMatchState) -> str:
    """Build a compact state summary string for prompts."""
    poss = state.possession_pct()
    home_stats = state.get_stats(state.home_team)
    away_stats = state.get_stats(state.away_team)

    h = home_stats
    a = away_stats

    lines = [
        f"Score: {state.score_str()} | Minute: {state.minute_str()} | Phase: {state.current_phase}",
        f"Possession: {state.home_team} {poss.get(state.home_team, 50):.0f}% / "
        f"{state.away_team} {poss.get(state.away_team, 50):.0f}%",
    ]
    if h and a:
        lines.append(
            f"Shots: {state.home_team} {h.shots} (on target {h.shots_on_target}) | "
            f"{state.away_team} {a.shots} (on target {a.shots_on_target})"
        )
        lines.append(
            f"Fouls: {state.home_team} {h.fouls} | {state.away_team} {a.fouls}"
        )
        if h.yellow_cards or a.yellow_cards or h.red_cards or a.red_cards:
            lines.append(
                f"Cards: {state.home_team} Y{h.yellow_cards}/R{h.red_cards} | "
                f"{state.away_team} Y{a.yellow_cards}/R{a.red_cards}"
            )
    return "\n".join(lines)
