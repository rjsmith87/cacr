"""OpenAI GPT-4o mini adapter.

Reads OPENAI_API_KEY from the environment (loaded from .env by the runner).
"""

import os

from openai import OpenAI

from models.base import Model


class GPT4oMini(Model):
    name = "gpt-4o-mini"
    tier = 2
    cost_per_token = 1.5e-7  # USD per input token

    def __init__(
        self,
        model_id: str = "gpt-4o-mini",
        max_tokens: int = 256,
        temperature: float = 0.0,
        api_key: str | None = None,
    ) -> None:
        key = api_key or os.environ.get("OPENAI_API_KEY")
        if not key:
            raise RuntimeError(
                "OPENAI_API_KEY is not set. Add it to .env or export it."
            )
        self._client = OpenAI(api_key=key)
        self._model_id = model_id
        self._max_tokens = max_tokens
        self._temperature = temperature

    def generate(self, prompt: str) -> str:
        resp = self._client.chat.completions.create(
            model=self._model_id,
            max_tokens=self._max_tokens,
            temperature=self._temperature,
            messages=[{"role": "user", "content": prompt}],
        )
        return (resp.choices[0].message.content or "").strip()
