"""
CommentaryCoordinator: collects candidates, applies selection policy, emits one decision.

Phase B: receives candidates one at a time (serial agents). Applies staleness + suppression.
Phase C: will receive parallel candidates for the same window and pick the best.
"""
from __future__ import annotations

import logging
import time
from typing import Sequence

from .models import AgentKind, CommentaryCandidate, SelectionDecision
from .policies import StaticV1SelectionPolicy

logger = logging.getLogger("[COORDINATOR]")


class CommentaryCoordinator:

    def __init__(
        self,
        deadline_ms: int = 500,
        enable_legacy_fallback: bool = True,
    ) -> None:
        self._deadline_ms = deadline_ms
        self._enable_legacy_fallback = enable_legacy_fallback
        self._policy = StaticV1SelectionPolicy()

    async def select(
        self,
        *,
        candidates: Sequence[CommentaryCandidate],
        recent_utterances: list[str],
        match_time: float,
    ) -> SelectionDecision:
        """
        Score candidates and return one SelectionDecision.
        selected_candidate_id=None means all candidates were suppressed.
        """
        t0 = time.time()

        live = [c for c in candidates if not c.is_expired]
        if not live:
            logger.debug("Coordinator: all candidates expired")
            return SelectionDecision(
                final_text="",
                selected_agent_kind="legacy",
                reason_codes=["all_expired"],
                decision_latency_ms=int((time.time() - t0) * 1000),
                degraded_mode=True,
            )

        scored = sorted(
            live,
            key=lambda c: self._policy.score_candidate(c, recent_texts=recent_utterances),
            reverse=True,
        )
        best = scored[0]
        score = self._policy.score_candidate(best, recent_texts=recent_utterances)

        # Suppress near-duplicates for non-critical triggers.
        # Critical events (goal, substitution, half_time) always get through.
        _critical = {"goal", "match_end", "half_time", "substitution"}
        is_dup = self._policy.is_near_duplicate(best.text, recent_utterances)
        if is_dup and best.trigger_type not in _critical:
            logger.debug(
                f"Coordinator: suppressing {best.agent_kind!r} "
                f"(trigger={best.trigger_type}) — near-duplicate"
            )
            return SelectionDecision(
                final_text="",
                selected_agent_kind=best.agent_kind,
                reason_codes=["suppressed_near_duplicate"],
                decision_latency_ms=int((time.time() - t0) * 1000),
                degraded_mode=False,
            )

        reason = f"selected_{best.agent_kind}_score_{score:.2f}"
        logger.debug(
            f"Coordinator: selected {best.agent_kind!r} "
            f"(trigger={best.trigger_type}, score={score:.2f}) "
            f"— {best.text[:60]!r}"
        )
        return SelectionDecision(
            final_text=best.text,
            selected_agent_kind=best.agent_kind,
            selected_candidate_id=best.candidate_id,
            reason_codes=[reason],
            decision_latency_ms=int((time.time() - t0) * 1000),
            degraded_mode=False,
        )

    def invalidate_stale(self, *, current_match_time: float) -> int:
        """No-op in Phase B (no persistent candidate queue). Returns 0."""
        return 0
