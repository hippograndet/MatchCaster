# backend/commentator/tts/engine.py
# TTS wrapper: text → WAV bytes, with voice selection and duration cap.
#
# Primary backend: kokoro-onnx (pip install kokoro-onnx)
#   - High-quality neural TTS, Python 3.13 compatible, no binary required
#   - Model files: ~/.local/share/kokoro/kokoro-v1.0.onnx + voices-v1.0.bin
# Fallback: macOS built-in `say` command

from __future__ import annotations

import asyncio
import functools
import io
import logging
import os
import struct
import subprocess
import tempfile
import wave
from pathlib import Path
from typing import Optional

from config import MAX_AUDIO_DURATION_SEC
from commentator.tts.voices import MACOS_SAY_VOICES

logger = logging.getLogger("[TTS]")

# ---------------------------------------------------------------------------
# Kokoro model paths
# ---------------------------------------------------------------------------

KOKORO_DIR = Path(os.path.expanduser("~/.local/share/kokoro"))
KOKORO_MODEL = KOKORO_DIR / "kokoro-v1.0.onnx"
KOKORO_VOICES = KOKORO_DIR / "voices-v1.0.bin"

# Voice mapping: agent name → kokoro voice ID
KOKORO_AGENT_VOICES: dict[str, str] = {
    "play_by_play": "am_adam",    # American male, energetic
    "analyst":      "bm_george",  # British male, measured
    # Legacy aliases
    "tactical":     "bm_george",
    "stats":        "am_adam",
}

# Speed tuning per agent (kokoro accepts 0.5–2.0)
KOKORO_AGENT_SPEED: dict[str, float] = {
    "play_by_play": 1.1,   # Slightly faster — live action energy
    "analyst":      1.0,   # Natural pace
}


# ---------------------------------------------------------------------------
# Kokoro backend
# ---------------------------------------------------------------------------

def _kokoro_available() -> bool:
    if not (KOKORO_MODEL.exists() and KOKORO_VOICES.exists()):
        return False
    try:
        import kokoro_onnx  # noqa: F401
        return True
    except ImportError:
        return False


def _samples_to_wav(samples, sample_rate: int) -> bytes:
    """Convert float32 numpy samples to 16-bit WAV bytes."""
    import numpy as np
    pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm.tobytes())
    return buf.getvalue()


class _KokoroEngine:
    """Lazy-loaded singleton wrapper around kokoro_onnx.Kokoro."""

    def __init__(self) -> None:
        self._kokoro = None

    def _load(self):
        if self._kokoro is None:
            from kokoro_onnx import Kokoro
            self._kokoro = Kokoro(
                model_path=str(KOKORO_MODEL),
                voices_path=str(KOKORO_VOICES),
            )
            logger.info("Kokoro model loaded")
        return self._kokoro

    def synthesize(self, text: str, agent_name: str) -> Optional[bytes]:
        try:
            k = self._load()
            voice = KOKORO_AGENT_VOICES.get(agent_name, "am_adam")
            speed = KOKORO_AGENT_SPEED.get(agent_name, 1.0)
            lang = "en-gb" if voice.startswith("b") else "en-us"
            samples, sr = k.create(text, voice=voice, speed=speed, lang=lang)
            wav = _samples_to_wav(samples, sr)
            return _truncate_wav(wav, MAX_AUDIO_DURATION_SEC)
        except Exception as exc:
            logger.error(f"Kokoro synthesis error: {exc}")
            return None


_kokoro_engine: Optional[_KokoroEngine] = None


def _get_kokoro() -> _KokoroEngine:
    global _kokoro_engine
    if _kokoro_engine is None:
        _kokoro_engine = _KokoroEngine()
    return _kokoro_engine


# ---------------------------------------------------------------------------
# macOS `say` fallback
# ---------------------------------------------------------------------------

def _which(cmd: str) -> Optional[str]:
    try:
        r = subprocess.run(["which", cmd], capture_output=True, text=True)
        return r.stdout.strip() if r.returncode == 0 else None
    except Exception:
        return None


def _say_available() -> bool:
    return _which("say") is not None


def _synthesize_say(text: str, voice: str) -> Optional[bytes]:
    if not text.strip():
        return None
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            aiff = os.path.join(tmpdir, "out.aiff")
            wav = os.path.join(tmpdir, "out.wav")

            r = subprocess.run(["say", "-v", voice, "-o", aiff, text],
                               capture_output=True, timeout=15.0)
            if r.returncode != 0 or not os.path.exists(aiff):
                logger.error(f"say failed: {r.stderr.decode()[:100]}")
                return None

            r2 = subprocess.run(
                ["afconvert", "-f", "WAVE", "-d", "LEI16@22050", "-c", "1", aiff, wav],
                capture_output=True, timeout=10.0,
            )
            if r2.returncode != 0 or not os.path.exists(wav):
                logger.error(f"afconvert failed: {r2.stderr.decode()[:100]}")
                return None

            with open(wav, "rb") as f:
                wav_bytes = f.read()

        return _truncate_wav(wav_bytes, MAX_AUDIO_DURATION_SEC)
    except subprocess.TimeoutExpired:
        logger.warning(f"say timed out: {text[:50]!r}")
        return None
    except Exception as exc:
        logger.error(f"say error: {exc}")
        return None


# ---------------------------------------------------------------------------
# WAV utilities
# ---------------------------------------------------------------------------

def _truncate_wav(wav_bytes: bytes, max_seconds: float) -> bytes:
    """Truncate WAV to max_seconds. Returns corrected WAV bytes."""
    if len(wav_bytes) < 44:
        return wav_bytes
    try:
        riff, _, wavhdr = struct.unpack_from("<4sI4s", wav_bytes, 0)
        if riff != b"RIFF" or wavhdr != b"WAVE":
            return wav_bytes

        offset = 12
        sample_rate, num_channels, bits_per_sample = 22050, 1, 16
        data_start, data_size = 44, len(wav_bytes) - 44

        while offset < len(wav_bytes) - 8:
            chunk_id = wav_bytes[offset:offset + 4]
            chunk_size = struct.unpack_from("<I", wav_bytes, offset + 4)[0]
            if chunk_id == b"fmt ":
                _, num_channels, sample_rate, _, _, bits_per_sample = \
                    struct.unpack_from("<HHIIHH", wav_bytes, offset + 8)
            elif chunk_id == b"data":
                data_start = offset + 8
                data_size = chunk_size
                break
            offset += 8 + chunk_size

        max_bytes = int(max_seconds * sample_rate * num_channels) * (bits_per_sample // 8)
        if data_size <= max_bytes:
            return wav_bytes

        trunc = min(max_bytes, data_size)
        trunc -= trunc % (num_channels * (bits_per_sample // 8))
        header = bytearray(wav_bytes[:data_start])
        struct.pack_into("<I", header, data_start - 4, trunc)
        struct.pack_into("<I", header, 4, data_start - 8 + trunc)
        return bytes(header) + wav_bytes[data_start:data_start + trunc]

    except (struct.error, IndexError) as exc:
        logger.warning(f"WAV truncation failed: {exc}")
        return wav_bytes


# ---------------------------------------------------------------------------
# TTS engine
# ---------------------------------------------------------------------------

class PiperTTSEngine:
    """
    TTS engine — named PiperTTSEngine for interface compatibility.

    Backends (in priority order):
      1. kokoro-onnx  — high-quality neural TTS, Python 3.13 compatible
      2. macOS `say`  — built-in fallback, always available on macOS
    """

    def __init__(self) -> None:
        self._kokoro_ok = _kokoro_available()
        self._say_ok = _say_available()

        if self._kokoro_ok:
            logger.info("TTS backend: kokoro-onnx (am_adam / bm_george)")
        elif self._say_ok:
            logger.info("TTS backend: macOS `say` (kokoro model files not found)")
        else:
            logger.warning("No TTS backend available — audio disabled")

    @property
    def available(self) -> bool:
        return self._kokoro_ok or self._say_ok

    @property
    def backend(self) -> str:
        if self._kokoro_ok:
            return "kokoro"
        if self._say_ok:
            return "say"
        return "none"

    def synthesize_sync(self, text: str, agent_name: str, trace=None) -> Optional[bytes]:
        """Synthesize text → WAV bytes. Call from a thread-pool executor."""
        import time as _t
        if not text.strip():
            return None

        t0 = _t.monotonic()
        wav: Optional[bytes] = None
        used_backend = "none"
        used_voice = ""

        if self._kokoro_ok:
            used_voice = KOKORO_AGENT_VOICES.get(agent_name, "am_adam")
            wav = _get_kokoro().synthesize(text, agent_name)
            if wav:
                used_backend = "kokoro"
            else:
                logger.warning("Kokoro failed, falling back to say")

        if wav is None and self._say_ok:
            say_voice = MACOS_SAY_VOICES.get(agent_name, "Samantha")
            wav = _synthesize_say(text, say_voice)
            if wav:
                used_backend = "say"
                used_voice = say_voice

        if trace is not None and wav:
            trace.tts_voice = used_voice
            trace.tts_backend = used_backend
            trace.tts_synthesis_ms = (_t.monotonic() - t0) * 1000
            trace.tts_audio_duration_sec = (len(wav) - 44) / (22050 * 2) if len(wav) > 44 else 0.0

        return wav

    async def synthesize(self, text: str, agent_name: str, trace=None) -> Optional[bytes]:
        """Async wrapper — runs synthesis in a thread-pool executor."""
        loop = asyncio.get_event_loop()
        try:
            fn = functools.partial(self.synthesize_sync, text, agent_name, trace)
            return await loop.run_in_executor(None, fn)
        except Exception as exc:
            logger.error(f"TTS async error: {exc}")
            return None


# Module-level singleton
_engine: Optional[PiperTTSEngine] = None


def get_tts_engine() -> PiperTTSEngine:
    global _engine
    if _engine is None:
        _engine = PiperTTSEngine()
    return _engine
