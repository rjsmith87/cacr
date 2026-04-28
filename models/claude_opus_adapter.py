"""Anthropic Claude Opus 4.7 adapter — frontier tier-3 model."""

import os

from anthropic import Anthropic

from models.base import Model


class ClaudeOpus(Model):
    name = "claude-opus-4-7"
    tier = 3
    # Opus 4.x list pricing: $15/M input, $75/M output. Use input as the
    # router cost signal (matches the convention in the other adapters).
    cost_per_token = 1.5e-5

    def __init__(
        self,
        model_id: str = "claude-opus-4-7",
        max_tokens: int = 256,
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

    def generate(self, prompt: str) -> str:
        # Opus 4.7 deprecates `temperature` — omit it entirely.
        resp = self._client.messages.create(
            model=self._model_id,
            max_tokens=self._max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        parts = []
        for block in resp.content:
            text = getattr(block, "text", None)
            if text:
                parts.append(text)
        return "".join(parts).strip()
