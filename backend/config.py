# backend/config.py
# All tunable constants for MatchCaster. Every other module imports from here.

import os as _os

# ---------------------------------------------------------------------------
# Replay
# ---------------------------------------------------------------------------
DEFAULT_SPEED_MULTIPLIER: float = 1.0       # 1× real time (default)
EVENT_BUFFER_LOOKAHEAD_SEC: float = 5.0     # Director looks ahead 5 match-seconds
MAX_CONCURRENT_AGENT_CALLS: int = 1          # CPU-only: serial calls prevent thread contention

# ---------------------------------------------------------------------------
# LLM backend selection
# ---------------------------------------------------------------------------
LLM_BACKEND: str = _os.getenv("LLM_BACKEND", "groq")   # "groq" | "local"

# Groq (cloud, fast, free tier)
GROQ_API_KEY: str = _os.getenv("GROQ_API_KEY", "")
GROQ_MODEL: str = "llama-3.1-8b-instant"
GROQ_BASE_URL: str = "https://api.groq.com/openai/v1"

# Compact prompts for local Ollama (removes style examples to reduce prefill tokens)
COMPACT_PROMPTS: bool = LLM_BACKEND == "local"

# ---------------------------------------------------------------------------
# Ollama (used when LLM_BACKEND=local)
# ---------------------------------------------------------------------------
OLLAMA_BASE_URL: str = "http://localhost:11434"
OLLAMA_MODEL: str = "gemma2:2b-instruct-q4_K_M"
OLLAMA_TIMEOUT_SEC: float = 90.0
MAX_OUTPUT_TOKENS: int = 50                 # Keep commentary lines SHORT (~35 words max)

AGENT_TEMPERATURES: dict[str, float] = {
    "play_by_play": 0.8,  # Creative, energetic
    "tactical": 0.5,       # Measured
    "stats": 0.4,          # Factual
}

# ---------------------------------------------------------------------------
# TTS
# ---------------------------------------------------------------------------
PIPER_VOICES: dict[str, str] = {
    "play_by_play": "en_US-lessac-medium",   # Energetic American male — PBP
    "analyst":      "en_GB-alan-medium",      # Measured British analyst
    # Legacy aliases
    "tactical":     "en_GB-alan-medium",
    "stats":        "en_US-amy-medium",
}
MAX_AUDIO_DURATION_SEC: float = 10.0         # Truncate TTS output longer than this (raised for flow blocks)

# ---------------------------------------------------------------------------
# Director priority weights
# ---------------------------------------------------------------------------
PRIORITY_WEIGHTS: dict[str, int] = {
    "goal":         100,
    "shot":          80,
    "red_card":      90,
    "yellow_card":   50,
    "substitution":  40,
    "foul":          30,
    "pass":           5,
    "carry":          3,
    "pressure":      10,
    "dribble":       20,
    "interception":  25,
    "clearance":     15,
    "block":         20,
    "keeper":        35,
}

# ---------------------------------------------------------------------------
# Agent turn policy
# ---------------------------------------------------------------------------
PBP_PRIORITY: int = 1       # Highest — speaks during action
ANALYST_PRIORITY: int = 2   # Expert analyst (merged tactical + stats)

# Time-block PBP — replaces the old per-event batch system
PBP_BLOCK_DURATION_GAME_SEC: float = 15.0   # game-sec per block at 1× speed (scales with speed)
PBP_BLOCKS_AHEAD: int = 4                    # how many blocks to keep pre-generated ahead
PBP_BLOCK_MAX_AUDIO_SEC: float = 10.0        # TTS duration cap for flow blocks
PBP_BLOCK_MAX_WORDS: int = 25               # target word budget per block
# Kept for Ollama generation time budget guard (used in _compute_block_duration)
PBP_BATCH_REAL_BUDGET_SEC: float = 22.0

# Analyst scheduling
ANALYST_MIN_GAP_GAME_SEC: float = 300.0   # 5 game-minutes minimum between timer firings
ANALYST_MAX_GAP_GAME_SEC: float = 420.0   # 7 game-minutes maximum
ANALYST_BLOCK_FIRST_SEC: float = 300.0    # blocked for first 5 game-minutes of play
GOAL_ANALYST_COOLDOWN_SEC: float = 120.0  # analyst blocked 2 game-min after goal

# Max notable events sent to LLM per batch (to keep prompt concise)
MAX_EVENTS_PER_BATCH: int = 8

# ---------------------------------------------------------------------------
# Audio queue
# ---------------------------------------------------------------------------
MAX_AUDIO_QUEUE_SIZE: int = 3   # Drop stale items beyond this

# ---------------------------------------------------------------------------
# Data paths (relative to repo root, i.e. one level above backend/)
# ---------------------------------------------------------------------------
_BACKEND_DIR = _os.path.dirname(_os.path.abspath(__file__))
_ROOT_DIR = _os.path.dirname(_BACKEND_DIR)

DATA_DIR: str = _os.path.join(_ROOT_DIR, "data")
MATCHES_DIR: str = _os.path.join(_ROOT_DIR, "data", "matches")
LINEUPS_DIR: str = _os.path.join(_ROOT_DIR, "data", "lineups")

# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------
HOST: str = "0.0.0.0"
PORT: int = 8000

# ---------------------------------------------------------------------------
# Routine event skip rate (legacy — no longer used in time-block PBP)
# ---------------------------------------------------------------------------
# ROUTINE_SKIP_RATE was 0.9 (skip 90% of routine events). Removed: time-block
# generation passes ALL events to the LLM for narrative context.

# ---------------------------------------------------------------------------
# Developer mode (never True in production)
# ---------------------------------------------------------------------------
DEV_MODE: bool = _os.getenv("DEV_MODE", "").lower() in ("1", "true", "yes")
