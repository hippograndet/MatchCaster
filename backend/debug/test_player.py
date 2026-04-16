#!/usr/bin/env python3
"""
debug/test_player.py — Match Player subsystem standalone test.

Tests: player.loader, player.clock, player.emitter
Run from backend/:  python debug/test_player.py
                    MATCH_ID=69249 python debug/test_player.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
import json
from collections import Counter

MATCH_ID = os.environ.get("MATCH_ID", "3788741")
SNAPSHOTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "snapshots")

# ── 1. Loader ──────────────────────────────────────────────────────────────

from player.loader import load_events, list_available_matches, compute_snapshots, compute_goal_timeline, get_score_at

print("=" * 60)
print("MATCH PLAYER — subsystem test")
print("=" * 60)

matches = list_available_matches()
print(f"\n[loader] Available matches: {len(matches)}")
for m in matches:
    teams = " vs ".join(m["teams"]) if m["teams"] else "?"
    print(f"  {m['match_id']:>10}  {teams:<35}  {m['event_count']} events")

print(f"\n[loader] Loading match {MATCH_ID} ...")
events = load_events(MATCH_ID)
last = events[-1]
period_label = (
    f" — period {last.details.get('period', '?')}" if last.event_type == "Half End" else ""
)
print(f"  Total events    : {len(events)}")
print(f"  First timestamp : {events[0].timestamp_sec:.1f}s  ({events[0].event_type})")
print(f"  Last  timestamp : {last.timestamp_sec:.1f}s  ({last.event_type}{period_label})")
print(f"  Duration        : {last.timestamp_sec / 60:.1f} game-minutes")

counts = Counter(e.event_type for e in events)
print(f"\n[loader] Top 10 event types:")
for etype, n in counts.most_common(10):
    print(f"  {n:>5}  {etype}")

for target in ("Shot", "Substitution"):
    sample = next((e for e in events if e.event_type == target), None)
    if sample:
        print(f"\n[loader] First {target}:")
        print(f"  player  : {sample.player}")
        print(f"  team    : {sample.team}")
        print(f"  time    : {sample.timestamp_sec:.1f}s")
        print(f"  position: {sample.position}")
        print(f"  details : {dict(list(sample.details.items())[:4])}")

teams = list({e.team for e in events if e.team})
if len(teams) >= 2:
    home_team, away_team = teams[0], teams[1]

    # ── Goal timeline (exact, derivable at any time T) ──
    goal_tl = compute_goal_timeline(events, home_team, away_team)
    print(f"\n[loader] Goal timeline: {len(goal_tl)} goal(s)")
    for g in goal_tl:
        min_str = f"{g['t'] / 60:.0f}'"
        scorer = g["scorer"] or g["team"]
        assist_str = f"  assist: {g['assist']}" if g["assist"] else ""
        print(f"  {min_str}  {g['team']}  {scorer}{assist_str}  → {g['score_home']}–{g['score_away']}")

    # Spot-check: score at 45 min
    score_45 = get_score_at(goal_tl, 45 * 60)
    score_ft = get_score_at(goal_tl, events[-1].timestamp_sec)
    print(f"  Score @ 45 min : {score_45}")
    print(f"  Score @ FT     : {score_ft}")

    # ── Stats snapshots (every 5 min, for seek-restoration) ──
    snaps = compute_snapshots(events, home_team, away_team)
    print(f"\n[loader] Stat snapshots: {len(snaps)} (every 5 min)")
    for s in snaps[:3]:
        print(f"  t={s['t']:.0f}s  stats sample: shots_home={s['stats'].get(home_team, {}).get('shots', 0)}")

    # Dump snapshot to debug/snapshots/ for cross-subsystem reproducibility
    snap_path = os.path.join(SNAPSHOTS_DIR, f"player_snapshots_{MATCH_ID}.json")
    with open(snap_path, "w") as f:
        json.dump(snaps, f, indent=2)
    print(f"\n[loader] Snapshot dump → {snap_path}")

# ── 2. Clock ───────────────────────────────────────────────────────────────

from player.clock import MatchClock

print("\n[clock] Running clock for 0.2s real-time at 10× speed ...")

ticks_received = []

async def run_clock_test():
    clock = MatchClock(speed=10.0)

    async def on_tick(match_time: float):
        ticks_received.append(round(match_time, 2))

    clock.register_tick(on_tick)
    clock.start()
    await asyncio.sleep(0.2)
    clock.stop()
    await asyncio.sleep(0.05)

asyncio.run(run_clock_test())

if ticks_received:
    print(f"  Ticks received  : {len(ticks_received)}")
    print(f"  Match time range: {ticks_received[0]}s → {ticks_received[-1]}s")
    # Total advance from clock start (0), not delta between ticks
    actual_advance = ticks_received[-1]
    expected = 0.2 * 10
    ok = abs(actual_advance - expected) < 1.0   # ±1s tolerance for asyncio jitter
    print(f"  Advance ~{expected:.1f}s game-time: {'OK' if ok else 'WARN'} ({actual_advance:.2f}s)")
else:
    print("  WARNING: no ticks received")

# ── 3. Emitter ─────────────────────────────────────────────────────────────

from player.emitter import get_or_create_session

print(f"\n[emitter] Creating ReplaySession for match {MATCH_ID} ...")
session = get_or_create_session(MATCH_ID)
print(f"  Events loaded   : {len(session.events)}")
print(f"  Clock speed     : {session.clock.speed}×")

received = []

async def run_emitter_test():
    q = session.subscribe()
    session.clock.set_speed(50.0)
    session.clock.start()
    await asyncio.sleep(0.1)
    session.clock.stop()
    while not q.empty():
        received.append(q.get_nowait())
    session.unsubscribe(q)

asyncio.run(run_emitter_test())
print(f"  Events emitted  : {len(received)} in 0.1s at 50× speed")
if received:
    print(f"  First emitted   : [{received[0]['event_type']}] {received[0]['player']}")

print("\n[PASS] Match Player subsystem OK\n")
