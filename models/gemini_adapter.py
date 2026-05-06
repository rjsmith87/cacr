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

Two surfaces:
  - generate(prompt) -> str: vanilla call, no logprobs requested.
  - generate_structured(prompt) -> GenerationResult: same call shape
    plus response_logprobs=True / logprobs=N in the config so the
    cascade router can read a real probability signal instead of the
    self-reported confidence digit. Both surfaces share the same
    retry/backoff/pacing loop.
"""

import os
import re
import time

import httpx
from google import genai
from google.genai import errors as genai_errors

from models.base import GenerationResult, Model

_MAX_RETRIES = 5
_BASE_DELAY = 4.0  # seconds; doubles each attempt → 4, 8, 16, 32, 64
_MIN_CALL_INTERVAL = 6.0  # Flash-specific rate-limit pacing (seconds)
_REQUEST_TIMEOUT_MS = 60_000  # 60s per attempt
# Number of alternative tokens to request per output token. Free metadata
# at the API level; modest wire-byte bump. Capped at 5 to bound response
# size — v1 only consumes the chosen-token logprob, but the alternatives
# become useful for entropy-based confidence in v2.
_TOP_LOGPROBS = 5


def _extract_retry_delay(exc: Exception) -> float | None:
    """Try to parse a 'retryDelay' hint from a Gemini error message."""
    msg = str(exc)
    m = re.search(r"retry(?:Delay)?[\"']?\s*[:=]\s*[\"']?(\d+)", msg, re.IGNORECASE)
    return float(m.group(1)) if m else None


def _is_logprob_unsupported_error(exc: Exception) -> bool:
    """True when the Gemini API returned a 400 INVALID_ARGUMENT specifically
    rejecting response_logprobs (observed on the 2.5 series via the direct
    API). Used by both Gemini adapters to fall through to a no-signal
    GenerationResult when logprobs aren't available — same path Anthropic
    and o3 take by inheriting the base-class default.

    Match is on the textual message because google-genai's ClientError
    doesn't expose a structured error code beyond status_code=400.
    """
    if getattr(exc, "status_code", 0) != 400:
        return False
    return "Logprobs is not enabled" in str(exc)


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
        self._cfg_kwargs: dict = {
            "max_output_tokens": max_tokens,
            "temperature": temperature,
            "http_options": genai.types.HttpOptions(timeout=_REQUEST_TIMEOUT_MS),
        }
        try:
            self._cfg_kwargs["thinking_config"] = genai.types.ThinkingConfig(
                thinking_budget=0
            )
        except AttributeError:
            pass  # older SDK without ThinkingConfig; safe to skip
        self._config = genai.types.GenerateContentConfig(**self._cfg_kwargs)
        self._last_call_ts: float = 0.0

    # ── Public surface ─────────────────────────────────────────────
    def generate(self, prompt: str) -> str:
        response = self._call_with_retry(self._config, prompt)
        return response.text.strip()

    def generate_structured(self, prompt: str) -> GenerationResult:
        # Build a logprob-enabled config on the fly. Doing this per-call
        # rather than caching as self._structured_config keeps the cost
        # of unused configurations zero on the generate()-only paths.
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
            # — observed live on flash and flash-lite during the Phase 1
            # rollout. Falling back to plain generate() preserves the
            # "no-logprob path" behavior the router already handles
            # gracefully (Anthropic / o3 / vertex take the same fallback).
            # Surfaces as a GenerationResult with logprob fields None.
            if _is_logprob_unsupported_error(exc):
                text = self.generate(prompt)
                return GenerationResult(text=text)
            raise
        text = response.text.strip()
        return _aggregate_gemini_logprobs(response, text)

    # ── Shared retry/backoff loop ──────────────────────────────────
    def _call_with_retry(self, config, prompt: str):
        """Wrap generate_content with the project's retry/backoff/pacing
        policy. Both generate() and generate_structured() route through
        here so the failure semantics stay identical regardless of which
        surface the caller picked."""
        elapsed = time.time() - self._last_call_ts
        if elapsed < _MIN_CALL_INTERVAL:
            time.sleep(_MIN_CALL_INTERVAL - elapsed)
        last_exc: Exception | None = None
        for attempt in range(_MAX_RETRIES):
            try:
                response = self._client.models.generate_content(
                    model=self._model_id,
                    contents=prompt,
                    config=config,
                )
                self._last_call_ts = time.time()
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


def _aggregate_gemini_logprobs(response, text: str) -> GenerationResult:
    """Aggregate per-token log-probabilities from a google-genai response
    into mean/min/count. Two paths in priority order:

      1. Server-computed `candidate.avg_logprobs` (a single float). Some
         SDK versions surface this directly — cheapest path when it
         exists.
      2. Per-token `logprobs_result.chosen_candidates[i].log_probability`.
         Compute mean and min ourselves.

    Defensive: any missing field, None, or shape change silently degrades
    to a no-signal result rather than raising. The cascade router treats
    None logprob_mean as "fall back to self-reported confidence."
    """
    try:
        candidate = response.candidates[0]
    except (AttributeError, IndexError, TypeError):
        return GenerationResult(text=text)

    # Path 1: server-computed mean.
    server_mean = getattr(candidate, "avg_logprobs", None)

    # Path 2: per-token list (also gives us min + count, which path 1 doesn't).
    token_logprobs: list[float] = []
    try:
        result = getattr(candidate, "logprobs_result", None)
        if result is not None:
            chosen = getattr(result, "chosen_candidates", None) or []
            for tok in chosen:
                lp = getattr(tok, "log_probability", None)
                if lp is not None:
                    token_logprobs.append(lp)
    except (AttributeError, TypeError):
        token_logprobs = []

    if token_logprobs:
        return GenerationResult(
            text=text,
            logprob_mean=sum(token_logprobs) / len(token_logprobs),
            logprob_min=min(token_logprobs),
            output_token_count=len(token_logprobs),
        )

    if server_mean is not None:
        # No per-token list available, but the server computed a mean.
        # Use it; leave min as None and count as 0 to mark "we don't
        # have token-level data."
        return GenerationResult(
            text=text,
            logprob_mean=float(server_mean),
            logprob_min=None,
            output_token_count=0,
        )

    return GenerationResult(text=text)
