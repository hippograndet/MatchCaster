# backend/commentator/queue.py
# Audio queue + event-tagged commentary queue.

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Optional

from config import MAX_AUDIO_QUEUE_SIZE, PBP_PRIORITY, ANALYST_PRIORITY

logger = logging.getLogger("[AUDIO_QUEUE]")

AGENT_PRIORITY_MAP: dict[str, int] = {
    "play_by_play": PBP_PRIORITY,
    "analyst": ANALYST_PRIORITY,
    # Legacy names kept for safety
    "tactical": ANALYST_PRIORITY,
    "stats": ANALYST_PRIORITY,
}


# ---------------------------------------------------------------------------
# CommentaryLine — one pre-generated line tied to an event ID
# ---------------------------------------------------------------------------

@dataclass
class CommentaryLine:
    event_id: str                          # matches MatchEvent.id, or "opening"
    text: str
    agent_name: str
    audio_bytes: Optional[bytes] = None
    ready: bool = False                    # True once TTS has been synthesized


# ---------------------------------------------------------------------------
# EventTaggedQueue — holds pre-generated lines keyed by event_id
# ---------------------------------------------------------------------------

class EventTaggedQueue:
    """
    Stores pre-generated commentary lines indexed by event_id.
    When an event fires on the pitch, pop_for_event() retrieves its line.
    """

    def __init__(self) -> None:
        self._pending: dict[str, CommentaryLine] = {}
        # "opening" line is special — fires once at match start
        self._opening_line: Optional[CommentaryLine] = None
        self._opening_fired: bool = False

    def store(self, lines: list[CommentaryLine]) -> None:
        for line in lines:
            if line.event_id == "opening":
                if not self._opening_fired:
                    self._opening_line = line
            else:
                self._pending[line.event_id] = line

    def pop_for_event(self, event_id: str) -> Optional[CommentaryLine]:
        return self._pending.pop(event_id, None)

    def pop_opening(self) -> Optional[CommentaryLine]:
        """Return and consume the opening scene-setter line, if available."""
        if self._opening_line and not self._opening_fired:
            line = self._opening_line
            self._opening_fired = True
            self._opening_line = None
            return line
        return None

    def clear(self) -> None:
        """Purge all pending lines (called on seek)."""
        self._pending.clear()
        self._opening_line = None
        # Do NOT reset _opening_fired — a seek after the opening shouldn't re-fire it

    def has_pending(self) -> bool:
        return bool(self._pending) or (self._opening_line is not None and not self._opening_fired)

    @property
    def pending_count(self) -> int:
        return len(self._pending)


# ---------------------------------------------------------------------------
# AudioItem / AudioQueue — unchanged, used for playback sequencing
# ---------------------------------------------------------------------------

@dataclass(order=True)
class AudioItem:
    priority: int
    match_time: float
    agent_name: str = field(compare=False)
    audio_bytes: Optional[bytes] = field(compare=False, default=None)
    text: str = field(compare=False, default="")

    @classmethod
    def from_agent(
        cls,
        agent_name: str,
        match_time: float,
        audio_bytes: Optional[bytes],
        text: str,
    ) -> "AudioItem":
        priority = AGENT_PRIORITY_MAP.get(agent_name, 99)
        return cls(
            priority=priority,
            match_time=match_time,
            agent_name=agent_name,
            audio_bytes=audio_bytes,
            text=text,
        )


class AudioQueue:
    """
    Async priority queue for audio items.
    Higher-priority items (lower number) are served first.
    If queue exceeds MAX_AUDIO_QUEUE_SIZE, lowest-priority items are dropped.
    """

    def __init__(self) -> None:
        self._queue: asyncio.PriorityQueue[AudioItem] = asyncio.PriorityQueue()
        self._size: int = 0
        self._items: list[AudioItem] = []
        self._lock = asyncio.Lock()
        self._has_items = asyncio.Event()

    async def put(self, item: AudioItem) -> None:
        async with self._lock:
            if self._size >= MAX_AUDIO_QUEUE_SIZE:
                self._drop_lowest_priority()
            await self._queue.put(item)
            self._items.append(item)
            self._size += 1
            self._has_items.set()

    async def put_audio(
        self,
        agent_name: str,
        match_time: float,
        audio_bytes: Optional[bytes],
        text: str,
    ) -> None:
        item = AudioItem.from_agent(agent_name, match_time, audio_bytes, text)
        await self.put(item)

    async def get(self) -> AudioItem:
        while True:
            try:
                item = self._queue.get_nowait()
                async with self._lock:
                    self._size = max(0, self._size - 1)
                    if item in self._items:
                        self._items.remove(item)
                    if self._size == 0:
                        self._has_items.clear()
                return item
            except asyncio.QueueEmpty:
                self._has_items.clear()
                await self._has_items.wait()

    async def get_nowait(self) -> Optional[AudioItem]:
        try:
            item = self._queue.get_nowait()
            async with self._lock:
                self._size = max(0, self._size - 1)
                if item in self._items:
                    self._items.remove(item)
                if self._size == 0:
                    self._has_items.clear()
            return item
        except asyncio.QueueEmpty:
            return None

    def _drop_lowest_priority(self) -> None:
        if not self._items:
            return
        worst = max(self._items, key=lambda i: (i.priority, -i.match_time))
        self._items.remove(worst)
        remaining = list(self._items)
        self._queue = asyncio.PriorityQueue()
        for item in remaining:
            self._queue.put_nowait(item)
        self._size = len(remaining)
        logger.warning(f"Queue full — dropped stale [{worst.agent_name}]: {worst.text[:40]!r}")

    @property
    def size(self) -> int:
        return self._size

    def clear(self) -> None:
        self._queue = asyncio.PriorityQueue()
        self._items.clear()
        self._size = 0
        self._has_items.clear()
