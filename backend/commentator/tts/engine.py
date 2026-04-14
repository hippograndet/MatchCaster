# backend/commentator/tts/engine.py
# PiperTTS wrapper: text → WAV bytes, with voice selection and duration cap.

from __future__ import annotations

import asyncio
import io
import logging
import os
import struct
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from config import MAX_AUDIO_DURATION_SEC
from commentator.tts.voices import get_voice_for_agent, PIPER_VOICES_DIR, FALLBACK_VOICE, MACOS_SAY_VOICES

logger = logging.getLogger("[TTS]")

# Piper binary location (searched in PATH and common install paths)
# On macOS the wrapper script at ~/.local/share/piper/piper.sh sets DYLD_LIBRARY_PATH
_PIPER_CANDIDATES = [
    os.path.expanduser("~/.local/share/piper/piper.sh"),  # macOS wrapper (preferred)
    os.path.expanduser("~/.local/share/piper/piper"),     # direct binary fallback
    "piper",
    os.path.expanduser("~/.local/bin/piper"),
    "/usr/local/bin/piper",
    "/opt/homebrew/bin/piper",
]


def _find_piper() -> Optional[str]:
    """Locate the piper binary."""
    for candidate in _PIPER_CANDIDATES:
        if Path(candidate).exists() or _which(candidate):
            return candidate
    return None


def _which(cmd: str) -> Optional[str]:
    try:
        result = subprocess.run(["which", cmd], capture_output=True, text=True)
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# macOS `say` backend
# ---------------------------------------------------------------------------

def _say_available() -> bool:
    """Return True if macOS `say` command is available."""
    return _which("say") is not None


def _synthesize_say(text: str, voice: str) -> Optional[bytes]:
    """
    Synthesize speech using macOS built-in `say` command.
    Returns WAV bytes or None on failure.

    `say` outputs AIFF; we convert to WAV with `afconvert` (also built-in on macOS).
    """
    if not text.strip():
        return None
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            aiff_path = os.path.join(tmpdir, "out.aiff")
            wav_path = os.path.join(tmpdir, "out.wav")

            # Synthesize to AIFF
            say_cmd = ["say", "-v", voice, "-o", aiff_path, text]
            result = subprocess.run(say_cmd, capture_output=True, timeout=15.0)
            if result.returncode != 0 or not os.path.exists(aiff_path):
                logger.error(f"say command failed: {result.stderr.decode()[:100]}")
                return None

            # Convert AIFF → WAV (16-bit, 22050 Hz mono)
            conv_cmd = [
                "afconvert",
                "-f", "WAVE",
                "-d", "LEI16@22050",
                "-c", "1",
                aiff_path,
                wav_path,
            ]
            result2 = subprocess.run(conv_cmd, capture_output=True, timeout=10.0)
            if result2.returncode != 0 or not os.path.exists(wav_path):
                logger.error(f"afconvert failed: {result2.stderr.decode()[:100]}")
                return None

            with open(wav_path, "rb") as f:
                wav_bytes = f.read()

        wav_bytes = _truncate_wav(wav_bytes, MAX_AUDIO_DURATION_SEC)
        return wav_bytes

    except subprocess.TimeoutExpired:
        logger.warning(f"say timed out for: {text[:50]!r}")
        return None
    except Exception as exc:
        logger.error(f"say synthesis error: {exc}")
        return None


def _voice_model_path(voice_name: str) -> str:
    """Return the .onnx model path for a given voice name."""
    voices_dir = Path(os.path.expanduser(PIPER_VOICES_DIR))
    # Piper models are stored as en_US-lessac-medium.onnx etc.
    onnx = voices_dir / f"{voice_name}.onnx"
    if onnx.exists():
        return str(onnx)
    # Some installations use subdirectory structure
    parts = voice_name.split("-")
    if len(parts) >= 2:
        lang = parts[0]
        subdir = voices_dir / lang / voice_name / f"{voice_name}.onnx"
        if subdir.exists():
            return str(subdir)
    return str(onnx)  # Return expected path even if not found (will fail at runtime)


def _truncate_wav(wav_bytes: bytes, max_seconds: float) -> bytes:
    """
    Truncate WAV audio to max_seconds at a zero-crossing to avoid clicks.
    Returns the truncated WAV bytes with corrected header.
    """
    if len(wav_bytes) < 44:
        return wav_bytes

    # Parse WAV header
    try:
        riff, size, wave = struct.unpack_from("<4sI4s", wav_bytes, 0)
        if riff != b"RIFF" or wave != b"WAVE":
            return wav_bytes

        # Find 'fmt ' chunk
        offset = 12
        sample_rate = 22050
        num_channels = 1
        bits_per_sample = 16
        data_start = 44
        data_size = len(wav_bytes) - 44

        while offset < len(wav_bytes) - 8:
            chunk_id = wav_bytes[offset:offset + 4]
            chunk_size = struct.unpack_from("<I", wav_bytes, offset + 4)[0]
            if chunk_id == b"fmt ":
                audio_format, num_channels, sample_rate, byte_rate, block_align, bits_per_sample = \
                    struct.unpack_from("<HHIIHH", wav_bytes, offset + 8)
            elif chunk_id == b"data":
                data_start = offset + 8
                data_size = chunk_size
                break
            offset += 8 + chunk_size

        bytes_per_sample = bits_per_sample // 8
        max_samples = int(max_seconds * sample_rate * num_channels)
        max_bytes = max_samples * bytes_per_sample

        if data_size <= max_bytes:
            return wav_bytes  # No truncation needed

        # Truncate at max_bytes, align to frame boundary
        truncated_data_size = min(max_bytes, data_size)
        truncated_data_size -= truncated_data_size % (num_channels * bytes_per_sample)

        # Rebuild WAV: header (up to data chunk) + truncated data
        header = bytearray(wav_bytes[:data_start])
        # Update data chunk size in header
        struct.pack_into("<I", header, data_start - 4, truncated_data_size)
        # Update RIFF size
        new_riff_size = data_start - 8 + truncated_data_size
        struct.pack_into("<I", header, 4, new_riff_size)

        truncated = bytes(header) + wav_bytes[data_start:data_start + truncated_data_size]
        return truncated

    except (struct.error, IndexError) as exc:
        logger.warning(f"WAV truncation failed: {exc}")
        return wav_bytes


class PiperTTSEngine:
    """
    TTS engine with two backends:
      1. Piper (preferred) — higher quality, needs separate install
      2. macOS `say` (fallback) — built-in, works immediately on macOS

    Runs synchronously in an executor to avoid blocking the event loop.
    """

    def __init__(self) -> None:
        self._piper_bin = _find_piper()
        self._say_ok = _say_available()

        if self._piper_bin:
            logger.info(f"TTS backend: Piper at {self._piper_bin}")
        elif self._say_ok:
            logger.info("TTS backend: macOS `say` (Piper not found)")
        else:
            logger.warning("No TTS backend available — audio disabled")

    @property
    def available(self) -> bool:
        return self._piper_bin is not None or self._say_ok

    @property
    def backend(self) -> str:
        if self._piper_bin:
            return "piper"
        if self._say_ok:
            return "say"
        return "none"

    def synthesize_sync(self, text: str, agent_name: str, trace=None) -> Optional[bytes]:
        """
        Synthesize text for a given agent. Tries Piper first, falls back to macOS `say`.
        Returns WAV bytes or None on failure.
        This runs synchronously — call from an executor thread.
        """
        import time as _time
        if not text.strip():
            return None

        _tts_start = _time.monotonic()
        wav: Optional[bytes] = None
        used_backend = "none"
        used_voice = ""

        # --- Piper path ---
        if self._piper_bin:
            used_voice = get_voice_for_agent(agent_name)
            wav = self._piper_synthesize(text, used_voice)
            if wav:
                used_backend = "piper"
            else:
                logger.warning("Piper failed, trying say fallback")

        # --- macOS say fallback ---
        if wav is None and self._say_ok:
            say_voice = MACOS_SAY_VOICES.get(agent_name, "Samantha")
            wav = _synthesize_say(text, say_voice)
            if wav:
                used_backend = "say"
                used_voice = say_voice

        if trace is not None and wav:
            trace.tts_voice = used_voice
            trace.tts_backend = used_backend
            trace.tts_synthesis_ms = (_time.monotonic() - _tts_start) * 1000
            trace.tts_audio_duration_sec = (len(wav) - 44) / (22050 * 2) if len(wav) > 44 else 0.0

        return wav

    def _piper_synthesize(self, text: str, voice: str) -> Optional[bytes]:
        model_path = _voice_model_path(voice)
        if not Path(model_path).exists():
            logger.warning(f"Voice model not found: {model_path}")
            if voice != FALLBACK_VOICE:
                model_path = _voice_model_path(FALLBACK_VOICE)
                if not Path(model_path).exists():
                    return None

        try:
            cmd = [self._piper_bin, "--model", model_path, "--output_raw", "--quiet"]
            result = subprocess.run(
                cmd, input=text.encode("utf-8"), capture_output=True, timeout=10.0
            )
            if result.returncode != 0:
                logger.error(f"Piper error: {result.stderr.decode()[:200]}")
                return None
            raw_pcm = result.stdout
            if not raw_pcm:
                return None
            wav_bytes = _pcm_to_wav(raw_pcm, sample_rate=22050, channels=1, bits=16)
            return _truncate_wav(wav_bytes, MAX_AUDIO_DURATION_SEC)
        except subprocess.TimeoutExpired:
            logger.warning(f"Piper timed out: {text[:50]!r}")
            return None
        except Exception as exc:
            logger.error(f"Piper synthesis error: {exc}")
            return None

    async def synthesize(self, text: str, agent_name: str, trace=None) -> Optional[bytes]:
        """Async wrapper: runs synthesis in thread pool executor."""
        import functools
        loop = asyncio.get_event_loop()
        try:
            fn = functools.partial(self.synthesize_sync, text, agent_name, trace)
            wav_bytes = await loop.run_in_executor(None, fn)
            return wav_bytes
        except Exception as exc:
            logger.error(f"TTS async error: {exc}")
            return None


def _pcm_to_wav(pcm_data: bytes, sample_rate: int, channels: int, bits: int) -> bytes:
    """Wrap raw PCM bytes in a WAV container header."""
    data_size = len(pcm_data)
    byte_rate = sample_rate * channels * bits // 8
    block_align = channels * bits // 8
    riff_size = 36 + data_size

    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        riff_size,
        b"WAVE",
        b"fmt ",
        16,           # fmt chunk size
        1,            # PCM format
        channels,
        sample_rate,
        byte_rate,
        block_align,
        bits,
        b"data",
        data_size,
    )
    return header + pcm_data


# Module-level singleton
_engine: Optional[PiperTTSEngine] = None


def get_tts_engine() -> PiperTTSEngine:
    global _engine
    if _engine is None:
        _engine = PiperTTSEngine()
    return _engine
