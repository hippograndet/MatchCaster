# backend/commentator/llm/groq.py
from __future__ import annotations

import json
import logging

import httpx

from commentator.llm.backend import LLMBackend

logger = logging.getLogger("[GROQ]")

_GROQ_COMPLETIONS = "https://api.groq.com/openai/v1/chat/completions"


class GroqBackend(LLMBackend):
    def __init__(self, api_key: str, model: str) -> None:
        self._api_key = api_key
        self._model = model

    # ------------------------------------------------------------------
    # LLMBackend interface
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        return "Groq"

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def needs_warmup(self) -> bool:
        return False

    async def generate(
        self,
        system: str,
        prompt: str,
        temperature: float,
        max_tokens: int,
    ) -> str:
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": True,
        }

        tokens: list[str] = []

        logger.info(f"→ {self._model} (T={temperature})")
        async with httpx.AsyncClient(timeout=30.0) as client:
            async with client.stream(
                "POST", _GROQ_COMPLETIONS, headers=headers, json=payload
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    raw = line[6:]  # strip "data: "
                    if raw.strip() == "[DONE]":
                        break
                    try:
                        chunk = json.loads(raw)
                    except ValueError:
                        continue
                    delta = chunk.get("choices", [{}])[0].get("delta", {})
                    tok = delta.get("content", "")
                    if tok:
                        tokens.append(tok)

        result = "".join(tokens)
        logger.info(f"← {len(result.split())} tokens")
        return result
