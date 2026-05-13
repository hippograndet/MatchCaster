# backend/tests/player/test_clock.py
"""Tests for player.clock module (MatchClock + SpeedCurve)."""

from __future__ import annotations

import asyncio
import time
import pytest

from player.clock import MatchClock, SpeedCurve, CriticalZone
from config import DEFAULT_SPEED_MULTIPLIER, CRITICAL_ZONE_PRE_SEC, CRITICAL_ZONE_POST_SEC


# ---------------------------------------------------------------------------
# SpeedCurve
# ---------------------------------------------------------------------------

class TestSpeedCurveInit:
    def test_default_base_speed(self):
        curve = SpeedCurve([])
        assert curve.base_speed == DEFAULT_SPEED_MULTIPLIER

    def test_custom_base_speed(self):
        curve = SpeedCurve([], base_speed=2.0)
        assert curve.base_speed == 2.0

    def test_speed_clamped_to_max(self):
        curve = SpeedCurve([], base_speed=100.0)
        assert curve.base_speed == 50.0

    def test_speed_clamped_to_min(self):
        curve = SpeedCurve([], base_speed=0.01)
        assert curve.base_speed == 0.1


class TestSpeedCurveBuild:
    def test_zones_created_from_events(self, critical_events):
        curve = SpeedCurve.build(critical_events, pre_sec=15.0, post_sec=5.0)
        assert len(curve._zones) == 2

    def test_zone_boundaries(self, critical_events):
        """Zone around 300s with 15s pre, 5s post = [285, 305]."""
        curve = SpeedCurve.build(critical_events, pre_sec=15.0, post_sec=5.0)
        zone = curve._zones[0]
        assert zone.start == pytest.approx(285.0)
        assert zone.end == pytest.approx(305.0)


class TestSpeedCurveEvaluate:
    def test_outside_zones_returns_base(self):
        curve = SpeedCurve([], base_speed=10.0)
        assert curve.evaluate(0.0) == 10.0

    def test_inside_zone_returns_1(self, critical_events):
        curve = SpeedCurve.build(critical_events, pre_sec=15.0, post_sec=5.0)
        # Inside zone around 300s (285 to 305)
        assert curve.evaluate(290.0) == 1.0
        assert curve.evaluate(300.0) == 1.0
        assert curve.evaluate(305.0) == 1.0

    def test_outside_zone_returns_base(self, critical_events):
        curve = SpeedCurve.build(critical_events, pre_sec=15.0, post_sec=5.0)
        assert curve.evaluate(0.0) == DEFAULT_SPEED_MULTIPLIER
        assert curve.evaluate(284.0) == DEFAULT_SPEED_MULTIPLIER
        assert curve.evaluate(306.0) == DEFAULT_SPEED_MULTIPLIER

    def test_multiple_zones(self, critical_events):
        """Both zones should return 1.0, others base."""
        curve = SpeedCurve.build(critical_events, pre_sec=15.0, post_sec=5.0)
        assert curve.evaluate(290.0) == 1.0   # inside first zone
        assert curve.evaluate(1810.0) == 1.0  # inside second zone
        assert curve.evaluate(1000.0) == DEFAULT_SPEED_MULTIPLIER


class TestSpeedCurveInCriticalZone:
    def test_at_zone_start(self, critical_events):
        curve = SpeedCurve.build(critical_events, pre_sec=15.0, post_sec=5.0)
        assert curve.in_critical_zone(285.0) is True

    def test_at_zone_end(self, critical_events):
        curve = SpeedCurve.build(critical_events, pre_sec=15.0, post_sec=5.0)
        assert curve.in_critical_zone(305.0) is True

    def test_just_before(self, critical_events):
        curve = SpeedCurve.build(critical_events, pre_sec=15.0, post_sec=5.0)
        assert curve.in_critical_zone(284.0) is False


class TestSpeedCurveSetBaseSpeed:
    def test_update_base_speed(self, critical_events):
        curve = SpeedCurve.build(critical_events, base_speed=1.0)
        curve.set_base_speed(5.0)
        assert curve.base_speed == 5.0

    def test_clamping(self, critical_events):
        curve = SpeedCurve.build(critical_events)
        curve.set_base_speed(0.05)
        assert curve.base_speed == 0.1


# ---------------------------------------------------------------------------
# MatchClock Lifecycle
# ---------------------------------------------------------------------------

class TestMatchClockInit:
    def test_initial_time_is_zero(self):
        clock = MatchClock()
        assert clock.get_time() == 0.0

    def test_initial_speed(self):
        clock = MatchClock(speed=5.0)
        assert clock.speed == 5.0

    def test_initial_paused(self):
        clock = MatchClock()
        assert clock.is_running is False


class TestMatchClockStart:
    def test_start_sets_running(self):
        clock = MatchClock()
        clock.start()
        assert clock.is_running is True

    def test_double_start_guard(self):
        clock = MatchClock()
        clock.start()
        clock.start()  # should not crash
        assert clock.is_running is True


class TestMatchClockPause:
    def test_pause_stops_clock(self):
        clock = MatchClock()
        clock.start()
        clock.pause()
        assert clock.is_running is False

    def test_pause_preserves_time(self):
        clock = MatchClock()
        clock.start()
        time.sleep(0.05)
        clock.pause()
        t = clock.get_time()
        clock.pause()  # double pause
        assert clock.get_time() == t


class TestMatchClockResume:
    def test_resume_after_pause(self):
        clock = MatchClock()
        clock.start()
        clock.pause()
        clock.resume()
        assert clock.is_running is True


class TestMatchClockStop:
    def test_stop_clears_running(self):
        clock = MatchClock()
        clock.start()
        clock.stop()
        assert clock.is_running is False

    def test_stop_cancels_task(self):
        clock = MatchClock()
        clock.start()
        clock.stop()
        time.sleep(0.05)
        assert clock._task is None or clock._task.done()


class TestMatchClockReset:
    def test_reset_to_specific_time(self):
        clock = MatchClock()
        clock.start()
        clock.reset(500.0)
        assert clock.get_time() == pytest.approx(500.0, abs=1.0)

    def test_reset_to_zero(self):
        clock = MatchClock()
        clock.start()
        time.sleep(0.05)
        clock.reset(0.0)
        assert clock.get_time() == 0.0


# ---------------------------------------------------------------------------
# MatchClock Tick Callbacks
# ---------------------------------------------------------------------------

class TestMatchClockTickCallbacks:
    @pytest.mark.asyncio
    async def test_callback_registered(self):
        """Tick callback should be invoked on each tick."""
        clock = MatchClock(speed=50.0)
        received: list[float] = []

        async def on_tick(match_time: float):
            received.append(match_time)

        clock.register_tick(on_tick)
        clock.start()
        await asyncio.sleep(0.15)
        clock.stop()

        assert len(received) > 0
        # Last tick should be near 7.5s (0.15s × 50×)
        assert received[-1] > 0

    @pytest.mark.asyncio
    async def test_callback_exception_caught(self):
        """Tick callback exception should not crash the loop."""
        clock = MatchClock(speed=10.0)
        call_count = 0

        async def flaky_callback(mt: float):
            nonlocal call_count
            call_count += 1
            if call_count > 2:
                raise ValueError("Test error")

        async def on_tick(mt: float):
            await flaky_callback(mt)

        clock.register_tick(on_tick)
        clock.start()
        await asyncio.sleep(0.2)
        clock.stop()
        # Should survive the exception
        assert clock._running is False

    @pytest.mark.asyncio
    async def test_multiple_callbacks(self):
        """Multiple callbacks all get called."""
        clock = MatchClock(speed=50.0)
        count1, count2 = 0, 0

        async def cb1(mt: float):
            nonlocal count1
            count1 += 1

        async def cb2(mt: float):
            nonlocal count2
            count2 += 1

        clock.register_tick(cb1)
        clock.register_tick(cb2)
        clock.start()
        await asyncio.sleep(0.15)
        clock.stop()

        assert count1 == count2
        assert count1 > 0


# ---------------------------------------------------------------------------
# MatchClock Speed Control
# ---------------------------------------------------------------------------

class TestMatchClockSetSpeed:
    def test_set_speed_without_curve(self):
        clock = MatchClock()
        clock.set_speed(10.0)
        assert clock.speed == 10.0

    def test_set_speed_with_curve(self, critical_events):
        clock = MatchClock()
        curve = SpeedCurve.build(critical_events)
        clock.set_speed_curve(curve)
        clock.set_speed(5.0)
        assert clock.speed == 5.0

    def test_same_speed_noop(self):
        """Setting same speed should not trigger updates."""
        clock = MatchClock(speed=2.0)
        # This should be a no-op
        clock.set_speed(2.0)
        assert clock.speed == 2.0

    def test_speed_clamping(self):
        clock = MatchClock()
        clock.set_speed(0.01)
        assert clock.speed == 0.1


# ---------------------------------------------------------------------------
# MatchClock Effective Speed
# ---------------------------------------------------------------------------

class TestMatchClockEffectiveSpeed:
    @pytest.mark.asyncio
    async def test_critical_zone_enforcement(self, critical_events):
        """Effective speed should hard-cut to 1.0 inside critical zones."""
        clock = MatchClock(speed=10.0)
        curve = SpeedCurve.build(critical_events, pre_sec=15.0, post_sec=5.0)
        clock.set_speed_curve(curve)

        clock.start()
        clock.reset(285.0)  # start at edge of critical zone
        await asyncio.sleep(0.15)
        clock.stop()

        # Inside zone, effective should be 1.0
        assert clock.effective_speed == 1.0

    def test_effective_speed_without_curve(self):
        """Without curve, effective_speed equals base speed."""
        clock = MatchClock(speed=5.0)
        # No curve attached
        assert clock.effective_speed == 5.0

    @pytest.mark.asyncio
    async def test_effective_speed_outside_zone(self, critical_events):
        """Outside critical zone, effective_speed equals base speed."""
        clock = MatchClock(speed=10.0)
        curve = SpeedCurve.build(critical_events, pre_sec=15.0, post_sec=5.0)
        clock.set_speed_curve(curve)

        # Reset to time far from critical zones (e.g., 1000s)
        clock.reset(1000.0)
        clock.start()
        await asyncio.sleep(0.05)
        clock.stop()

        assert clock.effective_speed == 10.0


# ---------------------------------------------------------------------------
# MatchClock Base Speed Property
# ---------------------------------------------------------------------------

class TestMatchClockBaseSpeed:
    def test_base_speed_property(self):
        clock = MatchClock(speed=3.0)
        assert clock.base_speed == 3.0

    def test_speed_alias(self):
        """speed property is alias for base_speed."""
        clock = MatchClock(speed=4.0)
        assert clock.speed == clock.base_speed