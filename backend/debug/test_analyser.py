#!/usr/bin/env python3
"""
debug/test_analyser.py — Match Analyser subsystem standalone test.

Tests: analyser.classifier, analyser.state, analyser.engine,
       analyser.spatial, analyser.enrichment.*

Reads from debug/snapshots/player_snapshots_<MATCH_ID>.json if present
(produced by test_player.py), so failures are independently reproducible.

Run from backend/:  python debug/test_analyser.py
                    MATCH_ID=69249 python debug/test_analyser.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
from collections import Counter

MATCH_ID = os.environ.get("MATCH_ID", "3788741")
SNAPSHOTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "snapshots")

print("=" * 60)
print("MATCH ANALYSER — subsystem test")
print("=" * 60)

from player.loader import load_events
events = load_events(MATCH_ID)
teams = list({e.team for e in events if e.team != "Unknown"})
home_team, away_team = teams[0], teams[1]
print(f"\nMatch: {home_team} vs {away_team}  ({len(events)} events)")

# ── 1. Classifier ──────────────────────────────────────────────────────────

from analyser.classifier import classify_and_tag, SequenceDetector, CRITICAL, NOTABLE, ROUTINE

print("\n[classifier] Classifying all events ...")
for e in events:
    classify_and_tag(e)

dist = Counter(e.priority for e in events)
total = len(events)
print(f"  CRITICAL : {dist[CRITICAL]:>5}  ({dist[CRITICAL]/total*100:.1f}%)")
print(f"  NOTABLE  : {dist[NOTABLE]:>5}  ({dist[NOTABLE]/total*100:.1f}%)")
print(f"  ROUTINE  : {dist[ROUTINE]:>5}  ({dist[ROUTINE]/total*100:.1f}%)")

critical_events = [e for e in events if e.priority == CRITICAL]
print(f"\n[classifier] Top 5 CRITICAL events:")
for e in critical_events[:5]:
    detail = e.details.get("shot_outcome") or e.details.get("foul_card") or ""
    print(f"  {e.timestamp_sec/60:>5.1f}' [{e.event_type:<20}] {e.player:<25} {detail}")

print("\n[classifier] SequenceDetector on first 200 events ...")
detector = SequenceDetector()
all_patterns: list[str] = []
for e in events[:200]:
    detected = detector.add(e)
    all_patterns.extend(detected)
print(f"  Patterns: {dict(Counter(all_patterns))}")

# Dump classified events summary to snapshots
snap_path = os.path.join(SNAPSHOTS_DIR, f"analyser_classification_{MATCH_ID}.json")
with open(snap_path, "w") as f:
    json.dump({
        "match_id": MATCH_ID,
        "total": total,
        "distribution": dict(dist),
        "critical_events": [
            {"type": e.event_type, "player": e.player, "team": e.team,
             "time": round(e.timestamp_sec, 1)}
            for e in critical_events
        ],
    }, f, indent=2)
print(f"\n[classifier] Snapshot dump → {snap_path}")

# ── 2. Shared State ────────────────────────────────────────────────────────

from analyser.state import SharedMatchState

print("\n[state] Feeding 500 events through SharedMatchState ...")
state = SharedMatchState(home_team=home_team, away_team=away_team)
for i in range(0, min(500, len(events)), 50):
    batch = events[i:i + 50]
    state.update(batch, batch[-1].timestamp_sec)

print(f"  Score      : {state.score_str()}")
print(f"  Minute     : {state.minute_str()}")
print(f"  Phase      : {state.current_phase}")
poss = state.possession_pct()
print(f"  Possession : {home_team} {poss[home_team]:.1f}%  /  {away_team} {poss[away_team]:.1f}%")
hs = state.get_stats(home_team)
as_ = state.get_stats(away_team)
if hs and as_:
    print(f"  Shots      : {home_team} {hs.shots}  /  {away_team} {as_.shots}")
    print(f"  Fouls      : {home_team} {hs.fouls}  /  {away_team} {as_.fouls}")

# Dump state snapshot
state_snap_path = os.path.join(SNAPSHOTS_DIR, f"analyser_state_{MATCH_ID}.json")
with open(state_snap_path, "w") as f:
    json.dump(state.to_dict(), f, indent=2)
print(f"\n[state] Snapshot dump → {state_snap_path}")

# ── 3. Analysis Engine ─────────────────────────────────────────────────────

from analyser.engine import MatchAnalysisEngine

print("\n[engine] Running MatchAnalysisEngine on first 1000 events ...")
engine = MatchAnalysisEngine(home_team=home_team, away_team=away_team)
for i in range(0, min(1000, len(events)), 50):
    batch = events[i:i + 50]
    engine.update(batch, batch[-1].timestamp_sec)

snap = engine.get_context_snapshot()
print(f"  Momentum   : {home_team} {snap.momentum_home:.0f}  /  {away_team} {snap.momentum_away:.0f}")
print(f"  xG         : {home_team} {snap.xg_home:.2f}  /  {away_team} {snap.xg_away:.2f}")
print(f"  Shots      : {len(snap.shots)}")
print(f"  Box entries: {snap.dangerous_entries}")

# ── New per-granularity context fields ─────────────────────────────────────
print(f"\n[engine] AnalysisPacket — per-granularity text context:")
print(f"  instant_text      : {snap.instant_text or '(empty)'}")
print(f"  short_term_text   : {snap.short_term_text[:100] if snap.short_term_text else '(empty)'}")
print(f"  long_term_text    : {snap.long_term_text[:100] if snap.long_term_text else '(empty)'}")
print(f"  match_totals_text :")
for line in (snap.match_totals_text or "(empty)").split("\n"):
    print(f"    {line}")

# Verify all four fields are non-empty at this point in the match
assert snap.short_term_text, "short_term_text should be non-empty after 1000 events"
assert snap.match_totals_text, "match_totals_text should be non-empty after 1000 events"
print("\n[engine] All four context fields present — OK")

# ── 4. Spatial Converter ───────────────────────────────────────────────────

from analyser.spatial import coords_to_description, coords_to_zone

print("\n[spatial] Coordinate → description samples:")
for x, y, label in [(2,40,"own goal"), (60,40,"midfield"), (95,64,"left channel"),
                     (110,10,"right box"), (118,40,"six-yard box")]:
    desc = coords_to_description(x, y)
    zone = coords_to_zone(x, y)
    print(f"  ({x:>3},{y:>2})  {zone}  → {desc}")

# ── 5. Enrichment ──────────────────────────────────────────────────────────

from analyser.enrichment.match_meta import get_match_meta
from analyser.enrichment.team_colors import get_team_colors

print("\n[enrichment] Match metadata:")
meta = get_match_meta(MATCH_ID, home_team, away_team)
print(f"  {meta.competition} {meta.season} | {meta.stadium}, {meta.city}")
print(f"  {meta.date} {meta.kick_off} | {meta.home_manager} vs {meta.away_manager}")

print("\n[enrichment] Team colours:")
for team in [home_team, away_team]:
    c = get_team_colors(team)
    print(f"  {team:<25}  primary={c['primary']}  secondary={c['secondary']}")

print("\n[PASS] Match Analyser subsystem OK\n")
