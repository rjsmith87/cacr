"""OpenAI GPT-5 adapter — standard chat completions, frontier tier-3."""

import os

from openai import OpenAI

from models.base import Model


class GPT5(Model):
    name = "gpt-5"
    tier = 3
    # GPT-5 list pricing: ~$1.25/M input, $10/M output. Input as router signal.
    cost_per_token = 1.25e-6

    def __init__(
        self,
        model_id: str = "gpt-5",
        max_completion_tokens: int = 512,
        api_key: str | None = None,
    ) -> None:
        key = api_key or os.environ.get("OPENAI_API_KEY")
        if not key:
            raise RuntimeError(
                "OPENAI_API_KEY is not set. Add it to .env or export it."
            )
        self._client = OpenAI(api_key=key)
        self._model_id = model_id
        # GPT-5 rejects `max_tokens` and `temperature` — uses
        # `max_completion_tokens` and the API-default temperature.
        self._max_completion_tokens = max_completion_tokens

    def generate(self, prompt: str) -> str:
        resp = self._client.chat.completions.create(
            model=self._model_id,
            max_completion_tokens=self._max_completion_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        return (resp.choices[0].message.content or "").strip()
