"""Gemini 2.5 Pro adapter via google-genai SDK (direct API, not Vertex).

Uses GOOGLE_API_KEY. Capped at 3 retries on 503/429 per project policy
(prior incident: Pro on Vertex consistently 503'd; the direct API may
behave better, but we don't loop forever and burn keys — after 3
attempts with exponential backoff, the call raises and the runner
records it as an error).

Per-request timeout: an earlier run hung for 10+ hours on a CodeSum
confidence probe — the server closed its side of the socket but the
SDK never surfaced it as a retryable error, leaving the client stuck
in recv(). We set an explicit 60s timeout via HttpOptions and treat
httpx timeout/network exceptions as retryable.
"""

import os
import time

import httpx
from google import genai
from google.genai import errors as genai_errors

from models.base import Model
from models.gemini_adapter import _extract_retry_delay

_MAX_RETRIES = 3
_BASE_DELAY = 4.0  # seconds; doubles each attempt → 4, 8, 16
_REQUEST_TIMEOUT_MS = 60_000  # 60s; Pro summarization observed at 10-32s


class GeminiPro(Model):
    name = "gemini-2.5-pro"
    tier = 3
    # Gemini 2.5 Pro list pricing: $1.25/M input (≤200k ctx), $10/M output.
    cost_per_token = 1.25e-6

    def __init__(
        self,
        model_id: str = "gemini-2.5-pro",
        max_tokens: int = 4096,
        temperature: float = 0.0,
        api_key: str | None = None,
    ) -> None:
        key = api_key or os.environ.get("GOOGLE_API_KEY")
        if not key:
            raise RuntimeError(
                "GOOGLE_API_KEY is not set. Add it to .env or export it."
            )
        self._client = genai.Client(api_key=key)
        self._model_id = model_id
        # Gemini 2.5 Pro requires thinking mode (rejects budget=0). Leave
        # the budget at the API default so reasoning runs; bump
        # max_output_tokens to give the visible answer headroom on top
        # of the reasoning trace.
        self._config = genai.types.GenerateContentConfig(
            max_output_tokens=max_tokens,
            temperature=temperature,
            http_options=genai.types.HttpOptions(timeout=_REQUEST_TIMEOUT_MS),
        )

    def generate(self, prompt: str) -> str:
        last_exc: Exception | None = None
        for attempt in range(_MAX_RETRIES):
            try:
                response = self._client.models.generate_content(
                    model=self._model_id,
                    contents=prompt,
                    config=self._config,
                )
                return response.text.strip()
            except (genai_errors.ServerError, genai_errors.ClientError) as exc:
                code = getattr(exc, "status_code", 0) or 0
                if code in (429, 503):
                    last_exc = exc
                    hint = _extract_retry_delay(exc)
                    delay = hint if hint else _BASE_DELAY * (2 ** attempt)
                    time.sleep(delay)
                    continue
                raise
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                # Socket hang / server-closed-but-SDK-stuck / DNS / connect
                # failures — all retryable from our side.
                last_exc = exc
                delay = _BASE_DELAY * (2 ** attempt)
                time.sleep(delay)
                continue
        raise last_exc  # type: ignore[misc]
