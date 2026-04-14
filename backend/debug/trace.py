# backend/debug/trace.py
# PipelineTrace: captures the full commentator pipeline for developer inspection.

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field, asdict


@dataclass
class PipelineTrace:
    trace_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    wall_time: float = field(default_factory=time.time)

    # --- Stage 1: Trigger (filled in director/router.py) ---
    trigger_events: list[dict] = field(default_factory=list)
    classification: str = ""        # CRITICAL / NOTABLE / ROUTINE / dead-air
    agent_selected: str = ""
    selection_reason: str = ""

    # --- Stage 2: LLM — 4 prompt layers (filled in agents/base.py) ---
    layer_general_context: str = ""     # system prompt (role + personality)
    layer_match_context: str = ""       # _state_to_summary(state)
    layer_recent_play: str = ""         # state.recent_utterances_text(3)
    layer_immediate: str = ""           # _events_to_text(events)
    user_prompt_assembled: str = ""     # the full user turn as actually sent
    llm_raw_response: str = ""
    llm_cleaned_text: str = ""
    llm_token_count: int = 0
    llm_generation_ms: float = 0.0
    llm_used_fallback: bool = False

    # --- Stage 3: TTS (filled in tts/engine.py) ---
    tts_voice: str = ""
    tts_backend: str = ""               # "piper" | "say" | "none"
    tts_synthesis_ms: float = 0.0
    tts_audio_duration_sec: float = 0.0

    # --- Computed at emit time ---
    end_to_end_ms: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)
