# Manual Debugging Guidelines — MatchCaster

## How to use this guide
Run each section independently. Note anything that looks wrong, unexpected, or inconsistent.
Then hand me the list — don't try to fix anything yourself first.

All commands run from `backend/`.

---

## 1 · Match Player

```bash
python3 debug/test_player.py
MATCH_ID=69249 python3 debug/test_player.py   # test a different match
```

**What to check:**
- `Available matches` — are all 5+ matches listed? Are team names correct?
- `Duration` — should be ~90–95 min (5400–5700s). Anything outside that is suspicious.
- `First timestamp` should be `0.0s`. If not, period offset logic is broken.
- `Top event types` — Pass and Ball Receipt should dominate (~25–30% each). If Shot is #1, something is wrong.
- `First Shot details` — does it have `shot_outcome`, `xg`, `position`? Missing fields = parsing bug.
- `Clock` — "Advance ~2.0s game-time" will say WARN if fewer than 3 ticks fired (timing is loose on slow machines — OK to ignore if `ticks_received >= 2`).
- `Events emitted` — should be > 0 at 50× speed in 0.1s. Zero = clock or emitter broken.

**Red flags:** FileNotFoundError, 0 events loaded, duration > 7200s, timestamps jumping backwards.

---

## 2 · Match Analyser

```bash
python3 debug/test_analyser.py
```

**What to check:**
- `CRITICAL` count — expect 20–50 events per match (goals, shots, red cards). Zero = classifier broken.
- `NOTABLE` — expect 5–15% of all events.
- `ROUTINE` — should be the vast majority (85–90%+).
- Top 5 CRITICAL events — should all be Shots or cards. If you see `Pass` or `Carry` as CRITICAL, weights in `config.py` are wrong.
- `SequenceDetector patterns` — `possession_sequence` should be the most common by far. Zero patterns for 200 events = detector broken.
- `Score` after 500 events — verify it matches what you know about the match (Italy vs Turkey ends 3-0).
- `Possession %` — should not be exactly 50/50 after 500 real events. Exactly 50 = state not updating.
- `Momentum` — after 1000 events, one team should have >50. Exactly 50/50 = engine not accumulating.
- `xG` — should be > 0 if there were shots. Zero after 1000 events = xG not being read from details.
- `Spatial` samples — read the 5 descriptions. Do they make geographic sense for the coordinates?
- `Enrichment` — check stadium/city/date are correct for the match you know.

**Snapshots produced** (inspect manually if something looks wrong):
- `debug/snapshots/analyser_classification_3788741.json` — full list of CRITICAL events
- `debug/snapshots/analyser_state_3788741.json` — state dict at the 500-event mark

---

## 3 · Commentator

```bash
python3 debug/test_commentator.py
OLLAMA=1 python3 debug/test_commentator.py   # if Ollama is running
```

**What to check:**

*Prompts:*
- Does the `MATCH STATE` block in each prompt show real numbers (not all zeros)?
- Does the trigger event description make sense spatially? (e.g. "in the right side of the box" for a shot near goal)
- Is `RECENT COMMENTARY` showing `(none)` when no prior utterances exist? Good.
- Are the three agents getting meaningfully different system prompts? (PBP = energetic, Tactical = measured, Stats = factual)

*Fallback output:*
- PBP should name the player and location. Generic `"— event_type for team"` = fallback didn't match any condition.
- Tactical should reference the dominant team or a pattern. Generic "Both sides probing" every time = no patterns detected upstream.
- Stats should state a real number. "continue to press for the advantage" = no stats available in state.

*TTS:*
- Three WAV files created in `debug/snapshots/`. Listen to them:
  - `tts_play_by_play.wav` — should sound energetic (Fred / Piper lessac)
  - `tts_tactical.wav` — should sound measured (Daniel / Piper alan)
  - `tts_stats.wav` — should sound clear and concise (Samantha / Piper amy)
- Duration shown — each should be between 2–6s. > 6s = truncation not working.
- If backend shows `say` instead of `piper` — Piper isn't installed/found.

*Queue:*
- Drain order must always be `play_by_play → tactical → stats`. Any other order = priority bug.
- Overflow drop must keep size at exactly `MAX_AUDIO_QUEUE_SIZE` (3). Larger = drop logic broken.

*With Ollama (`OLLAMA=1`):*
- Each agent should return non-empty text within 8s.
- Text should be in present tense, under 35 words.
- Stats agent must contain a number. If it doesn't, prompt isn't constraining output enough.
- Check `debug/snapshots/commentator_llm_3788741.json` — look at raw text for hallucinations (invented player names, wrong scores, coordinates mentioned).

---

## 4 · Full stack (browser)

Start both servers:
```bash
# Terminal 1 — backend
cd backend && python3 main.py

# Terminal 2 — frontend
cd frontend && npm run dev
```

Open `http://localhost:5173` and observe:

**Match selection:**
- All matches listed? Team names correct?
- Personality dropdown showing all 5 options?

**During playback (speed 1×):**
- Clock advancing in the header?
- Events appearing in the Live tab?
- Commentary overlay appearing and fading after ~12s?
- Audio playing? (check browser console for Web Audio errors)
- Pitch markers appearing and fading?

**Controls:**
- Pause → clock stops, commentary stops, audio stops
- Resume → resumes from same position
- Seek (click waveform) → clock jumps, events replay from that point
- Speed 8× → commentary should become very sparse (PBP-only on critical events)
- Personality switch → system prompt changes, next utterance should sound different

**Backend logs to watch** (Terminal 1):
- `[DIRECTOR]` lines — shows which agent was selected and why
- `[PLAY_BY_PLAY]` / `[TACTICAL]` / `[STATS]` — shows generated text
- `[TTS]` — shows synthesis timing
- `[STATE]` — logs GOAL! when a goal is detected
- Any `ERROR` or `WARNING` lines

**Dev mode** (shows full pipeline):
```
http://localhost:5173?dev=true
```
Open the DevPanel (bottom right). For each commentary line you should see:
- Trigger event(s)
- Classification (CRITICAL / NOTABLE / ROUTINE / dead-air)
- Agent selected + reason
- 4 prompt layers
- LLM raw + cleaned output
- TTS backend, voice, duration
- End-to-end latency (ms)

---

## 5 · Quick per-match smoke test

```bash
for id in 3788741 3788768 3788769 69249 69251; do
  echo "--- $id ---"
  MATCH_ID=$id python3 debug/test_player.py 2>/dev/null | grep -E "(PASS|ERROR|WARNING|Duration|Total events)"
  MATCH_ID=$id python3 debug/test_analyser.py 2>/dev/null | grep -E "(PASS|ERROR|Score|CRITICAL)"
done
```

---

## 6 · What to note when compiling your bug list

For each issue, try to capture:
1. **Which subsystem** — player / analyser / commentator / director / frontend
2. **What you observed** — exact output, behaviour, or error
3. **When it happens** — always? only at certain speed? only on certain match? only after seek?
4. **Severity** — broken (nothing works), degraded (works but wrong), cosmetic

That structure lets me isolate the right module and fix exactly one thing at a time, as per CLAUDE.md.