"""Gemini 2.5 Flash Lite adapter via google-genai SDK.

The cheapest/fastest Gemini model — true tier 1 small model.
Uses GOOGLE_API_KEY for the direct Gemini API (not Vertex AI).
Retries on transient 503 / 429 errors with exponential backoff.

Per-request timeout: same CLOSE_WAIT-hang failure mode the Pro adapter
hit during the v2 run. On Render, a hung Flash Lite call lets gunicorn
SIGABRT the worker at --timeout, and the resulting Render-edge HTML 500
has no CORS header — so the browser surfaces it as "Failed to fetch".

Two surfaces:
  - generate(prompt) -> str: vanilla call, no logprobs requested.
  - generate_structured(prompt) -> GenerationResult: same call shape
    plus response_logprobs=True / logprobs=N in the config so the
    cascade router sees a real probability signal. Both surfaces
    share the retry/backoff loop.
"""

import os
import time

import httpx
from google import genai
from google.genai import errors as genai_errors

from models.base import GenerationResult, Model
from models.gemini_adapter import (
    _aggregate_gemini_logprobs,
    _extract_retry_delay,
    _is_logprob_unsupported_error,
)

_MAX_RETRIES = 5
_BASE_DELAY = 4.0
_REQUEST_TIMEOUT_MS = 60_000  # 60s per attempt
# Number of alternative tokens to request per output token. See
# gemini_adapter._TOP_LOGPROBS comment — same rationale.
_TOP_LOGPROBS = 5


class GeminiFlashLite(Model):
    name = "gemini-2.5-flash-lite"
    tier = 1
    cost_per_token = 4e-8  # USD per input token

    def __init__(
        self,
        model_id: str = "gemini-2.5-flash-lite",
        max_tokens: int = 256,
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
        self._cfg_kwargs: dict = {
            "max_output_tokens": max_tokens,
            "temperature": temperature,
            "http_options": genai.types.HttpOptions(timeout=_REQUEST_TIMEOUT_MS),
        }
        self._config = genai.types.GenerateContentConfig(**self._cfg_kwargs)

    # ── Public surface ─────────────────────────────────────────────
    def generate(self, prompt: str) -> str:
        response = self._call_with_retry(self._config, prompt)
        return response.text.strip()

    def generate_structured(self, prompt: str) -> GenerationResult:
        structured_cfg = genai.types.GenerateContentConfig(
            **self._cfg_kwargs,
            response_logprobs=True,
            logprobs=_TOP_LOGPROBS,
        )
        try:
            response = self._call_with_retry(structured_cfg, prompt)
        except genai_errors.ClientError as exc:
            # Gemini 2.5 series rejects response_logprobs=True at the API
            # level with a 400 "Logprobs is not enabled for models/..."
            # — see gemini_adapter._is_logprob_unsupported_error for the
            # match. Fall back to plain generate() so the cascade router
            # treats this step the same way it treats Anthropic / o3 /
            # vertex (no logprob signal → use self-report).
            if _is_logprob_unsupported_error(exc):
                text = self.generate(prompt)
                return GenerationResult(text=text)
            raise
        text = response.text.strip()
        return _aggregate_gemini_logprobs(response, text)

    # ── Shared retry/backoff loop ──────────────────────────────────
    def _call_with_retry(self, config, prompt: str):
        last_exc: Exception | None = None
        for attempt in range(_MAX_RETRIES):
            try:
                response = self._client.models.generate_content(
                    model=self._model_id,
                    contents=prompt,
                    config=config,
                )
                return response
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
                # failures — all retryable from our side. Without this catch,
                # a hung connection bypasses retry and the calling worker
                # eventually gets SIGABRTed by gunicorn at --timeout.
                last_exc = exc
                delay = _BASE_DELAY * (2 ** attempt)
                time.sleep(delay)
                continue
        raise last_exc  # type: ignore[misc]
