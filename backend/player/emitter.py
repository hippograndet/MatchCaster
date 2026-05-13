# backend/player/emitter.py
# SSE endpoint: emits match events as they pass the current match clock time.

from __future__ import annotations

import asyncio
import bisect
import json
import logging
from dataclasses import asdict
from typing import AsyncGenerator, Callable, Optional

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from sse_starlette.sse import EventSourceResponse

from config import (
    EVENT_BUFFER_LOOKAHEAD_SEC,
    DEFAULT_SPEED_MULTIPLIER,
    CRITICAL_ZONE_PRE_SEC,
    CRITICAL_ZONE_POST_SEC,
)
from player.loader import MatchEvent, load_events, list_available_matches, compute_critical_timeline
from player.clock import MatchClock, SpeedCurve

logger = logging.getLogger("[EMITTER]")

router = APIRouter()

# Look-ahead window (game-seconds): if a critical event is within this window,
# trigger anticipation callback.
ANTICIPATION_WINDOW_SEC = 30.0

# Global registry: match_id → ReplaySession
_active_replays: dict[str, "ReplaySession"] = {}


class ReplaySession:
    """Holds state for one active match replay."""

    def __init__(self, match_id: str) -> None:
        self.match_id = match_id
        self.clock = MatchClock()
        self.events: list[MatchEvent] = load_events(match_id)
        self.critical_timeline: list[MatchEvent] = compute_critical_timeline(self.events)

        # Pre-built timestamp arrays for O(log N) seek
        self._timestamps: list[float] = [e.timestamp_sec for e in self.events]
        self._critical_timestamps: list[float] = [e.timestamp_sec for e in self.critical_timeline]

        self._event_index: int = 0
        self._critical_index: int = 0
        self._subscribers: list[asyncio.Queue] = []
        self._look_ahead_cb: "Callable[[str, float], None] | None" = None

        # Wire SpeedCurve into the clock
        curve = SpeedCurve.build(
            self.critical_timeline,
            pre_sec=CRITICAL_ZONE_PRE_SEC,
            post_sec=CRITICAL_ZONE_POST_SEC,
        )
        self.clock.set_speed_curve(curve)

        self.clock.register_tick(self._on_tick)

    def register_look_ahead(self, cb: "Callable[[str, float], None]") -> None:
        self._look_ahead_cb = cb

    async def _on_tick(self, match_time: float) -> None:
        """Called every 50 ms. Emit all events whose timestamp ≤ match_time."""
        fired: list[MatchEvent] = []
        while (
            self._event_index < len(self.events)
            and self.events[self._event_index].timestamp_sec <= match_time
        ):
            fired.append(self.events[self._event_index])
            self._event_index += 1

        if fired:
            for ev in fired:
                payload = _event_to_dict(ev)
                for q in list(self._subscribers):
                    try:
                        q.put_nowait(payload)
                    except asyncio.QueueFull:
                        pass  # subscriber too slow; skip

        # Advance the critical look-ahead pointer and fire callback if needed
        if self._look_ahead_cb and self.clock.speed > 2.0:
            while (
                self._critical_index < len(self.critical_timeline)
                and self.critical_timeline[self._critical_index].timestamp_sec <= match_time
            ):
                self._critical_index += 1
            if self._critical_index < len(self.critical_timeline):
                next_critical = self.critical_timeline[self._critical_index]
                gap = next_critical.timestamp_sec - match_time
                if gap <= ANTICIPATION_WINDOW_SEC:
                    self._look_ahead_cb(next_critical.event_type, gap)

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=100)
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        if q in self._subscribers:
            self._subscribers.remove(q)

    def reset(self) -> None:
        self._event_index = 0
        self._critical_index = 0
        self.clock.reset(0.0)

    def seek(self, target_time: float) -> None:
        """
        Seek to target_time (game seconds).
        Uses binary search — O(log N) instead of O(N).
        Flushes all subscriber queues so no stale pre-seek events arrive downstream.
        """
        target_time = max(0.0, target_time)
        self.clock.reset(target_time)

        # Binary search: first event at or after target_time
        self._event_index = bisect.bisect_left(self._timestamps, target_time)

        # Binary search: first critical event strictly after target_time
        self._critical_index = bisect.bisect_right(self._critical_timestamps, target_time)

        # Flush all subscriber queues — prevent stale events arriving post-seek
        for q in self._subscribers:
            while not q.empty():
                try:
                    q.get_nowait()
                except asyncio.QueueEmpty:
                    break

    def close(self) -> None:
        """Stop clock and release all subscriber queues. Call before evicting from registry."""
        self.clock.stop()
        for q in self._subscribers:
            while not q.empty():
                try:
                    q.get_nowait()
                except asyncio.QueueEmpty:
                    break
        self._subscribers.clear()
        logger.info(f"ReplaySession closed: {self.match_id}")


def get_or_create_session(match_id: str) -> ReplaySession:
    if match_id not in _active_replays:
        session = ReplaySession(match_id)
        _active_replays[match_id] = session
    return _active_replays[match_id]


def get_session(match_id: str) -> ReplaySession | None:
    return _active_replays.get(match_id)


def remove_session(match_id: str) -> None:
    """Evict a session from the registry and release its resources."""
    session = _active_replays.pop(match_id, None)
    if session:
        session.close()
        logger.info(f"Session evicted from registry: {match_id}")


def _display_player(ev: MatchEvent) -> str:
    if ev.player:
        return ev.player
    if ev.event_type == "Starting XI":
        return ev.team
    return ev.team


def _event_to_dict(ev: MatchEvent) -> dict:
    return {
        "id": ev.id,
        "timestamp_sec": ev.timestamp_sec,
        "event_type": ev.event_type,
        "team": ev.team,
        "player": _display_player(ev),
        "position": list(ev.position),
        "end_position": list(ev.end_position) if ev.end_position else None,
        "details": ev.details,
        "priority": ev.priority,
        "detected_patterns": ev.detected_patterns,
        "is_home": ev.is_home,
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/api/matches")
async def list_matches():
    return list_available_matches()


@router.get("/api/events/stream")
async def stream_events(match_id: str, speed: float = DEFAULT_SPEED_MULTIPLIER):
    session = get_or_create_session(match_id)
    session.clock.set_speed(speed)
    if not session.clock.is_running:
        session.clock.start()

    q = session.subscribe()

    async def event_generator() -> AsyncGenerator[dict, None]:
        try:
            while True:
                try:
                    payload = await asyncio.wait_for(q.get(), timeout=30.0)
                    yield {"data": json.dumps(payload), "event": "match_event"}
                except asyncio.TimeoutError:
                    yield {"data": json.dumps({"type": "heartbeat"}), "event": "heartbeat"}
        except asyncio.CancelledError:
            pass
        finally:
            session.unsubscribe(q)

    return EventSourceResponse(event_generator())


@router.post("/api/replay/control")
async def control_replay(match_id: str, action: str, speed: float | None = None):
    session = get_or_create_session(match_id)
    if action == "start":
        if speed is not None:
            session.clock.set_speed(speed)
        if not session.clock.is_running:
            session.clock.start()
    elif action == "pause":
        session.clock.pause()
    elif action == "resume":
        session.clock.resume()
    elif action == "stop":
        session.clock.stop()
    elif action == "reset":
        session.clock.stop()
        session.reset()
    elif action == "set_speed" and speed is not None:
        session.clock.set_speed(speed)

    return {
        "match_id": match_id,
        "action": action,
        "match_time": session.clock.get_time(),
        "speed": session.clock.speed,
        "running": session.clock.is_running,
    }
