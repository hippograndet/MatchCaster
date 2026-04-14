# backend/director/router.py
from __future__ import annotations

import asyncio
import logging
import random
import time
from typing import Optional, Callable, Awaitable

from config import (
    MAX_CONCURRENT_AGENT_CALLS,
    MIN_GAP_GAME_SEC,
    DEAD_AIR_GAME_SEC,
    ROUTINE_SKIP_RATE,
    DEFAULT_SPEED_MULTIPLIER,
    DEV_MODE,
)
from debug.trace import PipelineTrace
from analyser.classifier import (
    SequenceDetector,
    classify_and_tag,
    CRITICAL,
    NOTABLE,
    ROUTINE,
)
from analyser.state import SharedMatchState, AgentUtterance
from player.loader import MatchEvent
from commentator.agents.play_by_play import PlayByPlayAgent
from commentator.agents.tactical import TacticalAgent
from commentator.agents.stats import StatsAgent
from commentator.tts.engine import get_tts_engine
from commentator.queue import AudioQueue

logger = logging.getLogger("[DIRECTOR]")

BroadcastCallback = Callable[[dict], Awaitable[None]]
SpeedCallback = Callable[[float], None]   # called with new speed multiplier


class Director:
    def __init__(
        self,
        state: SharedMatchState,
        audio_queue: AudioQueue,
        broadcast_cb: Optional[BroadcastCallback] = None,
        speed_cb: Optional[SpeedCallback] = None,
    ) -> None:
        self.state = state
        self.audio_queue = audio_queue
        self.broadcast_cb = broadcast_cb
        self.speed_cb = speed_cb          # lets director adjust replay speed

        self._pbp = PlayByPlayAgent()
        self._tactical = TacticalAgent()
        self._stats = StatsAgent()
        self._tts = get_tts_engine()
        self._seq_detector = SequenceDetector()

        self._active_task: Optional[asyncio.Task] = None
        self._active_task_priority: int = 999
        self._sem = asyncio.Semaphore(MAX_CONCURRENT_AGENT_CALLS)

        self._last_utterance_wall_time: float = 0.0
        self._dead_air_task: Optional[asyncio.Task] = None
        self._dead_air_generating: bool = False   # BUG FIX: guard concurrent dead-air calls

        # Pause state — BUG FIX: stop commentary when clock paused
        self.is_paused: bool = False

        # Dynamic speed
        self._base_speed: float = DEFAULT_SPEED_MULTIPLIER
        self._speed_override_until: float = 0.0   # wall-clock time when override expires

        # Match end
        self._match_ended: bool = False
        self.personality: str = "neutral"   # neutral | enthusiastic | home_bias | away_bias | analytical

        # PBP dominance: track last game-time when tactical/stats spoke
        self._last_secondary_game_min: float = -999.0   # game minutes

        # Speed-aware commentary tracking (game-seconds based)
        self._last_utterance_game_time: float = -999.0  # game time of last utterance

        # Context injected by MatchSession
        self._analysis_context: str = ""
        self._match_context: str = ""       # static: competition, venue, weather

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        self._dead_air_task = asyncio.get_event_loop().create_task(self._dead_air_loop())
        logger.info("Director started")

    def stop(self) -> None:
        if self._dead_air_task:
            self._dead_air_task.cancel()
        if self._active_task and not self._active_task.done():
            self._active_task.cancel()

    def set_paused(self, paused: bool) -> None:
        """BUG FIX: pause/resume commentary generation."""
        self.is_paused = paused
        if paused and self._active_task and not self._active_task.done():
            self._active_task.cancel()
        logger.info(f"Director {'paused' if paused else 'resumed'}")

    def set_base_speed(self, speed: float) -> None:
        self._base_speed = speed

    def set_match_context(self, context: str) -> None:
        """Set static match context (competition, venue, weather) prepended to every prompt."""
        self._match_context = context

    def set_analysis_snapshot(self, snapshot) -> None:
        """Called by MatchSession each tick with the latest analysis data."""
        parts = []
        if self._match_context:
            parts.append(self._match_context)
        if snapshot.short_term_text:
            parts.append(snapshot.short_term_text)
        if snapshot.long_term_text:
            parts.append(snapshot.long_term_text)
        self._analysis_context = "\n".join(parts)

    async def process_events(self, events: list[MatchEvent], match_time: float) -> None:
        if not events or self.is_paused or self._match_ended:
            return

        # Classify + detect sequences
        for ev in events:
            classify_and_tag(ev)
            patterns = self._seq_detector.add(ev)
            ev.detected_patterns = list(set(ev.detected_patterns + patterns))

        # Check for match end (Half End period 2 or 4)
        for ev in events:
            if ev.event_type == "Half End" and ev.details.get("period", 1) >= 2:
                await self._handle_match_end(ev)
                return

        # Update state — BUG FIX: use event's own timestamp, not clock time
        self.state.update(events, match_time)

        # Broadcast raw events
        if self.broadcast_cb:
            for ev in events:
                await self._safe_broadcast({
                    "type": "event",
                    "data": self._serialize_event(ev),
                    "state": self.state.to_dict(),
                })

        # Dynamic speed: slow down during intense sequences
        has_dense = any(
            p in ("attacking_move", "counter_attack")
            for ev in events
            for p in ev.detected_patterns
        )
        if has_dense and self.speed_cb:
            self._trigger_slow_motion()

        # Route to agents
        critical_events = [e for e in events if e.priority == CRITICAL]
        notable_events  = [e for e in events if e.priority == NOTABLE]
        routine_events  = [e for e in events if e.priority == ROUTINE]

        # BUG FIX: use event's timestamp_sec for commentary time stamp
        event_time = events[0].timestamp_sec if events else match_time

        # Detect goal — trigger slow-motion commentary window
        is_goal = any(
            ev.event_type == "Shot" and ev.details.get("shot_outcome") == "Goal"
            for ev in events
        )
        if is_goal and self.speed_cb:
            self._trigger_goal_slowdown()

        # Speed tiers — adapt verbosity to playback speed
        speed = self._base_speed
        high_speed = speed >= 8.0
        med_speed  = speed >= 4.0
        # Routine skip rate adapts: at speed 1, skip 50%; at speed 8, skip 98%
        routine_skip = min(0.98, 0.5 + (speed - 1.0) * 0.07)

        if critical_events:
            await self._cancel_active_if_lower(priority=1)
            await self._spawn_generation(
                agent=self._pbp,
                events=critical_events,
                priority=1,
                agent_name="play_by_play",
                match_time=critical_events[0].timestamp_sec,
                follow_up_agent=self._stats if not high_speed and random.random() < 0.6 else None,
                follow_up_delay=2.0,
            )
        elif notable_events and not high_speed:
            if self._can_speak(match_time):
                await self._spawn_generation(
                    agent=self._pbp,
                    events=notable_events,
                    priority=2,
                    agent_name="play_by_play",
                    match_time=notable_events[0].timestamp_sec,
                )
        elif routine_events and not high_speed and not med_speed:
            if self._can_speak(match_time) and random.random() > routine_skip:
                await self._spawn_generation(
                    agent=self._pbp,
                    events=routine_events[-1:],
                    priority=3,
                    agent_name="play_by_play",
                    match_time=routine_events[-1].timestamp_sec,
                )

    # ------------------------------------------------------------------
    # Generation helpers
    # ------------------------------------------------------------------

    async def _spawn_generation(self, agent, events, priority, agent_name,
                                 match_time, follow_up_agent=None, follow_up_delay=0.0):
        task = asyncio.get_event_loop().create_task(
            self._generate_and_queue(agent, events, priority, agent_name,
                                     match_time, follow_up_agent, follow_up_delay)
        )
        self._active_task = task
        self._active_task_priority = priority

    async def _generate_and_queue(self, agent, events, priority, agent_name,
                                   match_time, follow_up_agent=None, follow_up_delay=0.0,
                                   classification_hint: str = ""):
        try:
            async with self._sem:
                if self.is_paused:
                    return

                # --- Dev trace setup ---
                trace = None
                _pipeline_start = time.monotonic()
                if DEV_MODE:
                    classification = classification_hint or {1: "CRITICAL", 2: "NOTABLE", 3: "ROUTINE"}.get(priority, "ROUTINE")
                    trace = PipelineTrace(
                        trigger_events=[
                            {"type": e.event_type, "player": e.player, "team": e.team}
                            for e in events
                        ],
                        classification=classification,
                        agent_selected=agent_name,
                        selection_reason=f"priority={priority} → {agent_name}",
                    )

                text = await agent.generate(events, self.state, self._analysis_context, trace=trace)
                if not text or self.is_paused:
                    return

                utterance = AgentUtterance(
                    agent_name=agent_name,
                    text=text,
                    match_time=match_time,
                    event_type=events[0].event_type if events else "",
                )
                self.state.add_utterance(utterance)
                self._last_utterance_wall_time = time.monotonic()
                self._last_utterance_game_time = match_time

                audio_bytes = None
                if self._tts.available:
                    try:
                        audio_bytes = await self._tts.synthesize(text, agent_name, trace=trace)
                    except Exception as exc:
                        logger.warning(f"TTS failed for {agent_name}: {exc}")

                await self.audio_queue.put_audio(
                    agent_name=agent_name,
                    match_time=match_time,
                    audio_bytes=audio_bytes,
                    text=text,
                )

                # Emit dev debug trace before the commentary broadcast
                if DEV_MODE and trace and self.broadcast_cb:
                    trace.end_to_end_ms = (time.monotonic() - _pipeline_start) * 1000
                    await self._safe_broadcast({"type": "debug", "trace": trace.to_dict()})

                if self.broadcast_cb:
                    await self._safe_broadcast({
                        "type": "commentary",
                        "agent": agent_name,
                        "text": text,
                        "has_audio": audio_bytes is not None,
                        "match_time": match_time,
                    })

                logger.info(f"[{agent_name.upper()}] {text!r}")

                # Follow-up (e.g. stats after goal)
                if follow_up_agent and follow_up_delay > 0:
                    await asyncio.sleep(follow_up_delay)
                    if self.is_paused:
                        return
                    try:
                        follow_trace = None
                        _follow_start = time.monotonic()
                        if DEV_MODE:
                            follow_trace = PipelineTrace(
                                trigger_events=[
                                    {"type": e.event_type, "player": e.player, "team": e.team}
                                    for e in events
                                ],
                                classification="follow_up",
                                agent_selected=follow_up_agent.name,
                                selection_reason="follow_up after primary",
                            )

                        follow_text = await follow_up_agent.generate(
                            events, self.state, self._analysis_context, trace=follow_trace
                        )
                        if follow_text and not self.is_paused:
                            follow_utt = AgentUtterance(
                                agent_name=follow_up_agent.name,
                                text=follow_text,
                                match_time=match_time + follow_up_delay,
                            )
                            self.state.add_utterance(follow_utt)
                            follow_audio = None
                            if self._tts.available:
                                try:
                                    follow_audio = await self._tts.synthesize(
                                        follow_text, follow_up_agent.name, trace=follow_trace
                                    )
                                except Exception:
                                    pass
                            await self.audio_queue.put_audio(
                                agent_name=follow_up_agent.name,
                                match_time=match_time + follow_up_delay,
                                audio_bytes=follow_audio,
                                text=follow_text,
                            )

                            if DEV_MODE and follow_trace and self.broadcast_cb:
                                follow_trace.end_to_end_ms = (time.monotonic() - _follow_start) * 1000
                                await self._safe_broadcast({"type": "debug", "trace": follow_trace.to_dict()})

                            if self.broadcast_cb:
                                await self._safe_broadcast({
                                    "type": "commentary",
                                    "agent": follow_up_agent.name,
                                    "text": follow_text,
                                    "has_audio": follow_audio is not None,
                                    "match_time": match_time + follow_up_delay,
                                })
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:
                        logger.warning(f"Follow-up error: {exc}")

        except asyncio.CancelledError:
            logger.debug(f"Generation cancelled for {agent_name}")
        except Exception as exc:
            logger.error(f"Generation error [{agent_name}]: {exc}")

    async def _cancel_active_if_lower(self, priority: int) -> None:
        if (self._active_task and not self._active_task.done()
                and self._active_task_priority > priority):
            self._active_task.cancel()
            try:
                await asyncio.shield(asyncio.sleep(0.01))
            except asyncio.CancelledError:
                pass

    def _can_speak(self, current_game_time: float = 0.0) -> bool:
        """
        Speed-aware gap enforcement.
        The minimum silence is MIN_GAP_GAME_SEC of *game time*, which translates
        to MIN_GAP_GAME_SEC / speed real seconds — shorter gaps at higher speed.
        """
        game_elapsed = current_game_time - self._last_utterance_game_time
        return game_elapsed >= MIN_GAP_GAME_SEC

    # ------------------------------------------------------------------
    # Dead-air filler — BUG FIX: guard with _dead_air_generating
    # ------------------------------------------------------------------

    async def _dead_air_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(1.0)
                if self.is_paused or self._match_ended:
                    continue
                if self._dead_air_generating:
                    continue
                # Skip filler at high speed — PBP only reacts to events
                if self._base_speed >= 4.0:
                    continue

                match_time = self.state.current_match_time
                game_elapsed = match_time - self._last_utterance_game_time
                if game_elapsed < DEAD_AIR_GAME_SEC:
                    continue

                recent = list(self.state.recent_events)
                if not recent:
                    continue

                current_game_min = match_time / 60.0

                # PBP dominance: tactical/stats only every 5-10 game minutes
                min_gap = random.uniform(5.0, 10.0)
                if current_game_min - self._last_secondary_game_min < min_gap:
                    # Not time for tactical/stats — fill with a PBP observation
                    self._dead_air_generating = True
                    try:
                        await self._generate_and_queue(
                            agent=self._pbp,
                            events=recent[-3:],
                            priority=3,
                            agent_name="play_by_play",
                            match_time=match_time,
                            classification_hint="dead-air",
                        )
                    finally:
                        self._dead_air_generating = False
                    continue

                # Alternate between tactical and stats
                agent, agent_name = (
                    (self._tactical, "tactical")
                    if random.random() < 0.6
                    else (self._stats, "stats")
                )

                self._last_secondary_game_min = current_game_min
                self._dead_air_generating = True
                try:
                    await self._generate_and_queue(
                        agent=agent,
                        events=recent[-5:],
                        priority=3,
                        agent_name=agent_name,
                        match_time=match_time,
                        classification_hint="dead-air",
                    )
                finally:
                    self._dead_air_generating = False

        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.error(f"Dead-air loop error: {exc}")

    # ------------------------------------------------------------------
    # Dynamic speed
    # ------------------------------------------------------------------

    def _trigger_goal_slowdown(self) -> None:
        """Slow to 0.5× for 20 real seconds after a goal — lets PBP commentate fully."""
        if self.speed_cb:
            self.speed_cb(0.5)
            logger.info("Goal! Slowing to 0.5× for commentary window")
        self._speed_override_until = time.monotonic() + 20.0
        asyncio.get_event_loop().create_task(self._restore_speed_after(20.0))

    def _trigger_slow_motion(self) -> None:
        """Halve the replay speed for 8 real seconds during intense action."""
        now = time.monotonic()
        if now < self._speed_override_until:
            return   # already in slow-motion or goal window
        self._speed_override_until = now + 8.0
        if self.speed_cb:
            slow = max(0.5, self._base_speed / 2.0)
            self.speed_cb(slow)
            logger.info(f"Dynamic speed: slowing to {slow}× for intense action")
        asyncio.get_event_loop().create_task(self._restore_speed_after(8.0))

    async def _restore_speed_after(self, delay: float) -> None:
        await asyncio.sleep(delay)
        if self.speed_cb and not self.is_paused:
            self.speed_cb(self._base_speed)
            logger.info(f"Dynamic speed: restored to {self._base_speed}×")

    # ------------------------------------------------------------------
    # Match end
    # ------------------------------------------------------------------

    async def _handle_match_end(self, ev: MatchEvent) -> None:
        self._match_ended = True
        logger.info("Match ended — stopping director")
        if self.broadcast_cb:
            await self._safe_broadcast({"type": "match_end", "match_time": ev.timestamp_sec})

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