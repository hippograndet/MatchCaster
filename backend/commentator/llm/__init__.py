# backend/commentator/llm/__init__.py
from __future__ import annotations

import logging

from commentator.llm.backend import LLMBackend

logger = logging.getLogger("[LLM]")

_backend: LLMBackend | None = None


def get_backend() -> LLMBackend:
    if _backend is None:
        raise RuntimeError("LLM backend not initialised — call init_backend() at startup")
    return _backend


def init_backend() -> None:
    """Instantiate the configured backend and store it as the module singleton.
    Called once from main.py on startup."""
    global _backend
    from config import LLM_BACKEND, GROQ_API_KEY, GROQ_MODEL, OLLAMA_BASE_URL, OLLAMA_MODEL, OLLAMA_TIMEOUT_SEC

    if LLM_BACKEND == "groq":
        if not GROQ_API_KEY:
            raise RuntimeError(
                "LLM_BACKEND=groq but GROQ_API_KEY is not set.\n"
                "  Get a free key at https://console.groq.com and run:\n"
                "    export GROQ_API_KEY=gsk_..."
            )
        from commentator.llm.groq import GroqBackend
        _backend = GroqBackend(GROQ_API_KEY, GROQ_MODEL)
        logger.info(f"LLM backend: Groq ({GROQ_MODEL})")
    else:
        from commentator.llm.ollama import OllamaBackend
        _backend = OllamaBackend(OLLAMA_BASE_URL, OLLAMA_MODEL, OLLAMA_TIMEOUT_SEC)
        logger.info(f"LLM backend: Ollama ({OLLAMA_MODEL})")
