# backend/commentator/tts/voices.py
# Voice configuration for MatchCaster TTS.
# Primary backend: kokoro-onnx (see engine.py for voice → agent mapping).
# Fallback: macOS `say` built-in voices.

from config import PIPER_VOICES

# Re-export for any legacy callers
AGENT_VOICES: dict[str, str] = PIPER_VOICES

# macOS built-in `say` voices — used when kokoro model files are not present.
# Run `say -v ?` to see all available voices on your machine.
MACOS_SAY_VOICES: dict[str, str] = {
    "play_by_play": "Fred",      # American male — energetic PBP
    "analyst":      "Daniel",    # British male — measured expert analyst
    # Legacy names
    "tactical":     "Daniel",
    "stats":        "Samantha",
}

# Legacy constants kept for import compatibility
FALLBACK_VOICE = "en_US-lessac-medium"
PIPER_VOICES_DIR = "~/.local/share/piper-voices"
PIPER_MODEL_BASE_URL = "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0"


def get_voice_for_agent(agent_name: str) -> str:
    """Return the Piper voice model name for the given agent (legacy)."""
    return AGENT_VOICES.get(agent_name, FALLBACK_VOICE)
