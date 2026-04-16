# backend/player/clock.py
# MatchClock: async accelerated match time with pause/resume/speed control.

from __future__ import annotations

import asyncio
import logging
import time
from typing import Callable, Awaitable

from config import DEFAULT_SPEED_MULTIPLIER

logger = logging.getLogger("[CLOCK]")

TickCallback = Callable[[float], Awaitable[None]]


class MatchClock:
    """
    Maintains match_elapsed_seconds advancing at speed_multiplier × real time.
    Ticks every 50 ms (real), advancing match time by 50ms × multiplier.
    Registered tick callbacks are awaited on every tick.
    """

    TICK_INTERVAL_REAL: float = 0.05  # 50 ms real time

    def __init__(self, speed: float = DEFAULT_SPEED_MULTIPLIER) -> None:
        self._speed: float = speed
        self._match_time: float = 0.0
        self._running: bool = False
        self._paused: bool = True   # hasn't started yet — logically paused
        self._task: asyncio.Task | None = None
        self._tick_callbacks: list[TickCallback] = []
        self._last_real_time: float = 0.0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def register_tick(self, callback: TickCallback) -> None:
        """Register an async callback called on every clock tick."""
        self._tick_callbacks.append(callback)

    def start(self) -> None:
        """Start the clock loop (creates background asyncio task)."""
        if self._running:
            return
        self._running = True
        self._paused = False
        self._last_real_time = time.monotonic()
        self._task = asyncio.get_event_loop().create_task(self._loop())
        logger.info(f"Clock started at {self._speed}× speed")

    def pause(self) -> None:
        """Pause the clock (match time stops advancing)."""
        self._paused = True
        logger.info("Clock paused")

    def resume(self) -> None:
        """Resume the clock after a pause."""
        self._paused = False
        self._last_real_time = time.monotonic()
        logger.info("Clock resumed")

    def stop(self) -> None:
        """Stop the clock and cancel its background task."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
        logger.info("Clock stopped")

    def reset(self, match_time: float = 0.0) -> None:
        """Reset match time to the given value."""
        self._match_time = match_time
        self._last_real_time = time.monotonic()

    def set_speed(self, multiplier: float) -> None:
        """Change the speed multiplier on the fly."""
        multiplier = max(0.1, min(multiplier, 50.0))
        self._speed = multiplier
        logger.info(f"Clock speed changed to {multiplier}×")

    def get_time(self) -> float:
        """Return current match elapsed seconds."""
        return self._match_time

    @property
    def speed(self) -> float:
        return self._speed

    @property
    def is_running(self) -> bool:
        return self._running and not self._paused

    # ------------------------------------------------------------------
    # Internal loop
    # ------------------------------------------------------------------

    async def _loop(self) -> None:
        try:
            while self._running:
                await asyncio.sleep(self.TICK_INTERVAL_REAL)

                if self._paused:
                    self._last_real_time = time.monotonic()
                    continue

                now = time.monotonic()
                real_delta = now - self._last_real_time
                self._last_real_time = now

                # Advance match time
                self._match_time += real_delta * self._speed

                # Fire tick callbacks
                current = self._match_time
                for cb in self._tick_callbacks:
                    try:
                        await cb(current)
                    except Exception as exc:
                        logger.error(f"Tick callback error: {exc}")
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.error(f"Clock loop crashed: {exc}")
            self._running = False
