"""Task abstract base class.

A Task bundles a set of examples, a prompt template, and an evaluator.
The runner iterates `examples()`, calls `prompt(example)` against a model,
scores the output with `eval(example, output)`, and aggregates per-task.
"""

from abc import ABC, abstractmethod
from typing import Any


class Task(ABC):
    # Class-level metadata. Subclasses override.
    family: str = "generic"          # e.g. "classification", "extraction"
    complexity: str = "easy"         # "easy" | "medium" | "hard"
    threshold: float = 0.8           # min score for a model to be "good enough"

    @property
    def name(self) -> str:
        return self.__class__.__name__

    @abstractmethod
    def examples(self) -> list[dict[str, Any]]:
        """Return a list of example dicts. Each dict carries inputs + gold labels."""

    @abstractmethod
    def prompt(self, example: dict[str, Any]) -> str:
        """Render the user-facing prompt for one example."""

    @abstractmethod
    def eval(self, example: dict[str, Any], output: str) -> float:
        """Score a single model output against the example's gold label. Range [0, 1]."""
