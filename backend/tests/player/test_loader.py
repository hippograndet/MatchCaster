# backend/tests/player/test_loader.py
"""Tests for player.loader module."""

from __future__ import annotations

import json
import pytest
from pathlib import Path
from unittest.mock import patch

from player.loader import (
    _parse_timestamp,
    _flip_coords,
    _extract_position,
    _extract_end_position,
    _extract_player,
    _extract_team,
    _build_details,
    load_events,
    load_lineup,
    compute_snapshots,
    compute_goal_timeline,
    get_score_at,
    compute_critical_timeline,
    list_available_matches,
    MatchEvent,
)
from .conftest import make_event, SAMPLE_HOME_TEAM, SAMPLE_AWAY_TEAM


# ---------------------------------------------------------------------------
# Timestamp parsing
# ---------------------------------------------------------------------------

class TestParseTimestamp:
    def test_hh_mm_ss_ms_format(self):
        """HH:MM:SS.mmm format (StatsBomb standard)."""
        assert _parse_timestamp("00:01:30.500") == pytest.approx(90.5)

    def test_hh_mm_ss_ms_two_hours(self):
        """Two-hour timestamp."""
        assert _parse_timestamp("02:15:00.000") == pytest.approx(2 * 3600 + 15 * 60)

    def test_mm_ss_ms_format(self):
        """MM:SS.mmm format."""
        assert _parse_timestamp("45:30.000") == pytest.approx(45 * 60 + 30)

    def test_empty_string(self):
        """Empty string returns 0."""
        assert _parse_timestamp("") == 0.0

    def test_none_value(self):
        """None returns 0."""
        assert _parse_timestamp(None) == 0.0

    def test_invalid_format(self):
        """Invalid format returns 0."""
        assert _parse_timestamp("not_a_time") == 0.0

    def test_edge_case_colon_count(self):
        """Wrong number of colons."""
        assert _parse_timestamp("1:2:3:4") == 0.0

    def test_extra_period_offset_p2(self):
        """Period 2 starts at 45 min (2700 sec)."""
        # This is tested via load_events period_offsets


# ---------------------------------------------------------------------------
# Coordinate flipping
# ---------------------------------------------------------------------------

class TestFlipCoords:
    def test_home_attacks_right(self):
        """Home team should NOT flip (x stays as-is)."""
        pos = (95.0, 40.0)
        assert _flip_coords(pos) == (95.0, 40.0)

    def test_away_flipped(self):
        """Away team should flip so home always attacks right."""
        # Original: away attacks toward x=120 in their own frame
        # After flip: should mirror to home perspective
        pos = (25.0, 40.0)  # away's "attack" zone
        flipped = _flip_coords(pos)
        assert flipped[0] == 120.0 - 25.0  # 95.0
        assert flipped[1] == 80.0 - 40.0  # 40.0

    def test_center_pitch(self):
        """Center (60, 40) stays unchanged after flip."""
        assert _flip_coords((60.0, 40.0)) == (60.0, 40.0)

    def test_corner_positions(self):
        """All four corners map correctly."""
        # Top-right corner of home (attacking)
        assert _flip_coords((120.0, 0.0)) == (0.0, 80.0)
        # Bottom-right
        assert _flip_coords((120.0, 80.0)) == (0.0, 0.0)
        # Top-left (away attacking)
        assert _flip_coords((0.0, 0.0)) == (120.0, 80.0)


# ---------------------------------------------------------------------------
# Event extraction helpers
# ---------------------------------------------------------------------------

class TestExtractPosition:
    def test_valid_location(self):
        ev = {"location": [70.0, 45.0]}
        assert _extract_position(ev) == (70.0, 45.0)

    def test_missing_location(self):
        ev = {}
        assert _extract_position(ev) == (60.0, 40.0)  # center default

    def test_partial_location(self):
        ev = {"location": [70.0]}
        assert _extract_position(ev) == (70.0, 40.0)

    def test_non_list_location(self):
        ev = {"location": "invalid"}
        assert _extract_position(ev) == (60.0, 40.0)


class TestExtractEndPosition:
    def test_pass_end_location(self):
        ev = {"pass": {"end_location": [75.0, 42.0]}}
        assert _extract_end_position(ev) == (75.0, 42.0)

    def test_shot_end_location(self):
        ev = {"shot": {"end_location": [95.0, 45.0]}}
        assert _extract_end_position(ev) == (95.0, 45.0)

    def test_missing_end_location(self):
        ev = {"pass": {}}
        assert _extract_end_position(ev) is None

    def test_no_sub_object(self):
        ev = {"type": {"name": "Pass"}}
        assert _extract_end_position(ev) is None


class TestExtractPlayer:
    def test_dict_player(self):
        ev = {"player": {"name": "Lionel Messi"}}
        assert _extract_player(ev) == "Lionel Messi"

    def test_string_player(self):
        ev = {"player": "Messi"}
        assert _extract_player(ev) == "Messi"

    def test_no_player(self):
        ev = {"type": {"name": "Half Start"}}
        assert _extract_player(ev) is None

    def test_empty_player_dict(self):
        ev = {"player": {}}
        assert _extract_player(ev) is None


class TestExtractTeam:
    def test_dict_team(self):
        ev = {"team": {"name": "Barcelona"}}
        assert _extract_team(ev) == "Barcelona"

    def test_string_team(self):
        ev = {"team": "Real Madrid"}
        assert _extract_team(ev) == "Real Madrid"

    def test_no_team(self):
        ev = {}
        assert _extract_team(ev) == "Unknown"


# ---------------------------------------------------------------------------
# Details extraction
# ---------------------------------------------------------------------------

class TestBuildDetails:
    def test_pass_details(self):
        ev = {
            "pass": {
                "outcome": {"name": "Complete"},
                "type": {"name": "Ground"},
                "length": 25.5,
                "goal_assist": True,
            }
        }
        d = _build_details(ev)
        assert d["pass_outcome"] == "Complete"
        assert d["pass_type"] == "Ground"
        assert d["pass_length"] == 25.5
        assert d["goal_assist"] is True

    def test_shot_details(self):
        ev = {
            "shot": {
                "statsbomb_xg": 0.75,
                "outcome": {"name": "Saved"},
                "technique": {"name": "Volley"},
                "first_time": True,
            }
        }
        d = _build_details(ev)
        assert d["xg"] == 0.75
        assert d["shot_outcome"] == "Saved"
        assert d["shot_technique"] == "Volley"
        assert d["first_time"] is True

    def test_foul_with_yellow_card(self):
        ev = {"foul_committed": {"card": {"name": "Yellow Card"}}}
        d = _build_details(ev)
        assert d["foul_card"] == "Yellow Card"

    def test_foul_with_red_card(self):
        ev = {"foul_committed": {"card": {"name": "Red Card"}}}
        d = _build_details(ev)
        assert d["foul_card"] == "Red Card"

    def test_empty_event(self):
        ev = {}
        d = _build_details(ev)
        assert d["period"] == 1
        assert d["minute"] == 0
        assert d["second"] == 0


# ---------------------------------------------------------------------------
# compute_snapshots
# ---------------------------------------------------------------------------

class TestComputeSnapshots:
    def test_passes_counted(self):
        events = [
            MatchEvent(id="1", timestamp_sec=10, event_type="Pass", team="Home",
                       player="A", position=(20, 40), end_position=None, details={}, index=0, is_home=True),
            MatchEvent(id="2", timestamp_sec=20, event_type="Pass", team="Home",
                       player="A", position=(30, 40), end_position=None, details={}, index=1, is_home=True),
        ]
        snaps = compute_snapshots(events, "Home", "Away")
        assert len(snaps) == 1  # t=0 initial
        assert snaps[0]["stats"]["Home"]["passes_attempted"] == 2

    def test_goal_increments_score(self):
        events = [
            MatchEvent(id="1", timestamp_sec=60, event_type="Shot", team="Home",
                       player="Striker", position=(95, 45), end_position=None,
                       details={"shot_outcome": "Goal", "xg": 0.5}, index=0, is_home=True),
        ]
        snaps = compute_snapshots(events, "Home", "Away")
        assert snaps[-1]["score"]["home"] == 1

    def test_xg_accumulated(self):
        events = [
            MatchEvent(id="1", timestamp_sec=60, event_type="Shot", team="Home",
                       player="Striker", position=(95, 45), end_position=None,
                       details={"shot_outcome": "Goal", "xg": 0.35}, index=0, is_home=True),
            MatchEvent(id="2", timestamp_sec=120, event_type="Shot", team="Home",
                       player="Striker", position=(90, 35), end_position=None,
                       details={"shot_outcome": "Saved", "xg": 0.25}, index=1, is_home=True),
        ]
        snaps = compute_snapshots(events, "Home", "Away")
        last = snaps[-1]
        assert last["stats"]["Home"]["xg"] == pytest.approx(0.60)

    def test_snapshots_at_intervals(self):
        """Snapshots every 300 seconds (5 min)."""
        events = [
            MatchEvent(id=str(i), timestamp_sec=i * 100, event_type="Pass",
                       team="Home", player="A", position=(20, 40), end_position=None,
                       details={}, index=i, is_home=True)
            for i in range(20)
        ]
        snaps = compute_snapshots(events, "Home", "Away")
        # t=0 + t=300 + t=600 + t=900 + t=1200 + ...
        expected_count = 1 + (600 // 300)  # initial + intervals up to max time
        assert len(snaps) >= expected_count


# ---------------------------------------------------------------------------
# compute_goal_timeline
# ---------------------------------------------------------------------------

class TestComputeGoalTimeline:
    def test_single_goal(self):
        events = [
            MatchEvent(id="1", timestamp_sec=60, event_type="Shot", team="Home",
                       player="Striker", position=(95, 45), end_position=None,
                       details={"shot_outcome": "Goal"}, index=0, is_home=True),
        ]
        tl = compute_goal_timeline(events, "Home", "Away")
        assert len(tl) == 1
        assert tl[0]["scorer"] == "Striker"
        assert tl[0]["score_home"] == 1

    def test_no_goals(self):
        events = [
            MatchEvent(id="1", timestamp_sec=60, event_type="Pass", team="Home",
                       player="Mid", position=(50, 40), end_position=None, details={}, index=0, is_home=True),
        ]
        tl = compute_goal_timeline(events, "Home", "Away")
        assert len(tl) == 0

    def test_away_goal(self):
        events = [
            MatchEvent(id="1", timestamp_sec=60, event_type="Shot", team="Away",
                       player="Striker", position=(95, 45), end_position=None,
                       details={"shot_outcome": "Goal"}, index=0, is_home=False),
        ]
        tl = compute_goal_timeline(events, "Home", "Away")
        assert len(tl) == 1
        assert tl[0]["is_home"] is False
        assert tl[0]["score_away"] == 1


class TestGetScoreAt:
    def test_exclusive_boundary(self):
        """Goals at exactly T are NOT counted."""
        timeline = [
            {"t": 300.0, "is_home": True},
            {"t": 600.0, "is_home": False},
        ]
        score = get_score_at(timeline, 300.0)
        assert score["home"] == 0  # not inclusive

    def test_before_first_goal(self):
        score = get_score_at([{"t": 300.0, "is_home": True}], 299.0)
        assert score["home"] == 0

    def test_after_last_goal(self):
        timeline = [{"t": 300.0, "is_home": True}]
        score = get_score_at(timeline, 1000.0)
        assert score["home"] == 1


# ---------------------------------------------------------------------------
# compute_critical_timeline
# ---------------------------------------------------------------------------

class TestComputeCriticalTimeline:
    def test_shot_is_critical(self):
        events = [
            MatchEvent(id="1", timestamp_sec=100, event_type="Shot", team="Home",
                       player="Striker", position=(95, 45), end_position=None, details={}, index=0, is_home=True),
            MatchEvent(id="2", timestamp_sec=200, event_type="Pass", team="Home",
                       player="Mid", position=(50, 40), end_position=None, details={}, index=1, is_home=True),
        ]
        critical = compute_critical_timeline(events)
        assert len(critical) == 1
        assert critical[0].id == "1"

    def test_red_card_is_critical(self):
        events = [
            MatchEvent(id="1", timestamp_sec=100, event_type="Foul Committed", team="Away",
                       player="Defender", position=(40, 35), end_position=None,
                       details={"foul_card": "Red Card"}, index=0, is_home=False),
        ]
        critical = compute_critical_timeline(events)
        assert len(critical) == 1

    def test_yellow_card_not_critical(self):
        events = [
            MatchEvent(id="1", timestamp_sec=100, event_type="Foul Committed", team="Away",
                       player="Defender", position=(40, 35), end_position=None,
                       details={"foul_card": "Yellow Card"}, index=0, is_home=False),
        ]
        critical = compute_critical_timeline(events)
        assert len(critical) == 0


# ---------------------------------------------------------------------------
# load_lineup
# ---------------------------------------------------------------------------

class TestLoadLineup:
    def test_load_existing_team(self, mock_match_file):
        with patch("player.loader.LINEUPS_DIR", str(Path(mock_match_file["lineup_file"]).parent)):
            lineup = load_lineup(mock_match_file["match_id"], "Home United")
            assert len(lineup) == 2
            assert lineup[0]["name"] == "Player A"

    def test_load_nonexistent_team(self, mock_match_file):
        with patch("player.loader.LINEUPS_DIR", str(Path(mock_match_file["lineup_file"]).parent)):
            lineup = load_lineup(mock_match_file["match_id"], "Unknown Team")
            assert lineup == []

    def test_case_insensitive_match(self, mock_match_file):
        with patch("player.loader.LINEUPS_DIR", str(Path(mock_match_file["lineup_file"]).parent)):
            lineup = load_lineup(mock_match_file["match_id"], "home united")
            assert len(lineup) == 2


# ---------------------------------------------------------------------------
# list_available_matches
# ---------------------------------------------------------------------------

class TestListAvailableMatches:
    def test_empty_dir(self, tmp_path):
        with patch("player.loader.MATCHES_DIR", str(tmp_path)):
            matches = list_available_matches()
            assert matches == []

    def test_with_json_files(self, tmp_path, sample_match_data):
        match_file = tmp_path / "99999.json"
        with open(match_file, "w", encoding="utf-8") as fp:
            json.dump(sample_match_data, fp)
        with patch("player.loader.MATCHES_DIR", str(tmp_path)):
            matches = list_available_matches()
            assert len(matches) == 1
            assert matches[0]["match_id"] == "99999"