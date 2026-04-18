# backend/commentator/llm/ollama.py
from __future__ import annotations

import json
import logging
import time as _time

import httpx

from commentator.llm.backend import LLMBackend

logger = logging.getLogger("[OLLAMA]")


class OllamaBackend(LLMBackend):
    def __init__(self, base_url: str, model: str, timeout_sec: float) -> None:
        self._base_url = base_url
        self._model = model
        self._timeout = timeout_sec

    # ------------------------------------------------------------------
    # LLMBackend interface
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        return "Ollama"

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def needs_warmup(self) -> bool:
        return True

    async def warmup(self) -> None:
        """Send a minimal request with the exact same options as generate() so Ollama
        pre-allocates the KV cache at the correct size — avoiding cold-start latency
        on the first real generation call."""
        try:
            async with httpx.AsyncClient(timeout=90.0) as client:
                await client.post(
                    f"{self._base_url}/api/generate",
                    json={
                        "model": self._model,
                        "prompt": "Ready.",
                        "stream": False,
                        "options": {
                            "num_predict": 1,
                            "num_ctx": 2048,
                            "num_thread": 4,
                        },
                    },
                )
            logger.info("Ollama model warmed up and ready")
        except Exception as exc:
            logger.warning(f"Ollama warmup skipped ({exc})")

    async def generate(
        self,
        system: str,
        prompt: str,
        temperature: float,
        max_tokens: int,
    ) -> str:
        url = f"{self._base_url}/api/generate"
        payload = {
            "model": self._model,
            "system": system,
            "prompt": prompt,
            "stream": True,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
                "num_ctx": 2048,
                "num_thread": 4,
                "stop": ["\n\n", "###", "---"],
            },
        }

        tokens: list[str] = []
        token_count = 0

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            async with client.stream("POST", url, json=payload) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    try:
                        chunk = json.loads(line)
                    except ValueError:
                        continue
                    tok = chunk.get("response", "")
                    if tok:
                        tokens.append(tok)
                        token_count += 1
                    if chunk.get("done") or token_count >= max_tokens:
                        break

        return "".join(tokens)
