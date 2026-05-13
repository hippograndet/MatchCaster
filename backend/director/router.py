# backend/director/router.py
# Director: orchestrates the time-block PBP + analyst commentary system.
#
# Architecture:
#   _block_scheduler_loop   — keeps PBP_BLOCKS_AHEAD flow blocks pre-generated
#   _dispatch_blocks_loop   — time-triggers blocks when clock reaches block_start
#   _analyst_scheduler_loop — fires analyst on timer + event triggers + dead-ball
#
# PBP commentary is one paragraph per 15-game-second block (scales with speed).
# Each block covers ALL events in its window; dispatched by clock time, not events.

from __future__ import annotations

import asyncio
import logging
import random
from collections import deque
from typing import Optional, Callable, Awaitable

from config import (
    MAX_CONCURRENT_AGENT_CALLS,
    PBP_BLOCK_DURATION_GAME_SEC,
    PBP_BLOCKS_AHEAD,
    ANALYST_MIN_GAP_GAME_SEC,
    ANALYST_MAX_GAP_GAME_SEC,
    ANALYST_BLOCK_FIRST_SEC,
    GOAL_ANALYST_COOLDOWN_SEC,
    MAX_EVENTS_PER_BATCH,
    DEFAULT_SPEED_MULTIPLIER,
    DEV_MODE,
    ENABLE_DIRECTOR_SELECTION_POLICY,
)
from commentator.orchestration.coordinator import CommentaryCoordinator
from commentator.orchestration.models import CommentaryCandidate
from debug.trace import PipelineTrace
from analyser.classifier import classify_and_tag, SequenceDetector
from analyser.engine import AnalysisSnapshot
from analyser.state import SharedMatchState, AgentUtterance
from player.loader import MatchEvent
from commentator.agents.play_by_play import PlayByPlayAgent
from commentator.agents.analyst import AnalystAgent
from commentator.agents.action_summary import ActionSummaryAgent
from commentator.agents.context_window import ContextWindowAgent
from commentator.queue import AudioQueue, EventTaggedQueue, CommentaryBlock, TimeBlockQueue
from commentator.tts.engine import get_tts_engine

logger = logging.getLogger("[DIRECTOR]")

BroadcastCallback = Callable[[dict], Awaitable[None]]


class Director:
    def __init__(
        self,
        state: SharedMatchState,
        audio_queue: AudioQueue,
        event_tagged_queue: EventTaggedQueue,
        broadcast_cb: Optional[BroadcastCallback] = None,
    ) -> None:
        self.state = state
        self.audio_queue = audio_queue
        self.event_tagged_queue = event_tagged_queue
        self.broadcast_cb = broadcast_cb

        self._pbp = PlayByPlayAgent()
        self._analyst = AnalystAgent()
        self._action_summary = ActionSummaryAgent()    # Phase C: build-up narrative
        self._context_agent = ContextWindowAgent()     # Phase C: 5m/15m significance
        self._tts = get_tts_engine()
        self._seq_detector = SequenceDetector()
        self._sem = asyncio.Semaphore(MAX_CONCURRENT_AGENT_CALLS)

        # Pause / match state
        self.is_paused: bool = True   # starts paused; MatchSession unpauses on "play"
        self._match_ended: bool = False
        self.personality: str = "neutral"

        # Speed (base speed tracked for block duration scaling only — Clock owns enforcement)
        self._base_speed: float = DEFAULT_SPEED_MULTIPLIER

        # Time-block PBP scheduler state
        self.time_block_queue: TimeBlockQueue = TimeBlockQueue()
        self._next_block_start: float = 0.0      # game-time frontier for block generation
        self._opening_done: bool = False          # first block scene-setter fired
        self._block_scheduler_task: Optional[asyncio.Task] = None
        self._dispatch_blocks_task: Optional[asyncio.Task] = None
        self._preload_done: asyncio.Event = asyncio.Event()   # set when first block is ready

        # Analyst scheduler state
        self._analyst_scheduler_task: Optional[asyncio.Task] = None
        self._last_analyst_game_time: float = -999.0
        self._analyst_cooldown_until: float = 0.0   # game-time block (post-goal)
        self._analyst_context: str = ""              # last analyst line, fed to PBP

        # Context injected by MatchSession
        self._match_context: str = ""
        self._pbp_context: str = ""
        self._analyst_ctx_snapshot: str = ""

        # All match events (set by MatchSession after loading)
        self._all_events: list[MatchEvent] = []

        # Decision log: ring buffer of trigger/release decisions for offline debug review.
        # Each entry: {type, trigger, match_time, ...}. Not broadcast (Phase D).
        self._decision_log: deque[dict] = deque(maxlen=50)

        # Phase B coordinator (active only when ENABLE_DIRECTOR_SELECTION_POLICY=True)
        self._coordinator = CommentaryCoordinator(enable_legacy_fallback=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        loop = asyncio.get_event_loop()
        self._block_scheduler_task = loop.create_task(self._block_scheduler_loop())
        self._dispatch_blocks_task = loop.create_task(self._dispatch_blocks_loop())
        self._analyst_scheduler_task = loop.create_task(self._analyst_scheduler_loop())
        logger.info("Director started (paused=True, waiting for play)")

    def stop(self) -> None:
        self.is_paused = True
        self._match_ended = True
        for t in (self._block_scheduler_task, self._dispatch_blocks_task, self._analyst_scheduler_task):
            if t:
                t.cancel()

    def set_paused(self, paused: bool) -> None:
        # Idempotency guard — prevents duplicate generation from double-play calls.
        if self.is_paused == paused:
            return
        self.is_paused = paused
        logger.info(f"Director {'paused' if paused else 'resumed'} at {self.state.current_match_time:.1f}s")
        if not paused and self._all_events:
            current_time = self.state.current_match_time
            # Only spawn initial blocks if pre-generation hasn't already advanced
            # _next_block_start past the current time (avoids duplicate generation).
            if self._next_block_start <= current_time:
                self._next_block_start = current_time
                loop = asyncio.get_event_loop()
                block_dur = self._compute_block_duration()
                for i in range(PBP_BLOCKS_AHEAD):
                    bstart = current_time + i * block_dur
                    bend = bstart + block_dur
                    loop.create_task(self._generate_pbp_block(bstart, bend))
                self._next_block_start = current_time + PBP_BLOCKS_AHEAD * block_dur

    def pregenerate_blocks(self) -> None:
        """Pre-generate opening blocks while still paused (called after warmup).
        Gives Ollama a head start so blocks are ready (or near-ready) when play is pressed."""
        if not self._all_events or self._preload_done.is_set():
            return
        block_dur = self._compute_block_duration()
        loop = asyncio.get_event_loop()
        for i in range(PBP_BLOCKS_AHEAD):
            bstart = float(i) * block_dur
            loop.create_task(self._generate_pbp_block(bstart, bstart + block_dur, pregenerate=True))
        self._next_block_start = float(PBP_BLOCKS_AHEAD) * block_dur
        logger.info(f"Pre-generating {PBP_BLOCKS_AHEAD} opening blocks while loading")

    def set_base_speed(self, speed: float) -> None:
        self._base_speed = speed

    def set_match_context(self, context: str) -> None:
        self._match_context = context

    def set_all_events(self, events: list[MatchEvent]) -> None:
        """Called by MatchSession on load. Pre-classifies all events so the
        priority filter in batch generation works immediately."""
        for ev in events:
            classify_and_tag(ev)
        self._all_events = events
        logger.info(f"Director loaded {len(events)} events (pre-classified)")

    def set_analysis_snapshot(self, snapshot: AnalysisSnapshot) -> None:
        """Called each tick by MatchSession."""
        parts = []
        if self._match_context:
            parts.append(self._match_context)
        if snapshot.short_term_text:
            parts.append(f"RECENT PATTERN: {snapshot.short_term_text}")
        if snapshot.long_term_text:
            parts.append(f"MATCH PICTURE: {snapshot.long_term_text}")
        self._pbp_context = "\n".join(parts)

        # Analyst context: match picture + totals
        a_parts = []
        if self._match_context:
            a_parts.append(self._match_context)
        if snapshot.short_term_text:
            a_parts.append(snapshot.short_term_text)
        if snapshot.long_term_text:
            a_parts.append(snapshot.long_term_text)
        if snapshot.match_totals_text:
            a_parts.append(f"TOTALS:\n{snapshot.match_totals_text}")
        self._analyst_ctx_snapshot = "\n".join(a_parts)

    def on_seek(self, target_time: float) -> None:
        """Called by MatchSession on seek — clear pre-generated blocks, reset pointer."""
        self.event_tagged_queue.clear()
        self.time_block_queue.clear()
        self._next_block_start = target_time
        self._opening_done = True   # don't re-fire the opening scene-setter after a seek
        # Reset preload gate so dispatch_blocks_loop waits for new blocks
        self._preload_done.clear()
        logger.info(f"Director seek updated to {target_time:.0f}s")

    def on_loading_start(self, reason: str) -> None:
        """Pause commentary dispatch while a loading operation is in progress."""
        self.is_paused = True
        logger.info(f"Director paused for loading: {reason}")

    def on_loading_end(self) -> None:
        """Called when loading is complete. Caller decides whether to unpause."""
        logger.info("Director loading ended")

    # ------------------------------------------------------------------
    # Event processing (state updates + trigger detection)
    # ------------------------------------------------------------------

    async def process_events(self, events: list[MatchEvent], match_time: float) -> None:
        """
        Update match state and detect analyst triggers.
        Commentary is NOT generated here — it's pre-generated by the batch scheduler.
        """
        if not events or self._match_ended:
            return

        for ev in events:
            classify_and_tag(ev)
            patterns = self._seq_detector.add(ev)
            ev.detected_patterns = list(set(ev.detected_patterns + patterns))

        trigger_type = self._classify_trigger(events, match_time)
        self._decision_log.append({
            "type": "trigger_classified",
            "trigger": trigger_type,
            "match_time": match_time,
            "event_count": len(events),
        })

        # Check match end
        for ev in events:
            if ev.event_type == "Half End" and ev.details.get("period", 1) >= 2:
                await self._handle_match_end(ev)
                return

        self.state.update(events, match_time)

        # Broadcast raw events
        if self.broadcast_cb:
            for ev in events:
                await self._safe_broadcast({
                    "type": "event",
                    "data": self._serialize_event(ev),
                    "state": self.state.to_dict(),
                })

        # Goal detected → block analyst, schedule post-goal analyst
        # Speed near goals is now handled by SpeedCurve in MatchClock.
        is_goal = any(
            ev.event_type == "Shot" and ev.details.get("shot_outcome") == "Goal"
            for ev in events
        )
        if is_goal:
            self._analyst_cooldown_until = match_time + GOAL_ANALYST_COOLDOWN_SEC
            asyncio.get_event_loop().create_task(
                self._schedule_post_goal_analyst(match_time)
            )

        # Substitution → trigger analyst immediately (if not blocked)
        for ev in events:
            if ev.event_type == "Substitution" and not self.is_paused:
                replacement = ev.details.get("sub_replacement", ev.player)
                detail = f"{ev.player} replaced by {replacement} ({ev.team})"
                asyncio.get_event_loop().create_task(
                    self._fire_analyst("substitution", detail)
                )
                break

        # Half-time
        for ev in events:
            if ev.event_type == "Half End" and ev.details.get("period", 1) == 1:
                asyncio.get_event_loop().create_task(
                    self._fire_analyst("half_time", "")
                )
                break

    # ------------------------------------------------------------------
    # Time-block scheduler loop
    # ------------------------------------------------------------------

    async def _block_scheduler_loop(self) -> None:
        """
        Keeps PBP_BLOCKS_AHEAD blocks pre-generated ahead of current game time.
        Fires every 300 ms; spawns background tasks for any blocks that need generating.
        """
        try:
            while not self._match_ended:
                await asyncio.sleep(0.3)

                if self.is_paused or not self._all_events:
                    continue

                current_time = self.state.current_match_time
                block_dur = self._compute_block_duration()
                lookahead = block_dur * PBP_BLOCKS_AHEAD
                target_frontier = current_time + lookahead

                while self._next_block_start < target_frontier:
                    bstart = self._next_block_start
                    bend = bstart + block_dur
                    self._next_block_start = bend
                    asyncio.get_event_loop().create_task(
                        self._generate_pbp_block(bstart, bend)
                    )

        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.error(f"Block scheduler error: {exc}")

    def _compute_block_duration(self) -> float:
        """
        Game-seconds per block.
        Scales with playback speed so real-time per block stays ~15s.
        """
        return min(max(PBP_BLOCK_DURATION_GAME_SEC, PBP_BLOCK_DURATION_GAME_SEC * self._base_speed), 45.0)

    async def _generate_pbp_block(self, block_start: float, block_end: float, *, pregenerate: bool = False) -> None:
        """Generate one flow-block for [block_start, block_end).

        Phase C: for critical-event blocks (shots/goals/red cards), runs ActionSummaryAgent
        in parallel with PBP and lets the coordinator pick the better candidate.
        Each LLM call owns its own semaphore slot — no nested locking.
        """
        if self._match_ended:
            return

        is_opening = not self._opening_done and block_start < 5.0
        events = [
            e for e in self._all_events
            if block_start <= e.timestamp_sec < block_end
        ][:MAX_EVENTS_PER_BATCH]
        is_quiet = len(events) < 3

        # Always generate PBP block
        pbp_task = asyncio.get_event_loop().create_task(
            self._llm_pbp_block(block_start, block_end, events, is_opening, pregenerate=pregenerate)
        )

        # Phase C: spawn ActionSummaryAgent in parallel for critical-event blocks
        action_task = None
        if ENABLE_DIRECTOR_SELECTION_POLICY and self._block_has_critical_event(events) and not is_opening:
            action_task = asyncio.get_event_loop().create_task(
                self._llm_action_summary(block_start, block_end, events)
            )

        # Await results
        if action_task:
            results = await asyncio.gather(pbp_task, action_task, return_exceptions=True)
            block = results[0] if not isinstance(results[0], Exception) else None
            action_candidate = results[1] if isinstance(results[1], CommentaryCandidate) else None
        else:
            block = await pbp_task
            action_candidate = None

        if block is None:
            if not self._preload_done.is_set():
                self._preload_done.set()
            return

        # Coordinator: pick between PBP and ActionSummary when both are available
        if action_candidate and ENABLE_DIRECTOR_SELECTION_POLICY:
            pbp_candidate = CommentaryCandidate(
                agent_kind="play_by_play",
                text=block.text,
                match_time=self.state.current_match_time,
                trigger_type="time_block",
                confidence=0.8,
                block_start=block_start,
                block_end=block_end,
            )
            recent = [u.text for u in list(self.state.agent_utterances)[-5:]]
            decision = await self._coordinator.select(
                candidates=[pbp_candidate, action_candidate],
                recent_utterances=recent,
                match_time=self.state.current_match_time,
            )
            self._decision_log.append({
                "type": "coordinator_pbp_vs_action",
                "match_time": self.state.current_match_time,
                "selected_kind": decision.selected_agent_kind,
                "block_start": block_start,
                "latency_ms": decision.decision_latency_ms,
            })
            if decision.selected_candidate_id is not None and decision.final_text != block.text:
                block.text = decision.final_text
                block.agent_name = decision.selected_agent_kind

        if is_opening:
            self._opening_done = True
        if not self._preload_done.is_set():
            self._preload_done.set()

        await self._synthesize_block(block)
        self.time_block_queue.store([block])
        logger.debug(
            f"Block ready: [{block_start:.0f}s–{block_end:.0f}s] "
            f"({'quiet' if is_quiet else 'active'}) {block.text[:60]!r}"
        )

        if is_quiet and not is_opening:
            current_time = self.state.current_match_time
            can_fire = (
                not self._is_in_analyst_cooldown(current_time)
                and current_time - self._last_analyst_game_time >= 60.0
            )
            if can_fire:
                asyncio.get_event_loop().create_task(
                    self._fire_analyst("dead_ball", "")
                )

    async def _llm_pbp_block(
        self,
        block_start: float,
        block_end: float,
        events: list[MatchEvent],
        is_opening: bool,
        *,
        pregenerate: bool = False,
    ) -> "CommentaryBlock | None":
        """PBP LLM call — owns one semaphore slot."""
        async with self._sem:
            if self._match_ended:
                return None
            if self.is_paused and not pregenerate:
                return None
            try:
                return await self._pbp.generate_flow_block(
                    block_start=block_start,
                    block_end=block_end,
                    events=events,
                    state=self.state,
                    analysis_context=self._pbp_context,
                    analyst_context=self._analyst_context,
                    match_meta=self._match_context,
                    is_opening=is_opening,
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error(f"PBP block generation error: {exc}")
                return None

    async def _llm_action_summary(
        self,
        block_start: float,
        block_end: float,
        events: list[MatchEvent],
    ) -> "CommentaryCandidate | None":
        """ActionSummaryAgent LLM call — owns one semaphore slot (parallel to PBP)."""
        async with self._sem:
            try:
                return await self._action_summary.generate_candidate(
                    window_start=block_start,
                    window_end=block_end,
                    events=events,
                    state=self.state,
                    tone=self.personality,
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning(f"ActionSummary generation error: {exc}")
                return None

    async def _synthesize_block(self, block: CommentaryBlock) -> None:
        """Synthesize TTS for one commentary block in place."""
        try:
            if self._tts.available:
                audio = await self._tts.synthesize(block.text, block.agent_name)
                block.audio_bytes = audio
            block.ready = True
        except Exception as exc:
            logger.warning(f"TTS failed for block: {exc}")
            block.ready = True  # mark ready even without audio

    # ------------------------------------------------------------------
    # Time-block dispatch loop
    # ------------------------------------------------------------------

    async def _dispatch_blocks_loop(self) -> None:
        """
        Time-triggered: pop and broadcast blocks whose block_start ≤ current_match_time.
        Waits for the preload gate before starting, ensuring commentary is ready before
        the first block fires.
        """
        try:
            # Wait until at least one block has been pre-generated
            await self._preload_done.wait()

            while not self._match_ended:
                await asyncio.sleep(0.1)

                if self.is_paused:
                    continue

                current_time = self.state.current_match_time
                ready_blocks = self.time_block_queue.pop_ready(current_time)
                for block in ready_blocks:
                    if self._should_release_block(block, current_time):
                        await self._broadcast_block(block, current_time)

        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.error(f"Dispatch blocks error: {exc}")

    async def _broadcast_block(self, block: CommentaryBlock, match_time: float) -> None:
        """Broadcast a flow block to the audio queue and WebSocket clients."""
        # Phase B: score PBP block for observability (never suppressed — silence is worse)
        if ENABLE_DIRECTOR_SELECTION_POLICY:
            recent = [u.text for u in list(self.state.agent_utterances)[-5:]]
            candidate = CommentaryCandidate(
                agent_kind="play_by_play",
                text=block.text,
                match_time=match_time,
                trigger_type="time_block",
                confidence=0.8,
                block_start=block.block_start,
                block_end=block.block_end,
            )
            decision = await self._coordinator.select(
                candidates=[candidate],
                recent_utterances=recent,
                match_time=match_time,
            )
            self._decision_log.append({
                "type": "coordinator_pbp",
                "trigger": "time_block",
                "match_time": match_time,
                "block_start": block.block_start,
                "selected": decision.selected_candidate_id is not None,
                "reason": decision.reason_codes,
                "latency_ms": decision.decision_latency_ms,
            })
            # PBP blocks are never suppressed in Phase B — log only

        utterance = AgentUtterance(
            agent_name=block.agent_name,
            text=block.text,
            match_time=match_time,
            event_type="",
        )
        self.state.add_utterance(utterance)

        await self.audio_queue.put_audio(
            agent_name=block.agent_name,
            match_time=match_time,
            audio_bytes=block.audio_bytes,
            text=block.text,
        )

        if self.broadcast_cb:
            await self._safe_broadcast({
                "type": "commentary",
                "agent": block.agent_name,
                "text": block.text,
                "has_audio": block.audio_bytes is not None,
                "match_time": match_time,
            })

        self._decision_log.append({
            "type": "pbp_block_dispatched",
            "trigger": "time_block",
            "match_time": match_time,
            "block_start": block.block_start,
            "text_len": len(block.text),
        })
        logger.info(f"[PBP BLOCK {block.block_start:.0f}s] dispatched at {match_time:.1f}s — {block.text!r}")

    # ------------------------------------------------------------------
    # Event dispatch (called by MatchSession for each arriving event)
    # ------------------------------------------------------------------

    async def dispatch_for_event(self, ev: MatchEvent) -> None:
        """
        No-op in time-block mode — commentary is time-triggered by _dispatch_blocks_loop.
        Kept for API compatibility with ws/handler.py.
        """
        pass

    # ------------------------------------------------------------------
    # Analyst scheduler loop
    # ------------------------------------------------------------------

    async def _analyst_scheduler_loop(self) -> None:
        next_analyst_gap = random.uniform(
            ANALYST_MIN_GAP_GAME_SEC, ANALYST_MAX_GAP_GAME_SEC
        )
        try:
            while not self._match_ended:
                await asyncio.sleep(1.0)

                if self.is_paused:
                    continue

                current_time = self.state.current_match_time

                if self._is_in_analyst_cooldown(current_time):
                    continue

                # Timer check
                time_since = current_time - self._last_analyst_game_time
                if time_since >= next_analyst_gap:
                    next_analyst_gap = random.uniform(
                        ANALYST_MIN_GAP_GAME_SEC, ANALYST_MAX_GAP_GAME_SEC
                    )
                    await self._fire_analyst("timer", "")

        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.error(f"Analyst scheduler error: {exc}")

    async def _fire_analyst(self, trigger_type: str, trigger_detail: str) -> None:
        """Generate and queue one analyst/context-window insight."""
        if self.is_paused or self._match_ended:
            return

        text, agent_kind = await self._resolve_analyst_candidate(trigger_type, trigger_detail)
        if not text:
            return

        self._analyst_context = text
        self._last_analyst_game_time = self.state.current_match_time
        await self._dispatch_analyst_line(text, agent_kind, trigger_type)

    async def _resolve_analyst_candidate(
        self, trigger_type: str, trigger_detail: str
    ) -> tuple[str, str]:
        """
        Decide which agent should speak for this trigger.

        Phase C (dead_ball / timer): runs Analyst + ContextWindowAgent in parallel;
        coordinator picks the better candidate.
        Phase B (all other triggers): runs Analyst alone; coordinator checks suppression.
        Returns (text, agent_kind) — ("", "") if suppressed or generation failed.
        """
        _parallel_triggers = ("dead_ball", "timer")

        if ENABLE_DIRECTOR_SELECTION_POLICY and trigger_type in _parallel_triggers:
            analyst_task = asyncio.get_event_loop().create_task(
                self._llm_analyst(trigger_type, trigger_detail)
            )
            context_task = asyncio.get_event_loop().create_task(
                self._llm_context_window(trigger_type)
            )
            results = await asyncio.gather(analyst_task, context_task, return_exceptions=True)

            analyst_text: str = results[0] if isinstance(results[0], str) else ""
            ctx_candidate: "CommentaryCandidate | None" = (
                results[1] if isinstance(results[1], CommentaryCandidate) else None
            )

            candidates = []
            if analyst_text:
                candidates.append(CommentaryCandidate(
                    agent_kind="analyst",
                    text=analyst_text,
                    match_time=self.state.current_match_time,
                    trigger_type=trigger_type,
                    confidence=0.65,
                ))
            if ctx_candidate:
                candidates.append(ctx_candidate)

            if not candidates:
                return "", ""

            recent = [u.text for u in list(self.state.agent_utterances)[-5:]]
            decision = await self._coordinator.select(
                candidates=candidates,
                recent_utterances=recent,
                match_time=self.state.current_match_time,
            )
            self._decision_log.append({
                "type": "coordinator_analyst_parallel",
                "trigger": trigger_type,
                "match_time": self.state.current_match_time,
                "n_candidates": len(candidates),
                "selected_kind": decision.selected_agent_kind,
                "selected": decision.selected_candidate_id is not None,
                "latency_ms": decision.decision_latency_ms,
            })
            if decision.selected_candidate_id is None:
                return "", ""
            return decision.final_text, decision.selected_agent_kind

        else:
            # Single-agent path (substitution, post_goal, half_time, etc.)
            text = await self._llm_analyst(trigger_type, trigger_detail)
            if not text:
                return "", ""

            if ENABLE_DIRECTOR_SELECTION_POLICY:
                recent = [u.text for u in list(self.state.agent_utterances)[-5:]]
                candidate = CommentaryCandidate(
                    agent_kind="analyst",
                    text=text,
                    match_time=self.state.current_match_time,
                    trigger_type=trigger_type,
                    confidence=0.9 if trigger_type in ("goal", "substitution", "half_time") else 0.65,
                )
                decision = await self._coordinator.select(
                    candidates=[candidate],
                    recent_utterances=recent,
                    match_time=self.state.current_match_time,
                )
                self._decision_log.append({
                    "type": "coordinator_analyst_single",
                    "trigger": trigger_type,
                    "match_time": self.state.current_match_time,
                    "selected": decision.selected_candidate_id is not None,
                    "reason": decision.reason_codes,
                    "latency_ms": decision.decision_latency_ms,
                })
                if decision.selected_candidate_id is None:
                    return "", ""

            return text, "analyst"

    async def _llm_analyst(self, trigger_type: str, trigger_detail: str) -> str:
        """Analyst LLM call — owns one semaphore slot."""
        async with self._sem:
            if self.is_paused or self._match_ended:
                return ""
            try:
                return await self._analyst.generate_insight(
                    state=self.state,
                    snapshot_text=self._analyst_ctx_snapshot,
                    trigger_type=trigger_type,
                    trigger_detail=trigger_detail,
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning(f"Analyst generation error: {exc}")
                return ""

    async def _llm_context_window(self, trigger_type: str) -> "CommentaryCandidate | None":
        """ContextWindowAgent LLM call — owns one semaphore slot (parallel to Analyst)."""
        async with self._sem:
            try:
                # Extract 5m and 15m context from the assembled analyst snapshot
                parts = self._analyst_ctx_snapshot.splitlines()
                context_5m = next(
                    (p for p in parts if "recent pattern" in p.lower() or "recent" in p.lower()), ""
                )
                context_15m = next(
                    (p for p in parts if "match picture" in p.lower() or "long" in p.lower()), ""
                )
                return await self._context_agent.generate_candidate(
                    match_time=self.state.current_match_time,
                    context_5m=context_5m,
                    context_15m=context_15m,
                    match_context=self._match_context,
                    state=self.state,
                    tone=self.personality,
                    trigger_type=trigger_type,
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning(f"ContextWindow generation error: {exc}")
                return None

    async def _dispatch_analyst_line(
        self, text: str, agent_kind: str, trigger_type: str
    ) -> None:
        """TTS synthesis + audio queue + WebSocket broadcast for any analyst-type line."""
        match_time = self.state.current_match_time

        audio_bytes = None
        if self._tts.available:
            try:
                audio_bytes = await self._tts.synthesize(text, agent_kind)
            except Exception:
                pass

        self.state.add_utterance(AgentUtterance(
            agent_name=agent_kind,
            text=text,
            match_time=match_time,
            event_type=trigger_type,
        ))
        await self.audio_queue.put_audio(
            agent_name=agent_kind,
            match_time=match_time,
            audio_bytes=audio_bytes,
            text=text,
        )
        if self.broadcast_cb:
            await self._safe_broadcast({
                "type": "commentary",
                "agent": agent_kind,
                "text": text,
                "has_audio": audio_bytes is not None,
                "match_time": match_time,
            })
        self._decision_log.append({
            "type": f"{agent_kind}_dispatched",
            "trigger": trigger_type,
            "match_time": match_time,
            "text_len": len(text),
        })
        logger.info(f"[{agent_kind.upper()}] ({trigger_type}) {text!r}")

    async def _schedule_post_goal_analyst(self, goal_game_time: float) -> None:
        """Wait for analyst cooldown to expire, then fire a post-goal insight."""
        # Poll until cooldown expires (or match ends / paused)
        while not self._match_ended:
            await asyncio.sleep(2.0)
            current = self.state.current_match_time
            if current >= goal_game_time + GOAL_ANALYST_COOLDOWN_SEC:
                if not self.is_paused:
                    score = self.state.score
                    detail = (
                        f"{score.get('home', 0)}-{score.get('away', 0)} "
                        f"({self.state.home_team} vs {self.state.away_team})"
                    )
                    await self._fire_analyst("post_goal", detail)
                return

    # ------------------------------------------------------------------
    # Match end
    # ------------------------------------------------------------------

    async def _handle_match_end(self, ev: MatchEvent) -> None:
        self._match_ended = True
        logger.info("Match ended — stopping director")
        # Fire a final analyst summary
        asyncio.get_event_loop().create_task(
            self._fire_analyst("half_time", "full time")
        )
        if self.broadcast_cb:
            await self._safe_broadcast({"type": "match_end", "match_time": ev.timestamp_sec})

    # ------------------------------------------------------------------
    # Personality
    # ------------------------------------------------------------------

    def set_personality(self, personality: str) -> None:
        self.personality = personality
        from commentator.agents.prompts import (
            build_flow_block_system, build_analyst_system,
            build_action_summary_system, build_context_window_system,
        )
        self._pbp.personality = personality
        self._pbp.update_system_prompt(build_flow_block_system(personality))
        self._analyst.update_system_prompt(build_analyst_system(personality))
        self._action_summary.personality = personality
        self._action_summary.update_system_prompt(build_action_summary_system(personality))
        self._context_agent.personality = personality
        self._context_agent.update_system_prompt(build_context_window_system(personality))
        logger.info(f"Personality set to: {personality}")

    # ------------------------------------------------------------------
    # Phase A policy helpers — named, testable, stub-ready for Phase B
    # ------------------------------------------------------------------

    def _classify_trigger(self, events: list[MatchEvent], match_time: float) -> str:
        """Return the highest-priority trigger type for a batch of events.
        Used for decision logging and Phase B candidate routing."""
        for ev in events:
            if ev.event_type == "Half End" and ev.details.get("period", 1) >= 2:
                return "match_end"
        for ev in events:
            if ev.event_type == "Half End" and ev.details.get("period", 1) == 1:
                return "half_time"
        for ev in events:
            if ev.event_type == "Shot" and ev.details.get("shot_outcome") == "Goal":
                return "goal"
        for ev in events:
            if ev.event_type == "Substitution":
                return "substitution"
        for ev in events:
            if any(p in ("attacking_move", "counter_attack") for p in ev.detected_patterns):
                return "dense_action"
        return "none"

    def _is_in_analyst_cooldown(self, match_time: float) -> bool:
        """True if analyst should not fire: first 5 min not elapsed, or inside goal cooldown."""
        if match_time < ANALYST_BLOCK_FIRST_SEC:
            return True
        if match_time < self._analyst_cooldown_until:
            return True
        return False

    def _should_suppress_commentary(self, text: str, recent_utterances: list[str]) -> bool:
        """Check for near-duplicate commentary against recent utterances.
        Phase A: logs potential duplicates but never suppresses (behaviour unchanged).
        Phase B: return True to suppress when overlap exceeds threshold."""
        if not text or not recent_utterances:
            return False
        text_tokens = set(text.lower().split())
        if not text_tokens:
            return False
        for recent in recent_utterances[-3:]:
            recent_tokens = set(recent.lower().split())
            overlap = len(text_tokens & recent_tokens) / len(text_tokens)
            if overlap > 0.7:
                logger.debug(
                    f"Near-duplicate commentary detected (overlap={overlap:.2f}): {text[:60]!r}"
                )
        return False  # Phase A: observe only, never suppress

    def _should_release_block(self, block: "CommentaryBlock", current_match_time: float) -> bool:
        """Gate for dispatching a ready block. Stub-ready for sealed-envelope (Phase B)."""
        if not block.text:
            return False
        # Sealed-envelope gate (Phase B: block.sealed + block.release_at will be checked here)
        if block.sealed and block.release_at is not None:
            return current_match_time >= block.release_at
        return True

    def _block_has_critical_event(self, events: list[MatchEvent]) -> bool:
        """True if the block contains a shot or red card — warrants ActionSummary generation."""
        return any(
            ev.event_type == "Shot" or (
                ev.event_type in ("Foul Committed", "Bad Behaviour")
                and ev.details.get("foul_card", ev.details.get("card", ""))
                in ("Red Card", "Second Yellow")
            )
            for ev in events
        )

    def _priority_for_trigger(self, trigger_type: str) -> int:
        """Integer priority for a trigger type (lower = higher priority).
        Used by Phase B coordinator selection policy."""
        return {
            "goal":         1,
            "match_end":    1,
            "half_time":    2,
            "substitution": 3,
            "dense_action": 4,
            "dead_ball":    5,
            "timer":        6,
            "none":         99,
        }.get(trigger_type, 99)

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    async def _safe_broadcast(self, payload: dict) -> None:
        if not self.broadcast_cb:
            return
        try:
            await self.broadcast_cb(payload)
        except Exception as exc:
            logger.debug(f"Broadcast error: {exc}")

    def _serialize_event(self, ev: MatchEvent) -> dict:
        return {
            "id": ev.id,
            "timestamp_sec": ev.timestamp_sec,
            "event_type": ev.event_type,
            "team": ev.team,
            "player": ev.player,
            "position": list(ev.position),
            "end_position": list(ev.end_position) if ev.end_position else None,
            "priority": ev.priority,
            "detected_patterns": ev.detected_patterns,
            "details": {
                k: v for k, v in ev.details.items()
                if k in (
                    "shot_outcome", "pass_outcome", "pass_recipient",
                    "foul_card", "card", "sub_replacement", "minute", "second",
                    "period", "cross", "goal_assist", "dribble_outcome",
                    "gk_type", "gk_outcome", "xg",
                )
            },
        }
