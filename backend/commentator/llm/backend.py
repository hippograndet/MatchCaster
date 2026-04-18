# backend/commentator/llm/backend.py
from __future__ import annotations
from abc import ABC, abstractmethod


class LLMBackend(ABC):
    """Abstract LLM backend — all commentary agents call generate() through this interface."""

    @abstractmethod
    async def generate(
        self,
        system: str,
        prompt: str,
        temperature: float,
        max_tokens: int,
    ) -> str:
        """Generate text and return the raw string (no cleaning)."""
        ...

    async def warmup(self) -> None:
        """Optional pre-warm (no-op by default — only Ollama needs it)."""

    @property
    def needs_warmup(self) -> bool:
        return False

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable backend name for logs and UI."""
        ...

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Active model identifier (shown in UI badge)."""
        ...
