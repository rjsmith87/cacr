"""Gemini 2.5 Pro adapter via google-genai SDK.

Uses GOOGLE_API_KEY for the direct Gemini API (not Vertex AI).
Retries on transient 503 / 429 errors.
"""

import os
import time

from google import genai
from google.genai import errors as genai_errors

from models.base import Model

_MAX_RETRIES = 3
_RETRY_BACKOFF = 2.0  # seconds, doubled each attempt


class GeminiPro(Model):
    name = "gemini-2.5-pro"
    tier = 3
    cost_per_token = 3.5e-6  # USD per input token

    def __init__(
        self,
        model_id: str = "gemini-2.5-pro",
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
        self._config = genai.types.GenerateContentConfig(
            max_output_tokens=max_tokens,
            temperature=temperature,
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
                    time.sleep(_RETRY_BACKOFF * (2 ** attempt))
                    continue
                raise
        raise last_exc  # type: ignore[misc]
