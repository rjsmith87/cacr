"""OpenAI GPT-4o mini adapter.

Reads OPENAI_API_KEY from the environment (loaded from .env by the runner).

Two surfaces:
  - generate(prompt) -> str: vanilla chat-completions call, no logprobs
    requested. Used by the standalone benchmark runner and any caller
    that doesn't need a confidence signal.
  - generate_structured(prompt) -> GenerationResult: passes
    `logprobs=True, top_logprobs=5` to the chat-completions call and
    aggregates per-token log-probabilities into mean/min so the cascade
    router can make escalation decisions on a real probability signal
    rather than the model's self-reported confidence digit.

Logprobs are returned as response metadata at no extra dollar cost; the
only impact is a small bump in wire bytes and SDK parsing time per
request.
"""

import os

from openai import OpenAI

from models.base import GenerationResult, Model

# How many alternative tokens to request per output token. We don't use
# the alternatives directly in v1 (mean over chosen tokens is the
# signal), but they're free with logprobs=True and become useful in v2
# for entropy-based confidence. Capped at 5 to keep response size bounded.
_TOP_LOGPROBS = 5


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

    def generate_structured(self, prompt: str) -> GenerationResult:
        resp = self._client.chat.completions.create(
            model=self._model_id,
            max_tokens=self._max_tokens,
            temperature=self._temperature,
            messages=[{"role": "user", "content": prompt}],
            logprobs=True,
            top_logprobs=_TOP_LOGPROBS,
        )
        text = (resp.choices[0].message.content or "").strip()
        return _aggregate_openai_logprobs(resp, text)


def _aggregate_openai_logprobs(resp, text: str) -> GenerationResult:
    """Aggregate per-token log-probabilities from an OpenAI chat-completions
    response into mean/min/count. Defensive: any shape change in the SDK
    (missing logprobs field, None content, empty list) silently degrades
    to a no-signal result rather than raising — the cascade router treats
    None logprob_mean as "fall back to self-reported confidence."
    """
    try:
        logprobs_obj = resp.choices[0].logprobs
        if logprobs_obj is None:
            return GenerationResult(text=text)
        content = logprobs_obj.content
        if not content:
            return GenerationResult(text=text)
        token_logprobs = [
            tok.logprob for tok in content
            if getattr(tok, "logprob", None) is not None
        ]
        if not token_logprobs:
            return GenerationResult(text=text)
        return GenerationResult(
            text=text,
            logprob_mean=sum(token_logprobs) / len(token_logprobs),
            logprob_min=min(token_logprobs),
            output_token_count=len(token_logprobs),
        )
    except (AttributeError, IndexError, TypeError):
        # SDK shape drift — never crash the request over telemetry.
        return GenerationResult(text=text)
