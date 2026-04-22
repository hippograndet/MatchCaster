# MatchCaster — AI Football Commentary Engine

A multi-agent AI football commentary system. Replays real StatsBomb match data with live synthesized audio commentary from two AI commentators, displayed on an interactive pitch visualizer.

```
StatsBomb JSON → Replay Engine → Director (look-ahead batch) → LLM (Groq API or Ollama)
                                                              → Kokoro/Piper TTS
                               → Analysis Engine
                               → WebSocket → React Frontend
```

---

## LLM Backend

MatchCaster supports two commentary backends, selected at startup:

### Cloud — Groq API (default, recommended)

Fast cloud inference (~400 tok/s). Free tier available. Requires an internet connection.

```bash
# 1. Get a free API key at https://console.groq.com
export GROQ_API_KEY=...

# 2. Start (Groq is the default)
./start.sh
# or explicitly:
./start.sh groq
```

> Commentary blocks generate in ~2 seconds with Groq. No model download required.

### Local — Ollama (offline)

Runs entirely on your machine. Requires a capable CPU/GPU. Slower on older Intel Macs (~20–30 s per block).

```bash
# 1. Install Ollama
brew install ollama

# 2. Pull the model
ollama pull gemma2:2b-instruct-q4_K_M

# 3. Start in local mode
./start.sh local
```

> Note: On Intel Macs (no Metal/GPU), generation may lag behind real-time play at 1× speed. Use 0.5× speed or lower for smooth commentary.

---

## Prerequisites

| Dependency | Version | Install |
|---|---|---|
| Python | 3.11+ | [python.org](https://python.org) |
| Node.js | 18+ | [nodejs.org](https://nodejs.org) |
| Ollama | latest | `brew install ollama` — only required for `./start.sh local` |
| Piper TTS | 2023.11.14-2 | Standalone bundle — see Step 3 |

---

## Setup (one-time)

### 1. Choose your LLM backend

See the [LLM Backend](#llm-backend) section above. For the quickest setup, use Groq (cloud) — just export your key and skip Ollama entirely.

### 2. Download match data

```bash
cd data
bash setup.sh
cd ..
```

Clones StatsBomb's open-data repository and copies match files into `data/matches/` and `data/lineups/`.

### 3. Download Kokoro TTS model files (optional — for higher-quality audio commentary)

> Without Kokoro, MatchCaster falls back to the macOS built-in `say` command automatically. Commentary still plays — just with system voices. Skip to Step 4 if you want to get started quickly.

MatchCaster uses **kokoro-onnx** for neural TTS (installed automatically via `pip install -r requirements.txt` in Step 4). It works on Python 3.13 and requires no binary — just two model files to download:

```bash
mkdir -p ~/.local/share/kokoro
cd ~/.local/share/kokoro

curl -L -o kokoro-v1.0.onnx \
  "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx"

curl -L -o voices-v1.0.bin \
  "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin"
```

| Voice | Agent | Character |
|---|---|---|
| `am_adam` | Play-by-play | American male, energetic |
| `bm_george` | Analyst | British male, measured |

#### Verify:

```bash
python3 -c "
from kokoro_onnx import Kokoro
import subprocess, wave, io, numpy as np
k = Kokoro(
    model_path='$HOME/.local/share/kokoro/kokoro-v1.0.onnx',
    voices_path='$HOME/.local/share/kokoro/voices-v1.0.bin',
)
samples, sr = k.create('And we are off!', voice='am_adam', speed=1.1, lang='en-us')
pcm = (np.clip(samples, -1, 1) * 32767).astype(np.int16)
buf = io.BytesIO()
with wave.open(buf, 'wb') as wf:
    wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(sr); wf.writeframes(pcm.tobytes())
subprocess.run(['afplay', '-'], input=buf.getvalue())
print('Kokoro OK')
"
```

### 4. Install dependencies

```bash
# Backend
cd backend && pip install -r requirements.txt && cd ..

# Frontend
cd frontend && npm install && cd ..
```

---

## Running the app

```bash
./start.sh          # Groq cloud (default) — requires GROQ_API_KEY
./start.sh groq     # same as above, explicit
./start.sh local    # Ollama offline — requires model pulled
```

Starts both the backend (port 8000) and frontend (port 5173). Press `Ctrl+C` to stop.

Open **[http://localhost:5173](http://localhost:5173)** in your browser.

> Run separately if preferred:
> ```bash
> # Terminal 1
> cd backend && python3 -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
>
> # Terminal 2
> cd frontend && npm run dev
> ```

---

## Using the app

1. **Select a match** — the launch screen appears automatically. Pick a match, choose a commentary style, then click **Watch Live →**.

2. **Controls** — the video player bar at the bottom:
   - `▶ / ⏸` — play and pause
   - `−30s` `−10s` `+10s` `+30s` — jump backward or forward
   - Click the **seek bar** to jump to any point in the match
   - Speed buttons `0.5× 1× 2× 4× 8×` — control replay speed
   - `🔊` — mute/unmute audio commentary
   - `⚙` — open the **Overlay Panel** (pitch view and settings)
   - **Change** — go back to the match selection screen

3. **Overlay Panel** (opened with `⚙`):
   - **Live** — real-time event markers and pass trails on the pitch
   - **Formation** — starting lineup with jersey numbers and player names
   - **Heatmap** — territory map for home or away team
   - **Shots** — all shot locations, sized by xG, colored by outcome
   - **Build-up** — directional pass flow arrows by zone

4. **Sidebar tabs**:
   - **Stats** — momentum bar, possession, shots, xG, passes, fouls, cards
   - **Live** — key events feed (goals, cards, big chances) or full event log
   - **Squad** — starting lineup with positions and goal contributions

5. **Commentary styles**:
   | Style | Character |
   |---|---|
   | 🎙 Neutral | Balanced, professional |
   | 🔥 Enthusiastic | High energy, emotional |
   | 📐 Analytical | Tactical depth, data-driven |
   | 🏠 Home Fan | Biased toward the home side |
   | ✈️ Away Fan | Biased toward the away side |

---

## Architecture

### Commentary System

MatchCaster uses a two-commentator look-ahead batch system:

1. The **Director** pre-generates commentary for the next 30 game-seconds of upcoming events (before they happen on the pitch).
2. Each line is tagged to a specific event ID and TTS audio is synthesized in advance.
3. When an event fires on the pitch, its pre-synthesized audio plays immediately — perfectly synced.

**Play-by-Play commentator** — narrates the action. Fires every 30 game-seconds. Receives analyst context to weave into narration. Handles the opening scene-setter.

**Analyst commentator** — expert macro insights. Fires every 5-7 game-minutes, on substitutions, and 2 minutes after goals. Silent during the first 5 minutes (PBP owns the opening). Feeds context back to PBP.

### File Structure

```
backend/
├── config.py                All tunables
├── main.py                  FastAPI app + HTTP routes
│
├── player/
│   ├── clock.py             Async accelerated match clock (50 ms ticks)
│   ├── loader.py            StatsBomb JSON → MatchEvent dataclasses
│   └── emitter.py           Replay session management + seek support
│
├── analyser/
│   ├── classifier.py        Event priority: critical / notable / routine
│   ├── state.py             SharedMatchState (score, possession, stats)
│   ├── engine.py            Real-time match analysis (momentum, xG, vectors)
│   ├── spatial.py           Coordinate → pitch zone descriptions
│   └── enrichment/
│       ├── match_meta.py    Stadium, date, manager lookup
│       ├── weather.py       Historical weather via Open-Meteo
│       └── team_colors.py   Kit colors for ~40 teams
│
├── director/
│   └── router.py            Orchestrator: look-ahead batch scheduler,
│                            analyst scheduler, event dispatch
│
├── commentator/
│   ├── agents/
│   │   ├── base.py          BaseAgent ABC + prompt assembly
│   │   ├── play_by_play.py  Live action narration (batch JSON output)
│   │   ├── analyst.py       Expert macro commentary (replaces tactical+stats)
│   │   └── prompts.py       System prompts + user prompt builders
│   ├── llm/
│   │   ├── __init__.py      Backend singleton (get_backend / init_backend)
│   │   ├── backend.py       LLMBackend ABC
│   │   ├── groq.py          Groq cloud backend (OpenAI-compatible SSE)
│   │   └── ollama.py        Ollama local backend
│   ├── tts/
│   │   ├── engine.py        Piper TTS wrapper → WAV bytes (+ macOS say fallback)
│   │   └── voices.py        Agent → voice model mapping
│   └── queue.py             AudioQueue + EventTaggedQueue (event-ID dispatch)
│
└── ws/
    └── handler.py           WebSocket session: events, audio, state, seek
```

---

## Configuration

All tunables live in `backend/config.py`:

| Key | Default | Description |
|---|---|---|
| `DEFAULT_SPEED_MULTIPLIER` | `1.0` | Replay speed on startup |
| `LLM_BACKEND` | `groq` | `"groq"` (cloud) or `"local"` (Ollama) |
| `GROQ_MODEL` | `llama-3.1-8b-instant` | Groq model |
| `OLLAMA_MODEL` | `gemma2:2b-instruct-q4_K_M` | Ollama model (local mode only) |
| `OLLAMA_TIMEOUT_SEC` | `90.0` | Per-call timeout for Ollama streaming |
| `MAX_OUTPUT_TOKENS` | `50` | Hard token cap per commentary batch |
| `PBP_BATCH_WINDOW_MIN_SEC` | `30.0` | Minimum look-ahead window (game-sec) |
| `PBP_BATCH_WINDOW_MAX_SEC` | `90.0` | Maximum look-ahead window at high speed |
| `ANALYST_MIN_GAP_GAME_SEC` | `300.0` | Minimum silence between analyst firings |
| `ANALYST_BLOCK_FIRST_SEC` | `300.0` | Analyst blocked for first 5 game-minutes |
| `GOAL_ANALYST_COOLDOWN_SEC` | `120.0` | Analyst cooldown after a goal |
| `MAX_EVENTS_PER_BATCH` | `8` | Max events sent to LLM per batch |

---

## Graceful degradation

| Failure | Fallback |
|---|---|
| LLM unavailable / slow | Template commentary ("Shot — great save!") |
| Piper TTS not installed | macOS `say` built-in voices |
| Piper TTS crashes | macOS `say` built-in voices |
| Audio queue overflow | Oldest items dropped |
| WebSocket disconnect | Auto-reconnect after 2 s |
| Unknown match ID | No metadata shown, colors use defaults |
