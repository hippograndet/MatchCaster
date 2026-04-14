# backend/commentator/tts/voices.py
# Voice configuration mapping: agent_name → Piper voice model identifier.
# Also maps agent_name → macOS `say` voice (used when Piper is unavailable).

from config import PIPER_VOICES

# Re-export for convenience
AGENT_VOICES: dict[str, str] = PIPER_VOICES

# macOS built-in `say` voices — distinct enough to tell the three agents apart.
# Run `say -v ?` to see all available voices on your machine.
MACOS_SAY_VOICES: dict[str, str] = {
    "play_by_play": "Fred",      # American male
    "tactical":     "Daniel",    # British male, measured
    "stats":        "Samantha",  # American female, clear
}

# Piper voice model details for documentation/setup purposes
VOICE_INFO: dict[str, dict] = {
    "en_US-lessac-medium": {
        "description": "American English male, energetic, clear diction",
        "sample_rate": 22050,
        "gender": "male",
        "accent": "American",
    },
    "en_GB-alan-medium": {
        "description": "British English male, measured, authoritative",
        "sample_rate": 22050,
        "gender": "male",
        "accent": "British",
    },
    "en_US-amy-medium": {
        "description": "American English female, clear, professional",
        "sample_rate": 22050,
        "gender": "female",
        "accent": "American",
    },
}

# Fallback voice if primary is unavailable
FALLBACK_VOICE = "en_US-lessac-medium"

# Piper model download base URL
PIPER_MODEL_BASE_URL = "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0"

# Local model storage directory
PIPER_VOICES_DIR = "~/.local/share/piper-voices"


def get_voice_for_agent(agent_name: str) -> str:
    """Return the Piper voice model name for the given agent."""
    return AGENT_VOICES.get(agent_name, FALLBACK_VOICE)
