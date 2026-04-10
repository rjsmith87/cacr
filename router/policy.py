"""CACR Router — route prompts to cost-optimal models.

Two router implementations:
1. LookupTableRouter: reads the cost matrix CSV, picks cheapest passing model
2. CACRRouter: logistic regression trained on benchmark results
"""

import csv
import json
import os
import pickle
import sys
from dataclasses import dataclass
from typing import Any

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _ROOT)


@dataclass
class RoutingDecision:
    recommended_model: str
    expected_cost: float
    confidence_interval: tuple[float, float]
    reasoning: str


# ── Lookup Table Router (baseline) ─────────────────────────────────

class LookupTableRouter:
    """Baseline: read cost_matrix.csv, pick cheapest passing model per task."""

    def __init__(self, csv_path: str | None = None):
        self._csv_path = csv_path or os.path.join(_ROOT, "results", "cost_matrix.csv")
        self._matrix: list[dict[str, Any]] = []
        self._load()

    def _load(self) -> None:
        if not os.path.exists(self._csv_path):
            return
        with open(self._csv_path) as f:
            self._matrix = list(csv.DictReader(f))
        for row in self._matrix:
            row["mean_score"] = float(row.get("mean_score", 0))
            row["expected_cost_usd"] = float(row.get("expected_cost_usd", 0))
            row["passes_threshold"] = row.get("passes_threshold", "").lower() == "true"
            row["is_cost_optimal"] = row.get("is_cost_optimal", "").lower() == "true"

    def route(self, task: str, **kwargs: Any) -> RoutingDecision:
        candidates = [r for r in self._matrix if r["task"] == task and r["passes_threshold"]]
        if not candidates:
            # Fallback to Haiku
            return RoutingDecision(
                recommended_model="claude-haiku-4-5",
                expected_cost=0.00023,
                confidence_interval=(0.0, 1.0),
                reasoning=f"No model passes threshold for {task}; defaulting to Haiku.",
            )
        best = min(candidates, key=lambda r: r["expected_cost_usd"])
        return RoutingDecision(
            recommended_model=best["model"],
            expected_cost=best["expected_cost_usd"],
            confidence_interval=(best["mean_score"] - 0.1, min(1.0, best["mean_score"] + 0.1)),
            reasoning=(
                f"Cheapest passing model for {task}: {best['model']} "
                f"(score={best['mean_score']:.2f}, cost=${best['expected_cost_usd']:.8f})"
            ),
        )


# ── CACR Router (trained classifier) ──────────────────────────────

FAMILY_MAP = {"classification": 0, "generation": 1}
COMPLEXITY_MAP = {"easy": 0, "medium": 1, "hard": 2}
MODEL_NAMES = ["claude-haiku-4-5", "gemini-2.5-flash", "gemini-2.5-flash-lite", "gpt-4o-mini"]


class CACRRouter:
    """Logistic regression router trained on benchmark results.

    Features: [task_family_encoded, complexity_encoded, pipeline_position,
               upstream_confidence_normalized]
    Target: model index that is cost-optimal
    """

    def __init__(self, model_path: str | None = None):
        self._model_path = model_path or os.path.join(_ROOT, "router", "cacr_router.pkl")
        self._clf = None
        self._lookup = LookupTableRouter()  # fallback

    def fit(self, bq_results: list[dict[str, Any]]) -> None:
        """Train on benchmark call records."""
        from sklearn.linear_model import LogisticRegression
        from sklearn.preprocessing import StandardScaler

        # Build training data: for each (task, difficulty), the target is
        # the cost-optimal model index from the cost matrix
        summaries = [r for r in bq_results if r.get("event") == "summary"]

        # Find cost-optimal model per task
        from router.cost_model import build_cost_matrix_from_jsonl
        matrix = build_cost_matrix_from_jsonl(bq_results)
        optimal: dict[str, str] = {}
        for entry in matrix:
            if entry.get("is_cost_optimal"):
                optimal[entry["task"]] = entry["model"]

        X, y = [], []
        for row in [r for r in bq_results if r.get("event") == "call"]:
            task = row.get("task", "")
            family = row.get("family", "classification")
            diff = row.get("difficulty", "medium")
            conf = row.get("confidence_score")
            if conf is None:
                conf = 5

            opt_model = optimal.get(task, "claude-haiku-4-5")
            if opt_model not in MODEL_NAMES:
                continue

            fam_enc = FAMILY_MAP.get(family, 0)
            diff_enc = COMPLEXITY_MAP.get(diff, 1)
            pipe_pos = 1  # default; will vary in pipeline context
            conf_norm = conf / 10.0

            X.append([fam_enc, diff_enc, pipe_pos, conf_norm])
            y.append(MODEL_NAMES.index(opt_model))

        if len(set(y)) < 2:
            # Not enough diversity — save a trivial model
            self._clf = None
            self._default_model = MODEL_NAMES[y[0]] if y else "claude-haiku-4-5"
            self._save()
            return

        scaler = StandardScaler()
        X_scaled = scaler.fit_transform(X)

        clf = LogisticRegression(max_iter=1000, random_state=42)
        clf.fit(X_scaled, y)

        self._clf = clf
        self._scaler = scaler
        self._save()

    def _save(self) -> None:
        state = {
            "clf": self._clf,
            "scaler": getattr(self, "_scaler", None),
            "default_model": getattr(self, "_default_model", "claude-haiku-4-5"),
        }
        with open(self._model_path, "wb") as f:
            pickle.dump(state, f)

    def load(self) -> None:
        if not os.path.exists(self._model_path):
            return
        with open(self._model_path, "rb") as f:
            state = pickle.load(f)
        self._clf = state.get("clf")
        self._scaler = state.get("scaler")
        self._default_model = state.get("default_model", "claude-haiku-4-5")

    def route(
        self,
        prompt: str,
        task_family: str = "classification",
        complexity: str = "medium",
        pipeline_position: int = 1,
        upstream_confidence: float = 0.8,
    ) -> RoutingDecision:
        if self._clf is None:
            self.load()

        if self._clf is None:
            # No trained model, use default
            model = getattr(self, "_default_model", "claude-haiku-4-5")
            return RoutingDecision(
                recommended_model=model,
                expected_cost=0.0,
                confidence_interval=(0.0, 1.0),
                reasoning=f"Classifier not trained; defaulting to {model}.",
            )

        fam_enc = FAMILY_MAP.get(task_family, 0)
        diff_enc = COMPLEXITY_MAP.get(complexity, 1)
        conf_norm = upstream_confidence

        features = [[fam_enc, diff_enc, pipeline_position, conf_norm]]
        features_scaled = self._scaler.transform(features)

        pred = self._clf.predict(features_scaled)[0]
        probs = self._clf.predict_proba(features_scaled)[0]

        model = MODEL_NAMES[pred]
        prob = probs[pred]

        # Confidence interval from class probabilities
        ci_low = max(0, prob - 0.15)
        ci_high = min(1, prob + 0.15)

        from router.cost_model import compute_expected_cost, MODEL_COSTS
        cost = compute_expected_cost(MODEL_COSTS.get(model, 1e-6), prob)

        reasoning = (
            f"LogReg predicts {model} (P={prob:.2f}) for "
            f"{task_family}/{complexity}/pos={pipeline_position}/upstream_conf={upstream_confidence:.1f}. "
            f"Expected cost: ${cost:.8f}."
        )

        return RoutingDecision(
            recommended_model=model,
            expected_cost=cost,
            confidence_interval=(ci_low, ci_high),
            reasoning=reasoning,
        )


def main() -> int:
    """Train the CACR router from stdin JSONL or BQ, then print comparison."""
    def _load_dotenv(path: str) -> None:
        if not os.path.exists(path):
            return
        with open(path) as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k, v = k.strip(), v.strip().strip('"').strip("'")
                if k and v:
                    os.environ.setdefault(k, v)
    _load_dotenv(os.path.join(_ROOT, ".env"))

    # Read JSONL from stdin
    lines = []
    if not sys.stdin.isatty():
        for raw in sys.stdin:
            try:
                lines.append(json.loads(raw))
            except json.JSONDecodeError:
                pass

    if not lines:
        print("Pipe runner.py output to stdin to train.", file=sys.stderr)
        return 1

    # Train
    router = CACRRouter()
    router.fit(lines)
    print("CACR router trained and saved to router/cacr_router.pkl")

    # Compare with lookup
    lookup = LookupTableRouter()
    print("\nRouting comparison:")
    for task_family, complexity in [("classification", "easy"), ("classification", "hard"), ("generation", "medium")]:
        cacr_dec = router.route("test", task_family, complexity)
        print(f"  {task_family}/{complexity}: CACR → {cacr_dec.recommended_model} ({cacr_dec.reasoning[:80]})")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
