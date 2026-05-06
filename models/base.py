"""Model abstract base class.

A Model is anything that turns a prompt into a string. Adapters wrap
SDKs (Anthropic, Vertex, etc.) and report tier + cost so the router
can make price/quality tradeoffs.

Two surfaces:
  - generate(prompt) -> str: the original text-only call. Existing
    callers (cascade_demo, runner, the standalone benchmarks) use this.
  - generate_structured(prompt) -> GenerationResult: optional logprob-
    enabled call. Adapters that can extract token-level log-probabilities
    from their SDK override this; adapters that can't (Anthropic, o3,
    legacy Vertex) inherit the default, which calls generate() and
    returns a result with logprob fields set to None. The router
    prefers logprob-derived confidence over text-parsed self-report
    when available, and falls back when not.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class GenerationResult:
    """Output of a single-shot completion with optional logprob signal.

    `logprob_mean` and `logprob_min` are mean / min per-token log-
    probability across the visible output tokens. None when the
    underlying SDK / model doesn't expose token logprobs (Anthropic
    Messages API, OpenAI o-series reasoning models, the legacy Vertex
    path). Callers should treat None as "no logprob signal — fall
    back to whatever other confidence channel you have."

    `output_token_count` is the number of output tokens the
    aggregation ran over. Zero on the fallback / no-signal path.
    """

    text: str
    logprob_mean: float | None = None
    logprob_min: float | None = None
    output_token_count: int = 0


class Model(ABC):
    name: str = "unknown"
    tier: str = "small"          # "small" | "medium" | "large"
    cost_per_token: float = 0.0  # USD per input token (rough average is fine)

    @abstractmethod
    def generate(self, prompt: str) -> str:
        """Run a single-shot completion. Return the model's text output."""

    def generate_structured(self, prompt: str) -> GenerationResult:
        """Run a single-shot completion with token-level logprobs when
        the underlying SDK supports it. Default implementation calls
        generate() and returns a result with logprob fields set to None
        — adapters that can extract logprobs override this method.

        This is intentionally a non-abstract base method so adapters
        that don't / can't support logprobs (Anthropic, o3, vertex)
        require zero changes — they keep working through the fallback.
        """
        text = self.generate(prompt)
        return GenerationResult(text=text)
