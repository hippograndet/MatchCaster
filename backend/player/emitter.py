# backend/player/emitter.py
# SSE endpoint: emits match events as they pass the current match clock time.

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import asdict
from typing import AsyncGenerator, Callable, Optional

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from sse_starlette.sse import EventSourceResponse

from config import EVENT_BUFFER_LOOKAHEAD_SEC, DEFAULT_SPEED_MULTIPLIER
from player.loader import MatchEvent, load_events, list_available_matches, compute_critical_timeline
from player.clock import MatchClock

logger = logging.getLogger("[EMITTER]")

router = APIRouter()

# Look-ahead window (game-seconds): if a critical event is within this window,
# trigger anticipation slow-down.
ANTICIPATION_WINDOW_SEC = 30.0

# Global registry: match_id → (clock, events, event_pointer)
_active_replays: dict[str, "ReplaySession"] = {}


class ReplaySession:
    """Holds state for one active match replay."""

    def __init__(self, match_id: str) -> None:
        self.match_id = match_id
        self.clock = MatchClock()
        self.events: list[MatchEvent] = load_events(match_id)
        self.critical_timeline: list[MatchEvent] = compute_critical_timeline(self.events)
        self._event_index: int = 0
        self._critical_index: int = 0        # pointer into critical_timeline for look-ahead
        self._subscribers: list[asyncio.Queue] = []
        self._look_ahead_cb: "Callable[[str, float], None] | None" = None
        self.clock.register_tick(self._on_tick)

    def register_look_ahead(self, cb: "Callable[[str, float], None]") -> None:
        """Register callback fired when a critical event is approaching.
        Signature: cb(event_type: str, game_seconds_until: float)
        """
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
            # Skip past critical events already passed
            while (
                self._critical_index < len(self.critical_timeline)
                and self.critical_timeline[self._critical_index].timestamp_sec <= match_time
            ):
                self._critical_index += 1
            # Check if the next critical event is within the anticipation window
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
        """Seek to target_time (game seconds). Clamps to [0, last event time]."""
        target_time = max(0.0, target_time)
        self.clock.reset(target_time)
        # Reposition event pointer to first event at or after target_time
        self._event_index = 0
        for i, ev in enumerate(self.events):
            if ev.timestamp_sec >= target_time:
                self._event_index = i
                break
        else:
            self._event_index = len(self.events)
        # Reposition critical look-ahead pointer
        self._critical_index = 0
        for i, ev in enumerate(self.critical_timeline):
            if ev.timestamp_sec > target_time:
                self._critical_index = i
                break
        else:
            self._critical_index = len(self.critical_timeline)


def _display_player(ev: MatchEvent) -> str:
    """Return a human-readable player identifier, falling back gracefully."""
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


def get_or_create_session(match_id: str) -> ReplaySession:
    if match_id not in _active_replays:
        session = ReplaySession(match_id)
        _active_replays[match_id] = session
    return _active_replays[match_id]


def get_session(match_id: str) -> ReplaySession | None:
    return _active_replays.get(match_id)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/api/matches")
async def list_matches():
    """Return list of available match IDs."""
    return list_available_matches()


@router.get("/api/events/stream")
async def stream_events(match_id: str, speed: float = DEFAULT_SPEED_MULTIPLIER):
    """
    SSE endpoint. Streams MatchEvents as JSON in real-time according to
    the match clock. The director subscribes to this internally; the
    frontend can also use it for lightweight event display.
    """
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
    """
    Control replay: action = 'start' | 'pause' | 'resume' | 'stop' | 'reset'
    """
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
