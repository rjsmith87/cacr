"""OpenAI o3 reasoning-model adapter — frontier tier-3.

Differences from a standard chat-completions call:
- No `temperature` (reasoning models reject it; the API enforces 1.0).
- `max_completion_tokens` instead of `max_tokens`.
- `reasoning_effort` controls the size of the hidden reasoning trace.
- Usage returns `reasoning_tokens` separately under
  `completion_tokens_details`. Reasoning tokens are billed at the output
  rate, so the cost model must add them to visible output tokens.
"""

import os

from openai import OpenAI

from models.base import Model


class O3(Model):
    name = "o3"
    tier = 3
    # o3 list pricing: $2/M input, $8/M output (reasoning tokens billed
    # at the output rate). Input rate is the router signal.
    cost_per_token = 2.0e-6

    def __init__(
        self,
        model_id: str = "o3",
        max_completion_tokens: int = 2048,
        reasoning_effort: str = "medium",
        api_key: str | None = None,
    ) -> None:
        key = api_key or os.environ.get("OPENAI_API_KEY")
        if not key:
            raise RuntimeError(
                "OPENAI_API_KEY is not set. Add it to .env or export it."
            )
        self._client = OpenAI(api_key=key)
        self._model_id = model_id
        # Headroom for the reasoning trace + visible answer; classification
        # answers are short but reasoning eats budget silently.
        self._max_completion_tokens = max_completion_tokens
        self._reasoning_effort = reasoning_effort
        self.last_usage: dict | None = None

    def generate(self, prompt: str) -> str:
        resp = self._client.chat.completions.create(
            model=self._model_id,
            max_completion_tokens=self._max_completion_tokens,
            reasoning_effort=self._reasoning_effort,
            messages=[{"role": "user", "content": prompt}],
        )
        usage = resp.usage
        details = getattr(usage, "completion_tokens_details", None)
        reasoning_tokens = getattr(details, "reasoning_tokens", 0) if details else 0
        self.last_usage = {
            "input_tokens": usage.prompt_tokens,
            "output_tokens": usage.completion_tokens,
            "reasoning_tokens": reasoning_tokens,
        }
        return (resp.choices[0].message.content or "").strip()
