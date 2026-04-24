# backend/player/clock.py
# MatchClock: async accelerated match time with pause/resume/speed control.
# SpeedCurve: pre-built critical-zone enforcement — hard-cuts to 1x near shots/goals/cards.

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Callable, Awaitable

from config import DEFAULT_SPEED_MULTIPLIER, CRITICAL_ZONE_PRE_SEC, CRITICAL_ZONE_POST_SEC

logger = logging.getLogger("[CLOCK]")

TickCallback = Callable[[float], Awaitable[None]]


# ---------------------------------------------------------------------------
# SpeedCurve
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CriticalZone:
    start: float   # game-seconds (inclusive)
    end: float     # game-seconds (inclusive)


class SpeedCurve:
    """
    Evaluates the effective speed multiplier at any match time.
    Outside critical zones: returns base_speed (user-set).
    Inside a critical zone: returns 1.0 (hard cut, no ramping).
    """

    def __init__(self, zones: list[CriticalZone], base_speed: float = DEFAULT_SPEED_MULTIPLIER) -> None:
        self._zones = zones
        self._base_speed: float = max(0.1, min(base_speed, 50.0))

    @classmethod
    def build(
        cls,
        critical_events: list,
        pre_sec: float = CRITICAL_ZONE_PRE_SEC,
        post_sec: float = CRITICAL_ZONE_POST_SEC,
        base_speed: float = DEFAULT_SPEED_MULTIPLIER,
    ) -> "SpeedCurve":
        """Build a SpeedCurve from a list of MatchEvent objects."""
        zones = [
            CriticalZone(
                start=ev.timestamp_sec - pre_sec,
                end=ev.timestamp_sec + post_sec,
            )
            for ev in critical_events
        ]
        return cls(zones, base_speed)

    def set_base_speed(self, speed: float) -> None:
        self._base_speed = max(0.1, min(speed, 50.0))

    @property
    def base_speed(self) -> float:
        return self._base_speed

    def evaluate(self, match_time: float) -> float:
        """Return the effective speed at match_time."""
        for zone in self._zones:
            if zone.start <= match_time <= zone.end:
                return 1.0
        return self._base_speed

    def in_critical_zone(self, match_time: float) -> bool:
        return any(z.start <= match_time <= z.end for z in self._zones)


# ---------------------------------------------------------------------------
# MatchClock
# ---------------------------------------------------------------------------

class MatchClock:
    """
    Maintains match_elapsed_seconds advancing at effective_speed × real time.
    Ticks every 50 ms (real), advancing match time by 50ms × effective_speed.

    Speed ownership:
    - set_speed() updates base_speed on the attached SpeedCurve (or internal fallback).
    - effective_speed is evaluated each tick from the SpeedCurve.
    - Critical zones in the SpeedCurve hard-cut effective_speed to 1.0 regardless of base_speed.
    """

    TICK_INTERVAL_REAL: float = 0.05  # 50 ms real time

    def __init__(self, speed: float = DEFAULT_SPEED_MULTIPLIER) -> None:
        self._base_speed: float = speed
        self._effective_speed: float = speed
        self._speed_curve: SpeedCurve | None = None
        self._match_time: float = 0.0
        self._running: bool = False
        self._paused: bool = True
        self._task: asyncio.Task | None = None
        self._tick_callbacks: list[TickCallback] = []
        self._last_real_time: float = 0.0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_speed_curve(self, curve: SpeedCurve) -> None:
        """Attach a SpeedCurve. From this point on, effective_speed is curve-evaluated."""
        self._speed_curve = curve
        self._speed_curve.set_base_speed(self._base_speed)
        logger.info(f"SpeedCurve attached ({len(curve._zones)} critical zones)")

    def register_tick(self, callback: TickCallback) -> None:
        self._tick_callbacks.append(callback)

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._paused = False
        self._last_real_time = time.monotonic()
        self._task = asyncio.get_event_loop().create_task(self._loop())
        logger.info(f"Clock started at {self._base_speed}× base speed")

    def pause(self) -> None:
        self._paused = True
        logger.info(f"Clock paused at {self._match_time:.1f}s")

    def resume(self) -> None:
        self._paused = False
        self._last_real_time = time.monotonic()
        logger.info(f"Clock resumed at {self._match_time:.1f}s")

    def stop(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
        logger.info("Clock stopped")

    def reset(self, match_time: float = 0.0) -> None:
        self._match_time = match_time
        self._last_real_time = time.monotonic()

    def set_speed(self, multiplier: float) -> None:
        """Set base speed. SpeedCurve (if attached) enforces zone overrides on top of this."""
        multiplier = max(0.1, min(multiplier, 50.0))
        if self._speed_curve is not None:
            if multiplier == self._speed_curve.base_speed:
                return
            self._speed_curve.set_base_speed(multiplier)
        else:
            if multiplier == self._base_speed:
                return
            self._base_speed = multiplier
        logger.info(f"Base speed set to {multiplier}×")

    def get_time(self) -> float:
        return self._match_time

    @property
    def base_speed(self) -> float:
        """User-set speed multiplier (unaffected by critical zones)."""
        if self._speed_curve is not None:
            return self._speed_curve.base_speed
        return self._base_speed

    @property
    def speed(self) -> float:
        """Alias for base_speed — preserves existing external call sites."""
        return self.base_speed

    @property
    def effective_speed(self) -> float:
        """Actual speed the clock is advancing at (may be 1.0 inside a critical zone)."""
        return self._effective_speed

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

                # Evaluate effective speed from curve (or base speed if no curve)
                if self._speed_curve is not None:
                    self._effective_speed = self._speed_curve.evaluate(self._match_time)
                else:
                    self._effective_speed = self._base_speed

                self._match_time += real_delta * self._effective_speed

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
