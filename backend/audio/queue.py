# backend/audio/queue.py
# Priority audio queue: buffers (priority, match_time, agent, audio, text) tuples.

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Optional

from config import MAX_AUDIO_QUEUE_SIZE, PBP_PRIORITY, TACTICAL_PRIORITY, STATS_PRIORITY

logger = logging.getLogger("[AUDIO_QUEUE]")

AGENT_PRIORITY_MAP: dict[str, int] = {
    "play_by_play": PBP_PRIORITY,
    "tactical": TACTICAL_PRIORITY,
    "stats": STATS_PRIORITY,
}


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
    - Higher-priority items (lower number) are served first.
    - If queue exceeds MAX_AUDIO_QUEUE_SIZE, lowest-priority (stale) items are dropped.
    """

    def __init__(self) -> None:
        self._queue: asyncio.PriorityQueue[AudioItem] = asyncio.PriorityQueue()
        self._size: int = 0
        self._items: list[AudioItem] = []  # shadow list for inspection/pruning
        self._lock = asyncio.Lock()
        self._has_items = asyncio.Event()

    async def put(self, item: AudioItem) -> None:
        async with self._lock:
            if self._size >= MAX_AUDIO_QUEUE_SIZE:
                # Drop the lowest-priority (highest number) item
                self._drop_lowest_priority()

            await self._queue.put(item)
            self._items.append(item)
            self._size += 1
            self._has_items.set()
            logger.debug(f"Queued [{item.agent_name}] priority={item.priority} text={item.text[:30]!r}")

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
        """Block until an item is available and return it."""
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
        """Non-blocking get. Returns None if queue is empty."""
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
        """Remove the item with highest priority number (least important)."""
        if not self._items:
            return
        worst = max(self._items, key=lambda i: (i.priority, -i.match_time))
        self._items.remove(worst)
        # Rebuild the priority queue without the dropped item
        remaining = list(self._items)
        self._queue = asyncio.PriorityQueue()
        for item in remaining:
            self._queue.put_nowait(item)
        self._size = len(remaining)
        logger.warning(f"Queue full — dropped stale [{worst.agent_name}] item: {worst.text[:40]!r}")

    @property
    def size(self) -> int:
        return self._size

    def clear(self) -> None:
        """Empty the queue (e.g., on match reset)."""
        self._queue = asyncio.PriorityQueue()
        self._items.clear()
        self._size = 0
        self._has_items.clear()
