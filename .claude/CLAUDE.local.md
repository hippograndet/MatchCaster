## General Architecture
This project is split into isolated subsystems. Each folder under `backend/` is a self-contained module. Respect those boundaries — don't create cross-dependencies unless explicitly discussed.

# Project Architecture Reference

## What it is
Fully local, multi-agent AI football commentary engine. Replays real StatsBomb match data through a controllable clock, classifies events in real-time, generates two-commentator live audio (LLM + TTS), and visualises everything on a React pitch canvas. No cloud APIs — Ollama + Kokoro ONNX only.

## System map (data flows top → bottom)

```
StatsBomb JSON
    ↓
backend/player/       Clock + event loader + SSE emitter
    ↓  MatchEvent stream
backend/analyser/     Classifier, SharedMatchState, AnalysisEngine, spatial, enrichment
    ↓  SharedMatchState + AnalysisSnapshot
backend/director/     Batch scheduler + analyst scheduler + dynamic speed control
    ↓  triggers agents
backend/commentator/  LLM (Ollama) → CommentaryLine list → TTS (Kokoro) → WAV bytes
    ↓  EventTaggedQueue + AudioQueue
backend/ws/           MatchSession — broadcasts events, audio, state over WebSocket
    ↓  JSON messages
frontend/             React canvas, controls, commentary overlay, sidebar
```

## Compartments — key files and roles

### `backend/player/`
| File | Role |
|---|---|
| `loader.py` | `load_events(match_id)→list[MatchEvent]`; pre-computes goal timeline + 5-min state snapshots (for seek) |
| `clock.py` | `MatchClock`: 50 ms asyncio tick loop, speed 0.1×–50×; `register_tick(cb)` |
| `emitter.py` | `ReplaySession`: emits events with `timestamp_sec ≤ match_time` each tick; SSE routes `/api/events/stream`, `/api/replay/control`, `/api/matches` |

`MatchEvent` fields: `id, timestamp_sec, event_type, team, player, position(x,y), end_position, details(dict), priority, detected_patterns, index`

### `backend/analyser/`
| File | Role |
|---|---|
| `classifier.py` | `classify(event)→"critical/notable/routine"` via priority weights; `SequenceDetector` finds 4 patterns in 15 s window |
| `state.py` | `SharedMatchState`: accumulates `TeamStats` (shots, xG, cards, fouls), phase, utterances; `reset_to_snapshot()` for seek |
| `engine.py` | `MatchAnalysisEngine`: momentum (3 game-min decay), xG, box entries, 6×4 build-up grid → `AnalysisSnapshot` with 4 text contexts (instant/short/long/totals) |
| `spatial.py` | StatsBomb (x,y) → natural language zone description |
| `enrichment/` | Hardcoded match metadata, team kit colors, Open-Meteo weather |

Priority weights: `goal=100, red_card=90, shot=80, keeper=35, yellow_card=50, sub=40, foul=30, pass=5, carry=3`

### `backend/director/`
Single file: `router.py` — `Director` class with two background asyncio loops:
- **Batch scheduler** (0.3 s real): look-ahead window = `clamp(22 s × speed, 30–90 game-s)` → collects ≤8 CRITICAL/NOTABLE events → `PlayByPlayAgent.generate_batch()` → TTS → `EventTaggedQueue`
- **Analyst scheduler** (1 s real): fires on timer (5–7 game-min gap), substitution, post-goal (2-min cooldown), half-time

Dynamic speed overrides: goal → halve speed 20 s; counter-attack → halve speed 8 s. `speed_cb` notifies `MatchSession`.

On each event arrival: `dispatch_for_event(event)` pops pre-generated line from `EventTaggedQueue` → `AudioQueue`.

### `backend/commentator/`
| File | Role |
|---|---|
| `agents/play_by_play.py` | Batched LLM call → JSON array of event-tagged lines (35-word cap, temp 0.8) |
| `agents/analyst.py` | Single plain-text insight (40-word cap, temp 0.5); triggers: timer/goal/sub/halftime |
| `agents/prompts.py` | All prompt builders + 5 personality modifiers (neutral/enthusiastic/analytical/home_bias/away_bias) |
| `agents/base.py` | `BaseAgent` ABC: Ollama HTTP streaming, template fallback, trace support |
| `tts/engine.py` | `PiperTTSEngine`: primary=kokoro-onnx (`am_adam`/`bm_george`), fallback=macOS `say`; WAV capped at 6 s |
| `tts/voices.py` | Agent name → voice + speed mapping |
| `queue.py` | `EventTaggedQueue` (dict by event_id); `AudioQueue` (priority: PBP=1, analyst=2, max 3 items) |

LLM: `mistral:7b-instruct-q4_K_M` via Ollama at `http://localhost:11434`. `MAX_OUTPUT_TOKENS=50`.

### `backend/ws/`
`handler.py` — `MatchSession` (one per match): holds Director, AudioQueue, EventTaggedQueue, SharedMatchState, ReplaySession; multi-client broadcast.

Three background tasks:
- `_event_consumer`: batches events → `director.process_events()` → `dispatch_for_event()`
- `_audio_pump`: drains AudioQueue → base64 WAV → `audio` WS message
- `_clock_broadcast`: `clock` message every 0.5 s; `analysis` snapshot every 5 s

**Seek** (most complex): pause → `replay_session.seek(t)` → flush queues → reset analysis → restore from nearest 5-min snapshot + fast-replay events to `t` → broadcast → resume.

WS endpoint: `ws://localhost:8000/ws/match?match_id=...`

Client→server actions: `play | pause | seek | set_speed | set_personality | reset | force_commentary`
Server→client types: `state | clock | event | audio | match_end | ping | error | debug`

`audio` message shape: `{type, agent, text, match_time, audio_b64 (base64 WAV), audio_format: "wav"}`

### `backend/main.py` — HTTP routes
`GET /api/matches`, `GET /api/lineup/{match_id}`, `GET /api/match_summary/{match_id}`,
`GET|POST|DELETE /api/dev/*` (DEV_MODE only), `GET /health`

### `frontend/src/`
| File | Role |
|---|---|
| `App.tsx` | Root: all state, event→visual mapping (markers, possession trail, heatmap, danger zones) |
| `components/PitchCanvas.tsx` | Canvas: pitch → markers → possession trail → formation → heatmap → shotmap → vectors |
| `components/VideoControls.tsx` | Waveform seek bar (home↑/away↓), playback buttons, speed, overlay toggles |
| `components/CommentaryOverlay.tsx` | Glass-morphism text + speaking-bar animation; 12 s visible, fades at 18 s |
| `components/SidebarTabs.tsx` | Stats / Live feed / Squad tabs |
| `components/OverlayPanel.tsx` | Heatmap, formation, shots, vectors, personality settings |
| `components/DevPanel.tsx` | Dev-only (`?dev=true`): traces, config inspector, prompt overrides |
| `hooks/useWebSocket.ts` | WS client, 2 s reconnect, all reactive match state |
| `hooks/useAudioPlayer.ts` | base64 WAV → AudioBuffer → sequential queue (150 ms gap); callback fires on track START |
| `utils/pitchCoords.ts` | `sbToCanvas()`: StatsBomb origin (bottom-left) → canvas (top-left), Y flipped |
| `utils/types.ts` | All TypeScript interfaces: `MatchState`, `MatchEventData`, `PossessionSegment`, `PipelineTrace`, etc. |

Possession trail visual speeds (fixed, independent of match speed): `pass=55 u/s, carry=7 u/s, dribble=5 u/s, shot=120 u/s`. Heatmap: 24×16 grid per team.

### `backend/debug/`
- `test_player.py`, `test_analyser.py`, `test_commentator.py` — standalone scripts, no server needed
- `debug/snapshots/` — JSON dumps between subsystems (match_id-keyed); WAV samples
- `override.py` — `OverrideStore`: one-shot custom prompt injection for dev UI

## Key config knobs (`backend/config.py`)
```
OLLAMA_MODEL          mistral:7b-instruct-q4_K_M
OLLAMA_TIMEOUT_SEC    45.0      ← increase if Ollama is slow
MAX_OUTPUT_TOKENS     50        ← keep short; affects commentary length
PBP_BATCH_WINDOW_*    30–90 s   ← look-ahead range (game-seconds)
PBP_BATCH_REAL_BUDGET_SEC 22   ← target generation budget (real-seconds)
MAX_EVENTS_PER_BATCH  8         ← LLM prompt size cap
ANALYST_MIN/MAX_GAP   300–420 s ← analyst frequency
GOAL_ANALYST_COOLDOWN 120 s
MAX_AUDIO_DURATION_SEC 6.0      ← WAV length cap
ROUTINE_SKIP_RATE     0.9       ← skip 90% of routine events
MAX_AUDIO_QUEUE_SIZE  3
DEV_MODE              env DEV_MODE=1
```

## Data dir
`data/matches/*.json` + `data/lineups/*.json` — StatsBomb open data (9 matches).
Match IDs currently available: 3788741 (UEFA Euro 2020), others from Euro 2020 + WC 2018 + La Liga.

## Entry point
`./start.sh` → Ollama check → `uvicorn main:app` on :8000 → `npm run dev` on :5173