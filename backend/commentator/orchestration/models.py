"""
Shared dataclasses for the multi-agent commentary coordinator.

Phase B: CommentaryCandidate and SelectionDecision used by PBP and Analyst.
Phase C: ActionSummaryAgent and ContextWindowAgent will add candidates here.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Literal, Optional

AgentKind = Literal["play_by_play", "analyst", "action_summary", "context_window", "legacy"]

_WORDS_PER_MS = 2.17 / 1000  # ~130 words/min in speech


def _estimate_speech_ms(text: str) -> int:
    """Rough speech-time estimate from word count."""
    return max(500, int(len(text.split()) / _WORDS_PER_MS))


@dataclass
class CommentaryCandidate:
    agent_kind: AgentKind
    text: str
    match_time: float
    trigger_type: str
    confidence: float                       # 0–1; agent's self-assessed quality
    candidate_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    estimated_speech_ms: int = field(default=0)
    created_at_ms: int = field(default_factory=lambda: int(time.time() * 1000))
    expires_at_ms: int = field(default=0)   # 0 = never expires
    event_id: Optional[str] = None
    block_start: Optional[float] = None
    block_end: Optional[float] = None
    metadata: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.estimated_speech_ms == 0:
            self.estimated_speech_ms = _estimate_speech_ms(self.text)
        if self.expires_at_ms == 0:
            # Default TTL: analyst 20s real-time, PBP 30s real-time
            ttl_ms = 20_000 if self.agent_kind == "analyst" else 30_000
            self.expires_at_ms = self.created_at_ms + ttl_ms

    @property
    def is_expired(self) -> bool:
        return int(time.time() * 1000) > self.expires_at_ms


@dataclass
class SelectionDecision:
    final_text: str
    selected_agent_kind: AgentKind
    decision_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    selected_candidate_id: Optional[str] = None   # None = suppressed / no candidates
    reason_codes: list[str] = field(default_factory=list)
    decision_latency_ms: int = 0
    degraded_mode: bool = False
