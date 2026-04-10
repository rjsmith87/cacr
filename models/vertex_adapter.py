"""Google Gemini Flash adapter via Vertex AI SDK.

Uses application default credentials (gcloud auth application-default login).
Project and location are read from env or .env.
"""

import os

import vertexai
from vertexai.generative_models import GenerativeModel, GenerationConfig

from models.base import Model


class GeminiFlash(Model):
    name = "gemini-2.0-flash"
    tier = "small"
    # Rough input price for Gemini 2.0 Flash (USD/token).
    cost_per_token = 0.4e-7

    def __init__(
        self,
        model_id: str = "gemini-2.0-flash",
        max_tokens: int = 256,
        temperature: float = 0.0,
        project: str | None = None,
        location: str = "us-central1",
    ) -> None:
        project = project or os.environ.get("GCP_PROJECT")
        if not project:
            raise RuntimeError(
                "GCP_PROJECT is not set. Add it to .env or export it."
            )
        vertexai.init(project=project, location=location)
        self._model = GenerativeModel(model_id)
        self._config = GenerationConfig(
            max_output_tokens=max_tokens,
            temperature=temperature,
        )

    def generate(self, prompt: str) -> str:
        response = self._model.generate_content(
            prompt,
            generation_config=self._config,
        )
        return response.text.strip()
