"""Anthropic Claude adapter.

Wraps the official `anthropic` SDK. Defaults to Claude Haiku 4.5 — the
small, fast tier we benchmark as the SLM baseline.
"""

import os

from anthropic import Anthropic

from models.base import Model


class ClaudeHaiku(Model):
    name = "claude-haiku-4-5"
    tier = 1
    # Approx input price for Haiku 4.5 (USD/token). Output is higher; we
    # use input as a rough router signal — refine when we wire real billing.
    cost_per_token = 1.0e-6

    def __init__(
        self,
        model_id: str = "claude-haiku-4-5-20251001",
        max_tokens: int = 256,
        temperature: float = 0.0,
        api_key: str | None = None,
    ) -> None:
        key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set. Add it to .env or export it."
            )
        self._client = Anthropic(api_key=key)
        self._model_id = model_id
        self._max_tokens = max_tokens
        self._temperature = temperature

    def generate(self, prompt: str) -> str:
        resp = self._client.messages.create(
            model=self._model_id,
            max_tokens=self._max_tokens,
            temperature=self._temperature,
            messages=[{"role": "user", "content": prompt}],
        )
        # Concatenate any text blocks in the response.
        parts = []
        for block in resp.content:
            text = getattr(block, "text", None)
            if text:
                parts.append(text)
        return "".join(parts).strip()
