# MatchCaster — AI Football Commentary Engine

A fully local, multi-agent AI football commentary system. Replays real StatsBomb match data with live synthesized audio commentary from three distinct AI agents, displayed on an interactive pitch visualizer.

```
StatsBomb JSON → Replay Engine → Director → 3 LLM Agents (Ollama) → Piper TTS → Web Audio API
                                          ↘ Analysis Engine ↗
                                          → WebSocket → React Frontend
```

---

## Prerequisites

| Dependency | Version | Install |
|---|---|---|
| Python | 3.11+ | [python.org](https://python.org) |
| Node.js | 18+ | [nodejs.org](https://nodejs.org) |
| Ollama | latest | `brew install ollama` |
| Piper TTS | latest | Standalone binary — see Step 3 |

---

## Setup (one-time)

### 1. Start Ollama and pull the model

```bash
brew install ollama          # macOS
ollama serve &               # start in background (or open Ollama.app)
ollama pull mistral:7b-instruct-q4_K_M
```

### 2. Download match data

```bash
cd data
bash setup.sh
cd ..
```

This clones StatsBomb's open-data repository and copies the selected match files into `data/matches/` and `data/lineups/`.

### 3. Install Piper TTS (optional — for audio commentary)

> Text commentary works without Piper. Skip this step if you only want text.

```bash
cd /tmp

# macOS Apple Silicon (M1/M2/M3):
curl -L -o piper.tar.gz \
  https://github.com/rhasspy/piper/releases/download/2023.11.14-2/piper_macos_aarch64.tar.gz

# macOS Intel (x86_64):
# curl -L -o piper.tar.gz \
#   https://github.com/rhasspy/piper/releases/download/2023.11.14-2/piper_macos_x64.tar.gz

tar -xzf piper.tar.gz
mkdir -p ~/.local/share/piper
cp -r piper/* ~/.local/share/piper/

# Wrapper script — required to fix dylib paths on macOS
cat > ~/.local/share/piper/piper.sh << 'EOF'
#!/bin/bash
DIR="$(cd "$(dirname "$0")" && pwd)"
DYLD_LIBRARY_PATH="$DIR:$DYLD_LIBRARY_PATH" exec "$DIR/piper" "$@"
EOF
chmod +x ~/.local/share/piper/piper.sh
~/.local/share/piper/piper.sh --version   # should print version

# Download the three commentator voices
mkdir -p ~/.local/share/piper-voices
cd ~/.local/share/piper-voices

# Play-by-play (American male)
wget -q "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_US/lessac/medium/en_US-lessac-medium.onnx"
wget -q "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_US/lessac/medium/en_US-lessac-medium.onnx.json"

# Tactical analyst (British male)
wget -q "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_GB/alan/medium/en_GB-alan-medium.onnx"
wget -q "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_GB/alan/medium/en_GB-alan-medium.onnx.json"

# Stats analyst (American female)
wget -q "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_US/amy/medium/en_US-amy-medium.onnx"
wget -q "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_US/amy/medium/en_US-amy-medium.onnx.json"
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
./start.sh
```

This starts both the backend (port 8000) and frontend (port 5173) in a single terminal with color-coded logs. Press `Ctrl+C` to stop both.

Then open **[http://localhost:5173](http://localhost:5173)** in your browser.

> If you prefer to run them separately:
> ```bash
> # Terminal 1
> cd backend && python3 -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
>
> # Terminal 2
> cd frontend && npm run dev
> ```

---

## Using the app

1. **Select a match** — the launch screen appears automatically. Click a match, choose a commentary style, then click **Watch Live →**.

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
   - **Heatmap** — territory map for home or away team (adjust detail with slider)
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

```
backend/
├── config.py              All tunables
├── main.py                FastAPI app + HTTP routes
│
├── replay/
│   ├── clock.py           Async accelerated match clock (50 ms ticks)
│   ├── loader.py          StatsBomb JSON → MatchEvent dataclasses
│   └── emitter.py         Replay session management + seek support
│
├── director/
│   ├── classifier.py      Event priority: critical / notable / routine
│   ├── state.py           SharedMatchState (score, possession, stats)
│   └── router.py          Orchestrator: routes events → agents, manages gaps
│
├── agents/
│   ├── base.py            BaseAgent + Ollama streaming
│   ├── play_by_play.py    Live action narration
│   ├── tactical.py        Formations and patterns
│   └── stats.py           Stat facts
│
├── analysis/
│   └── engine.py          Real-time match analysis (momentum, xG, build-up vectors)
│
├── enrichment/
│   ├── match_meta.py      Stadium, date, manager lookup (StatsBomb match IDs)
│   ├── weather.py         Historical weather via Open-Meteo (no API key)
│   └── team_colors.py     Primary/secondary kit colors for ~40 teams
│
├── tts/
│   ├── engine.py          Piper TTS wrapper → WAV bytes
│   └── voices.py          Agent → voice model mapping
│
├── audio/
│   └── queue.py           Priority audio queue
│
└── ws/
    └── handler.py         WebSocket session: events, audio, state, seek

frontend/src/
├── App.tsx                Layout shell + state management
├── hooks/
│   ├── useWebSocket.ts    WS connection + message dispatch
│   └── useAudioPlayer.ts  Web Audio API queue + text/audio sync
├── utils/
│   ├── types.ts           TypeScript interfaces
│   └── pitchCoords.ts     StatsBomb → canvas coordinate mapping + pitch draw
└── components/
    ├── MatchSelectModal   Launch screen: match + commentary style picker
    ├── MatchHeader        Score, status, goal scorers, venue, weather
    ├── PitchCanvas        Canvas pitch: markers, trails, heatmap, shotmap, vectors
    ├── VideoControls      Seek bar, ±10/30s, speed, mute, settings
    ├── OverlayPanel       Floating pitch view/settings panel
    ├── SidebarTabs        Stats / Live events / Squad tabs
    └── CommentaryOverlay  Glass commentary bubble on pitch
```

---

## Configuration

All tunables live in `backend/config.py`:

| Key | Default | Description |
|---|---|---|
| `DEFAULT_SPEED_MULTIPLIER` | `1.0` | Replay speed on startup |
| `OLLAMA_MODEL` | `mistral:7b-instruct-q4_K_M` | LLM model |
| `OLLAMA_TIMEOUT_SEC` | `8.0` | Kill slow LLM generations |
| `MAX_OUTPUT_TOKENS` | `80` | Hard token cap per commentary line |
| `MIN_GAP_GAME_SEC` | `6.0` | Minimum silence between utterances (game-time seconds) |
| `DEAD_AIR_GAME_SEC` | `12.0` | Trigger fill commentary after this silence |

---

## Graceful degradation

| Failure | Fallback |
|---|---|
| Ollama offline / slow | Template commentary ("Shot from X — saved") |
| Piper TTS missing | Text-only commentary, no audio |
| Audio queue overflow | Oldest items dropped |
| WebSocket disconnect | Auto-reconnect after 2 s |
| Unknown match ID | No metadata shown, colors use defaults |
