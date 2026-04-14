# backend/debug/override.py
# One-shot prompt override store for developer inspection tool.

from __future__ import annotations

import threading
from typing import Optional


class _PromptOverrideStore:
    """
    Thread-safe store for one-shot LLM prompt overrides per agent.
    An override is consumed (popped) exactly once by the next generate() call.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._overrides: dict[str, dict] = {}  # agent_name → override payload

    def set(self, agent_name: str, payload: dict) -> None:
        """Queue an override for the next LLM call from this agent."""
        with self._lock:
            self._overrides[agent_name] = payload

    def consume(self, agent_name: str) -> Optional[dict]:
        """Return and clear the pending override, or None if none queued."""
        with self._lock:
            return self._overrides.pop(agent_name, None)

    def has_pending(self, agent_name: str) -> bool:
        with self._lock:
            return agent_name in self._overrides


# Module-level singleton
override_store = _PromptOverrideStore()
