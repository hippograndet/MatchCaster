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
OLLAMA_TIMEOUT_SEC: float = 8.0             # Kill slow generations
MAX_OUTPUT_TOKENS: int = 80                 # Keep commentary lines SHORT

AGENT_TEMPERATURES: dict = {
    "play_by_play": 0.8,  # Creative, energetic
    "tactical": 0.5,       # Measured
    "stats": 0.4,          # Factual
}

# ---------------------------------------------------------------------------
# TTS
# ---------------------------------------------------------------------------
PIPER_VOICES: dict = {
    "play_by_play": "en_US-lessac-medium",   # Energetic male voice
    "tactical":     "en_GB-alan-medium",      # Measured British analyst
    "stats":        "en_US-amy-medium",       # Clear, concise female voice
}
MAX_AUDIO_DURATION_SEC: float = 6.0          # Truncate TTS output longer than this

# ---------------------------------------------------------------------------
# Director priority weights
# ---------------------------------------------------------------------------
PRIORITY_WEIGHTS: dict = {
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
PBP_PRIORITY: int = 1     # Highest — speaks during action
TACTICAL_PRIORITY: int = 2
STATS_PRIORITY: int = 3
MIN_GAP_GAME_SEC: float = 6.0                  # Minimum game-seconds between utterances (speed-adjusted)
DEAD_AIR_GAME_SEC: float = 12.0               # Dead-air filler triggers after this many game-seconds of silence
MIN_GAP_BETWEEN_UTTERANCES_SEC: float = 1.5   # Legacy alias — kept for reference
DEAD_AIR_THRESHOLD_SEC: float = 5.0            # Legacy alias

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
