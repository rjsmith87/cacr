"""Model abstract base class.

A Model is anything that turns a prompt into a string. Adapters wrap
SDKs (Anthropic, Vertex, etc.) and report tier + cost so the router
can make price/quality tradeoffs.
"""

from abc import ABC, abstractmethod


class Model(ABC):
    name: str = "unknown"
    tier: str = "small"          # "small" | "medium" | "large"
    cost_per_token: float = 0.0  # USD per input token (rough average is fine)

    @abstractmethod
    def generate(self, prompt: str) -> str:
        """Run a single-shot completion. Return the model's text output."""
