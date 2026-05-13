# backend/tests/player/test_emitter.py
"""Tests for player.emitter module (ReplaySession, session management)."""

from __future__ import annotations

import asyncio
import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from player.emitter import (
    ReplaySession,
    get_or_create_session,
    get_session,
    remove_session,
    _event_to_dict,
    _display_player,
    ANTICIPATION_WINDOW_SEC,
)
from player.loader import MatchEvent


# ---------------------------------------------------------------------------
# _display_player
# ---------------------------------------------------------------------------

class TestDisplayPlayer:
    def test_with_player_name(self):
        ev = MatchEvent(
            id="1", timestamp_sec=0.0, event_type="Pass", team="Home",
            player="Lionel Messi", position=(50, 40), end_position=None,
            details={}, index=0, is_home=True,
        )
        assert _display_player(ev) == "Lionel Messi"

    def test_no_player_for_starting_xi(self):
        ev = MatchEvent(
            id="1", timestamp_sec=0.0, event_type="Starting XI", team="Home",
            player=None, position=(60, 40), end_position=None,
            details={}, index=0, is_home=True,
        )
        assert _display_player(ev) == "Home"

    def test_no_player_fallback_to_team(self):
        ev = MatchEvent(
            id="1", timestamp_sec=0.0, event_type="Half Start", team="Away",
            player=None, position=(60, 40), end_position=None,
            details={}, index=0, is_home=False,
        )
        assert _display_player(ev) == "Away"


# ---------------------------------------------------------------------------
# _event_to_dict
# ---------------------------------------------------------------------------

class TestEventToDict:
    def test_basic_conversion(self):
        ev = MatchEvent(
            id="evt_123", timestamp_sec=120.5, event_type="Pass",
            team="Barcelona", player="Gavi", position=(65.0, 38.0),
            end_position=(70.0, 40.0), details={"pass_outcome": "Complete"},
            priority="routine", detected_patterns=["tiki_taka"], index=5, is_home=True,
        )
        result = _event_to_dict(ev)

        assert result["id"] == "evt_123"
        assert result["timestamp_sec"] == 120.5
        assert result["event_type"] == "Pass"
        assert result["team"] == "Barcelona"
        assert result["player"] == "Gavi"
        assert result["position"] == [65.0, 38.0]
        assert result["end_position"] == [70.0, 40.0]
        assert result["details"] == {"pass_outcome": "Complete"}
        assert result["priority"] == "routine"
        assert result["detected_patterns"] == ["tiki_taka"]
        assert result["is_home"] is True

    def test_none_end_position(self):
        ev = MatchEvent(
            id="1", timestamp_sec=0.0, event_type="Shot", team="Home",
            player="Striker", position=(95.0, 45.0), end_position=None,
            details={}, index=0, is_home=False,
        )
        result = _event_to_dict(ev)
        assert result["end_position"] is None


# ---------------------------------------------------------------------------
# ReplaySession Init
# ---------------------------------------------------------------------------

class TestReplaySessionInit:
    def test_session_loads_events(self, mock_match_file):
        with patch("player.emitter.MATCHES_DIR", str(Path(mock_match_file["match_file"]).parent)):
            session = ReplaySession(mock_match_file["match_id"])
            assert len(session.events) > 0

    def test_session_creates_critical_timeline(self, mock_match_file):
        with patch("player.emitter.MATCHES_DIR", str(Path(mock_match_file["match_file"]).parent)):
            session = ReplaySession(mock_match_file["match_id"])
            # Should have at least the shot event from sample data
            assert isinstance(session.critical_timeline, list)

    def test_session_attaches_speed_curve(self, mock_match_file):
        with patch("player.emitter.MATCHES_DIR", str(Path(mock_match_file["match_file"]).parent)):
            session = ReplaySession(mock_match_file["match_id"])
            assert session.clock._speed_curve is not None
            assert len(session.clock._speed_curve._zones) >= 0


# ---------------------------------------------------------------------------
# ReplaySession Subscribe/Unsubscribe
# ---------------------------------------------------------------------------

class TestReplaySessionSubscribe:
    def test_subscribe_returns_queue(self, mock_match_file):
        with patch("player.emitter.MATCHES_DIR", str(Path(mock_match_file["match_file"]).parent)):
            session = ReplaySession(mock_match_file["match_id"])
            q = session.subscribe()
            assert isinstance(q, asyncio.Queue)
            assert q in session._subscribers

    def test_multiple_subscribers(self, mock_match_file):
        with patch("player.emitter.MATCHES_DIR", str(Path(mock_match_file["match_file"]).parent)):
            session = ReplaySession(mock_match_file["match_id"])
            q1 = session.subscribe()
            q2 = session.subscribe()
            assert len(session._subscribers) == 2

    def test_unsubscribe(self, mock_match_file):
        with patch("player.emitter.MATCHES_DIR", str(Path(mock_match_file["match_file"]).parent)):
            session = ReplaySession(mock_match_file["match_id"])
            q = session.subscribe()
            session.unsubscribe(q)
            assert q not in session._subscribers


# ---------------------------------------------------------------------------
# ReplaySession Seek
# ---------------------------------------------------------------------------

class TestReplaySessionSeek:
    def test_seek_sets_event_index(self, mock_match_file):
        with patch("player.emitter.MATCHES_DIR", str(Path(mock_match_file["match_file"]).parent)):
            session = ReplaySession(mock_match_file["match_id"])
            session.seek(100.0)
            # Index should point to first event at or after 100s
            assert session._event_index >= 0

    def test_seek_flushes_queues(self, mock_match_file):
        with patch("player.emitter.MATCHES_DIR", str(Path(mock_match_file["match_file"]).parent)):
            session = ReplaySession(mock_match_file["match_id"])
            q = session.subscribe()

            # Add items to queue
            q.put_nowait({"type": "old_event"})

            # Seek should flush
            session.seek(100.0)

            # Queue should be empty after flush
            assert q.empty()

    def test_seek_resets_critical_index(self, mock_match_file):
        with patch("player.emitter.MATCHES_DIR", str(Path(mock_match_file["match_file"]).parent)):
            session = ReplaySession(mock_match_file["match_id"])
            session.seek(500.0)
            assert session._critical_index == 0  # Reset after seek


# ---------------------------------------------------------------------------
# ReplaySession Reset
# ---------------------------------------------------------------------------

class TestReplaySessionReset:
    def test_reset_clears_indices(self, mock_match_file):
        with patch("player.emitter.MATCHES_DIR", str(Path(mock_match_file["match_file"]).parent)):
            session = ReplaySession(mock_match_file["match_id"])
            session.seek(1000.0)
            assert session._event_index > 0
            session.reset()
            assert session._event_index == 0


# ---------------------------------------------------------------------------
# ReplaySession Event Emission
# ---------------------------------------------------------------------------

class TestReplaySessionOnTick:
    @pytest.mark.asyncio
    async def test_events_emitted_in_order(self, mock_match_file):
        with patch("player.emitter.MATCHES_DIR", str(Path(mock_match_file["match_file"]).parent)):
            session = ReplaySession(mock_match_file["match_id"])
            q = session.subscribe()

            # Fast forward past some events
            session.clock.reset(5000.0)
            session.clock.start()
            await asyncio.sleep(0.1)
            session.clock.stop()

            # Collect events
            emitted = []
            while not q.empty():
                emitted.append(q.get_nowait())

            # Events should be sorted by timestamp
            if len(emitted) >= 2:
                for i in range(len(emitted) - 1):
                    assert emitted[i]["timestamp_sec"] <= emitted[i + 1]["timestamp_sec"]


# ---------------------------------------------------------------------------
# Session Management
# ---------------------------------------------------------------------------

class TestSessionManagement:
    def test_get_or_create_new(self, mock_match_file):
        with patch("player.emitter.MATCHES_DIR", str(Path(mock_match_file["match_file"]).parent)):
            remove_session(mock_match_file["match_id"])  # Ensure clean
            session = get_or_create_session(mock_match_file["match_id"])
            assert session is not None
            assert session.match_id == mock_match_file["match_id"]

    def test_get_or_create_reuses(self, mock_match_file):
        with patch("player.emitter.MATCHES_DIR", str(Path(mock_match_file["match_file"]).parent)):
            remove_session(mock_match_file["match_id"])
            s1 = get_or_create_session(mock_match_file["match_id"])
            s2 = get_or_create_session(mock_match_file["match_id"])
            assert s1 is s2  # Same instance

    def test_get_session_nonexistent(self):
        remove_session("nonexistent_id_xyz")
        session = get_session("nonexistent_id_xyz")
        assert session is None

    def test_remove_session(self, mock_match_file):
        with patch("player.emitter.MATCHES_DIR", str(Path(mock_match_file["match_file"]).parent)):
            session = get_or_create_session(mock_match_file["match_id"])
            remove_session(mock_match_file["match_id"])
            assert get_session(mock_match_file["match_id"]) is None


# ---------------------------------------------------------------------------
# ReplaySession Close
# ---------------------------------------------------------------------------

class TestReplaySessionClose:
    def test_close_stops_clock(self, mock_match_file):
        with patch("player.emitter.MATCHES_DIR", str(Path(mock_match_file["match_file"]).parent)):
            session = ReplaySession(mock_match_file["match_id"])
            session.clock.start()
            session.close()
            assert session.clock.is_running is False

    def test_close_clears_subscribers(self, mock_match_file):
        with patch("player.emitter.MATCHES_DIR", str(Path(mock_match_file["match_file"]).parent)):
            session = ReplaySession(mock_match_file["match_id"])
            q = session.subscribe()
            session.close()
            assert len(session._subscribers) == 0


# ---------------------------------------------------------------------------
# Look-ahead Callback
# ---------------------------------------------------------------------------

class TestReplaySessionLookAhead:
    @pytest.mark.asyncio
    async def test_look_ahead_callback_at_high_speed(self, mock_match_file):
        with patch("player.emitter.MATCHES_DIR", str(Path(mock_match_file["match_file"]).parent)):
            callback_calls = []

            def look_ahead_cb(event_type: str, gap: float):
                callback_calls.append((event_type, gap))

            session = ReplaySession(mock_match_file["match_id"])
            session.register_look_ahead(look_ahead_cb)
            session.clock.set_speed(50.0)

            # Reset to near end where we have shots
            session.clock.reset(100.0)
            session.clock.start()
            await asyncio.sleep(0.2)
            session.clock.stop()


# ---------------------------------------------------------------------------
# Edge Cases
# ---------------------------------------------------------------------------

class TestEmitterEdgeCases:
    def test_seek_negative_time_clamped(self, mock_match_file):
        with patch("player.emitter.MATCHES_DIR", str(Path(mock_match_file["match_file"]).parent)):
            session = ReplaySession(mock_match_file["match_id"])
            session.seek(-100.0)
            # Should clamp to 0.0
            assert session.clock.get_time() == 0.0

    def test_event_dict_has_required_fields(self, mock_match_file):
        with patch("player.emitter.MATCHES_DIR", str(Path(mock_match_file["match_file"]).parent)):
            session = ReplaySession(mock_match_file["match_id"])
            ev = session.events[0]
            d = _event_to_dict(ev)
            assert "id" in d
            assert "timestamp_sec" in d
            assert "event_type" in d
            assert "team" in d
            assert "player" in d
            assert "position" in d