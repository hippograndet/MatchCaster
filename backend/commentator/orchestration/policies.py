"""
Static v1 selection policy for the commentary coordinator.

Scoring logic (higher = better candidate):
  1. trigger priority  — critical events score higher than filler
  2. confidence        — agent's self-assessed quality
  3. staleness         — penalise candidates close to expiry
  4. repetition        — penalise text too similar to recent utterances

Phase C: add context-window weighting (lull vs. dense-action windows).
"""
from __future__ import annotations

from .models import CommentaryCandidate

# Trigger types → base score (higher = preferred)
_TRIGGER_BASE: dict[str, float] = {
    "goal":         10.0,
    "match_end":    10.0,
    "half_time":     8.0,
    "substitution":  7.0,
    "dense_action":  6.0,
    "shot":          6.0,
    "dead_ball":     4.0,
    "timer":         3.0,
    "time_block":    5.0,   # routine PBP blocks
    "none":          2.0,
}

# Phase C: agent-trigger fit multipliers.
# When multiple candidates compete for the same window, this biases the scorer
# toward the agent whose perspective is most valuable for that trigger type.
# (agent_kind → trigger_type → multiplier)
_AGENT_TRIGGER_FIT: dict[str, dict[str, float]] = {
    "action_summary": {
        "goal":         1.6,   # build-up narrative excels at goal moments
        "shot":         1.5,
        "dense_action": 1.3,
    },
    "context_window": {
        "dead_ball":    1.5,   # significance framing excels during pauses
        "timer":        1.4,
        "post_goal":    1.3,
        "substitution": 1.2,
    },
    "analyst": {
        "substitution": 1.3,
        "half_time":    1.4,
        "post_goal":    1.1,
    },
    # play_by_play: neutral (no fit bonus — it's the baseline)
}

# Overlap fraction above which a candidate is near-duplicate
_DUPLICATE_THRESHOLD = 0.65


class StaticV1SelectionPolicy:

    def score_candidate(
        self,
        candidate: CommentaryCandidate,
        *,
        recent_texts: list[str],
    ) -> float:
        import time as _time

        base = _TRIGGER_BASE.get(candidate.trigger_type, 2.0)
        score = base * candidate.confidence

        # Phase C: agent-trigger fit bonus
        fit = _AGENT_TRIGGER_FIT.get(candidate.agent_kind, {}).get(candidate.trigger_type, 1.0)
        score *= fit

        # Staleness penalty: linearly decay in the last 40% of TTL
        now_ms = int(_time.time() * 1000)
        ttl_total = candidate.expires_at_ms - candidate.created_at_ms
        if ttl_total > 0:
            elapsed = now_ms - candidate.created_at_ms
            fraction_used = elapsed / ttl_total
            if fraction_used > 0.6:
                score *= 1.0 - (fraction_used - 0.6) / 0.4 * 0.5  # up to 50% penalty

        # Repetition penalty (coordinator uses is_near_duplicate() for explicit suppress)
        if self.is_near_duplicate(candidate.text, recent_texts):
            score *= 0.1

        return score

    def tie_break(
        self,
        a: CommentaryCandidate,
        b: CommentaryCandidate,
    ) -> CommentaryCandidate:
        """Prefer shorter speech time (less likely to overlap next block)."""
        return a if a.estimated_speech_ms <= b.estimated_speech_ms else b

    def is_near_duplicate(self, text: str, recent_texts: list[str]) -> bool:
        """True if text overlaps enough with any of the last 3 recent utterances."""
        if not text or not recent_texts:
            return False
        # Strip punctuation for token comparison
        import re
        clean = re.compile(r"[^\w\s]")
        text_tokens = set(clean.sub("", text.lower()).split())
        if not text_tokens:
            return False
        for recent in recent_texts[-3:]:
            recent_tokens = set(clean.sub("", recent.lower()).split())
            overlap = len(text_tokens & recent_tokens) / len(text_tokens)
            if overlap > _DUPLICATE_THRESHOLD:
                return True
        return False
