# backend/config.py
# All tunable constants for MatchCaster. Every other module imports from here.

# ---------------------------------------------------------------------------
# Replay
# ---------------------------------------------------------------------------
DEFAULT_SPEED_MULTIPLIER: float = 1.0       # 1× real time (default)
EVENT_BUFFER_LOOKAHEAD_SEC: float = 5.0     # Director looks ahead 5 match-seconds
MAX_CONCURRENT_AGENT_CALLS: int = 2          # Don't overload GPU

# ---------------------------------------------------------------------------
# Ollama
# ---------------------------------------------------------------------------
OLLAMA_BASE_URL: str = "http://localhost:11434"
OLLAMA_MODEL: str = "mistral:7b-instruct-q4_K_M"
OLLAMA_TIMEOUT_SEC: float = 45.0            # Covers cold model load (~6s) + generation
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
MAX_AUDIO_DURATION_SEC: float = 6.0          # Truncate TTS output longer than this

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

# Look-ahead batch window (game-seconds)
# Formula: clamp(22s * speed, min=30, max=90)
PBP_BATCH_WINDOW_MIN_SEC: float = 30.0   # minimum look-ahead (game-sec)
PBP_BATCH_WINDOW_MAX_SEC: float = 90.0   # maximum look-ahead (game-sec)
PBP_BATCH_REAL_BUDGET_SEC: float = 22.0  # target real-time budget for generation

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
import os as _os
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
# Routine event skip rate (director)
# ---------------------------------------------------------------------------
ROUTINE_SKIP_RATE: float = 0.9   # Skip 90% of routine pass/carry events

# ---------------------------------------------------------------------------
# Developer mode (never True in production)
# ---------------------------------------------------------------------------
DEV_MODE: bool = _os.getenv("DEV_MODE", "").lower() in ("1", "true", "yes")
