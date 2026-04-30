"""Gemini 2.5 Flash adapter via google-genai SDK.

Uses GOOGLE_API_KEY for the direct Gemini API (not Vertex AI).
Retries on transient 503 / 429 errors with exponential backoff.

Per-request timeout: same CLOSE_WAIT-hang failure mode the Pro adapter
hit during the v2 run can also strand Flash inside ssl.recv() — the
server closes its side, the SDK never surfaces it as retryable, and
the worker sits there until gunicorn SIGABRTs it. On Render that
manifests as an HTML 500 from the edge with no CORS header, so the
browser surfaces it as "Failed to fetch". We pin a 60s timeout via
HttpOptions and treat httpx timeout/network exceptions as retryable.
"""

import os
import re
import time

import httpx
from google import genai
from google.genai import errors as genai_errors

from models.base import Model

_MAX_RETRIES = 5
_BASE_DELAY = 4.0  # seconds; doubles each attempt → 4, 8, 16, 32, 64
_MIN_CALL_INTERVAL = 6.0  # Flash-specific rate-limit pacing (seconds)
_REQUEST_TIMEOUT_MS = 60_000  # 60s per attempt


def _extract_retry_delay(exc: Exception) -> float | None:
    """Try to parse a 'retryDelay' hint from a Gemini error message."""
    msg = str(exc)
    m = re.search(r"retry(?:Delay)?[\"']?\s*[:=]\s*[\"']?(\d+)", msg, re.IGNORECASE)
    return float(m.group(1)) if m else None


class GeminiFlash(Model):
    name = "gemini-2.5-flash"
    tier = 1
    cost_per_token = 1e-7  # USD per input token

    def __init__(
        self,
        model_id: str = "gemini-2.5-flash",
        max_tokens: int = 1024,
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
        # Disable Gemini 2.5 reasoning tokens — they consume the output
        # budget before visible JSON completes, truncating structured
        # responses. CVE classification does not need chain-of-thought.
        cfg_kwargs = {
            "max_output_tokens": max_tokens,
            "temperature": temperature,
            "http_options": genai.types.HttpOptions(timeout=_REQUEST_TIMEOUT_MS),
        }
        try:
            cfg_kwargs["thinking_config"] = genai.types.ThinkingConfig(
                thinking_budget=0
            )
        except AttributeError:
            pass  # older SDK without ThinkingConfig; safe to skip
        self._config = genai.types.GenerateContentConfig(**cfg_kwargs)
        self._last_call_ts: float = 0.0

    def generate(self, prompt: str) -> str:
        elapsed = time.time() - self._last_call_ts
        if elapsed < _MIN_CALL_INTERVAL:
            time.sleep(_MIN_CALL_INTERVAL - elapsed)
        last_exc: Exception | None = None
        for attempt in range(_MAX_RETRIES):
            try:
                response = self._client.models.generate_content(
                    model=self._model_id,
                    contents=prompt,
                    config=self._config,
                )
                self._last_call_ts = time.time()
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
                # failures — all retryable from our side. Without this catch,
                # a hung connection bypasses retry and the calling worker
                # eventually gets SIGABRTed by gunicorn at --timeout.
                last_exc = exc
                delay = _BASE_DELAY * (2 ** attempt)
                time.sleep(delay)
                continue
        raise last_exc  # type: ignore[misc]
