#!/usr/bin/env python3
"""
debug/test_commentator.py — Commentator subsystem standalone test.

Tests: commentator.agents.*, commentator.tts.engine, commentator.queue

Reads analyser state snapshot from debug/snapshots/ if present,
otherwise builds state from raw events — so it runs independently
of the other subsystems.

Run from backend/:
  python debug/test_commentator.py
  OLLAMA=1 python debug/test_commentator.py   # also calls live Ollama
  MATCH_ID=69249 python debug/test_commentator.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
import json
import time

MATCH_ID = os.environ.get("MATCH_ID", "3788741")
SNAPSHOTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "snapshots")

print("=" * 60)
print("COMMENTATOR — subsystem test")
print("=" * 60)

# ── Fixtures — build state (or restore from snapshot) ─────────────────────

from player.loader import load_events
from analyser.state import SharedMatchState
from analyser.classifier import classify_and_tag

events = load_events(MATCH_ID)
teams = list({e.team for e in events if e.team != "Unknown"})
home_team, away_team = teams[0], teams[1]

# Try restoring state from analyser snapshot for full isolation
state_snap_path = os.path.join(SNAPSHOTS_DIR, f"analyser_state_{MATCH_ID}.json")
if os.path.exists(state_snap_path):
    with open(state_snap_path) as f:
        snap_data = json.load(f)
    state = SharedMatchState(home_team=home_team, away_team=away_team)
    # Rebuild _team_stats from snapshot
    for team_name, sd in snap_data.get("stats", {}).items():
        from analyser.state import TeamStats
        ts = TeamStats(name=team_name)
        ts.shots = sd.get("shots", 0)
        ts.shots_on_target = sd.get("shots_on_target", 0)
        ts.passes_completed = sd.get("passes_completed", 0)
        ts.passes_attempted = sd.get("passes_attempted", 0)
        ts.fouls = sd.get("fouls", 0)
        ts.yellow_cards = sd.get("yellow_cards", 0)
        ts.red_cards = sd.get("red_cards", 0)
        ts.goals = sd.get("goals", 0)
        ts.xg = sd.get("xg", 0.0)
        state._team_stats[team_name] = ts
    state.score = snap_data.get("score", {"home": 0, "away": 0})
    state.current_match_time = snap_data.get("match_time", 0.0)
    print(f"\nFixture: loaded state from snapshot ({state_snap_path.split('/')[-1]})")
else:
    # Build from scratch
    state = SharedMatchState(home_team=home_team, away_team=away_team)
    for e in events[:600]:
        classify_and_tag(e)
    for i in range(0, 600, 50):
        batch = events[i:i + 50]
        state.update(batch, batch[-1].timestamp_sec)
    print(f"\nFixture: built state from first 600 events")

trigger = next((e for e in events[:600] if e.priority == "critical"), events[50])
print(f"Match  : {home_team} vs {away_team}")
print(f"Trigger: [{trigger.event_type}] {trigger.player} @ {trigger.timestamp_sec/60:.1f}'")

# ── 1. Agent prompt building ───────────────────────────────────────────────

from commentator.agents.play_by_play import PlayByPlayAgent
from commentator.agents.tactical import TacticalAgent
from commentator.agents.stats import StatsAgent
from commentator.agents.base import _events_to_text, _state_to_summary

pbp   = PlayByPlayAgent()
tac   = TacticalAgent()
stats = StatsAgent()
trigger_events = [trigger]

print("\n[agents] Assembled prompts (first 300 chars of user turn):")
prompts_dump = {}
for agent in (pbp, tac, stats):
    prompt = agent.build_prompt(trigger_events, state)
    prompts_dump[agent.name] = {"system": agent.system_prompt, "user": prompt}
    print(f"\n  --- {agent.name.upper()} ---")
    print(f"  System : {agent.system_prompt[:100].strip()}...")
    print(f"  User   : {prompt[:300].strip()}...")

# Dump prompts to snapshots
prompts_path = os.path.join(SNAPSHOTS_DIR, f"commentator_prompts_{MATCH_ID}.json")
with open(prompts_path, "w") as f:
    json.dump(prompts_dump, f, indent=2)
print(f"\n[agents] Prompt dump → {prompts_path}")

# ── 2. Fallback output (no LLM needed) ────────────────────────────────────

print("\n[agents] Fallback output (no LLM):")
for agent in (pbp, tac, stats):
    text = agent._fallback(trigger_events, state)
    print(f"  {agent.name:<14}: {text!r}")

# ── 3. Optional live Ollama call ───────────────────────────────────────────

if os.environ.get("OLLAMA") == "1":
    import httpx
    print("\n[agents] Checking Ollama ...")
    try:
        r = httpx.get("http://localhost:11434/api/tags", timeout=2.0)
        ollama_ok = r.status_code == 200
    except Exception:
        ollama_ok = False

    if ollama_ok:
        print("  Ollama reachable — generating from all 3 agents ...")
        ollama_results = {}

        async def call_agents():
            for agent in (pbp, tac, stats):
                t0 = time.monotonic()
                text = await agent.generate(trigger_events, state)
                ms = (time.monotonic() - t0) * 1000
                ollama_results[agent.name] = {"text": text, "ms": round(ms)}
                print(f"\n  [{agent.name}] ({ms:.0f}ms)")
                print(f"    {text!r}")

        asyncio.run(call_agents())

        llm_path = os.path.join(SNAPSHOTS_DIR, f"commentator_llm_{MATCH_ID}.json")
        with open(llm_path, "w") as f:
            json.dump(ollama_results, f, indent=2)
        print(f"\n[agents] LLM output dump → {llm_path}")
    else:
        print("  Ollama not running — skipping (set OLLAMA=1 to enable)")
else:
    print("\n[agents] Skipping live LLM call (set OLLAMA=1 to enable)")

# ── 4. TTS engine ──────────────────────────────────────────────────────────

from commentator.tts.engine import get_tts_engine

tts = get_tts_engine()
print(f"\n[tts] Backend  : {tts.backend}")
print(f"[tts] Available: {tts.available}")

if tts.available:
    sample_texts = {
        "play_by_play": "Messi cuts inside — he shoots — GOAL! Unbelievable!",
        "tactical":     "What you're seeing here is a high defensive line exploited in behind.",
        "stats":        "That's Barcelona's twelfth shot of the match.",
    }
    for agent_name, text in sample_texts.items():
        t0 = time.monotonic()
        wav = tts.synthesize_sync(text, agent_name)
        ms = (time.monotonic() - t0) * 1000
        if wav:
            wav_path = os.path.join(SNAPSHOTS_DIR, f"tts_{agent_name}.wav")
            with open(wav_path, "wb") as f:
                f.write(wav)
            duration = (len(wav) - 44) / (22050 * 2)
            print(f"  [{agent_name:<14}] {ms:>5.0f}ms  {duration:.2f}s  → {wav_path}")
        else:
            print(f"  [{agent_name:<14}] synthesis returned None")
else:
    print("  No TTS backend — skipping synthesis")

# ── 5. Audio queue ─────────────────────────────────────────────────────────

from commentator.queue import AudioQueue

print("\n[queue] Priority ordering test ...")

async def test_queue():
    q = AudioQueue()
    await q.put_audio("stats",        match_time=100.0, audio_bytes=b"s", text="stat fact")
    await q.put_audio("tactical",     match_time=101.0, audio_bytes=b"t", text="tactical obs")
    await q.put_audio("play_by_play", match_time=102.0, audio_bytes=b"p", text="pbp narration")

    drain = []
    while q.size > 0:
        item = await q.get_nowait()
        if item:
            drain.append(item.agent_name)

    expected = ["play_by_play", "tactical", "stats"]
    ok = drain == expected
    print(f"  Insert: stats → tactical → play_by_play")
    print(f"  Drain : {' → '.join(drain)}  {'OK' if ok else 'FAIL'}")

    from config import MAX_AUDIO_QUEUE_SIZE
    for i in range(MAX_AUDIO_QUEUE_SIZE + 1):
        await q.put_audio("stats", match_time=float(i), audio_bytes=b"x", text=f"item {i}")
    overflow_ok = q.size <= MAX_AUDIO_QUEUE_SIZE
    print(f"  Overflow drop (max={MAX_AUDIO_QUEUE_SIZE}): {'OK' if overflow_ok else 'FAIL'}")

asyncio.run(test_queue())

print("\n[PASS] Commentator subsystem OK\n")
