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


# Minimum acceptable mean_score for a model to be recommended without a warning.
# Below 0.70 the model is wrong more than 30% of the time, which is not
# acceptable for production deployment. The per-task `passes_threshold` flag in
# the cost matrix uses the task's own threshold (e.g. 0.4 for CodeSummarization)
# and let too-weak models through silently — Flash Lite at 0.42 on
# CodeSummarization was being recommended as if it were a defensible default.
# This floor is a hard global gate above the per-task threshold.
MIN_ACCEPTABLE_SCORE = 0.70


@dataclass
class RoutingDecision:
    recommended_model: str
    expected_cost: float
    confidence_interval: tuple[float, float]
    reasoning: str
    below_threshold: bool = False
    warning: str | None = None


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
        task_rows = [r for r in self._matrix if r["task"] == task]

        if not task_rows:
            # No data at all for this task — last-resort fallback.
            return RoutingDecision(
                recommended_model="claude-haiku-4-5",
                expected_cost=0.00023,
                confidence_interval=(0.0, 1.0),
                reasoning=f"No benchmark data for {task}; defaulting to Haiku.",
                below_threshold=True,
                warning=(
                    f"No benchmark data for {task}. Defaulting to claude-haiku-4-5 "
                    f"without empirical support. Consider human review."
                ),
            )

        # Acceptable = scores at or above the global minimum floor (not just the
        # per-task threshold). Below the floor we never silently recommend.
        acceptable = [r for r in task_rows if r["mean_score"] >= MIN_ACCEPTABLE_SCORE]

        if acceptable:
            best_t1 = min(acceptable, key=lambda r: r["expected_cost_usd"])

            # Escalation (preserved): if the cheapest acceptable pick is at
            # the borderline (< 0.80), check whether a higher-cost model
            # offers a meaningful accuracy bump. Triggers only when there's
            # headroom worth paying for.
            if best_t1["mean_score"] < 0.80:
                escalation = [
                    r for r in acceptable
                    if r["mean_score"] >= best_t1["mean_score"] + 0.05
                    and r.get("cost_per_token", 0) > best_t1.get("cost_per_token", 0)
                ]
                if escalation:
                    esc = min(escalation, key=lambda r: float(r.get("expected_cost_usd", 999)))
                    return RoutingDecision(
                        recommended_model=esc["model"],
                        expected_cost=float(esc["expected_cost_usd"]),
                        confidence_interval=(esc["mean_score"] - 0.1, min(1.0, esc["mean_score"] + 0.1)),
                        reasoning=(
                            f"Escalated: cheapest model meeting MIN_ACCEPTABLE_SCORE "
                            f"({MIN_ACCEPTABLE_SCORE}) was {best_t1['model']} at "
                            f"score={best_t1['mean_score']:.2f}; escalating to "
                            f"{esc['model']} for score={esc['mean_score']:.2f} "
                            f"at cost=${float(esc['expected_cost_usd']):.8f}."
                        ),
                    )

            return RoutingDecision(
                recommended_model=best_t1["model"],
                expected_cost=float(best_t1["expected_cost_usd"]),
                confidence_interval=(best_t1["mean_score"] - 0.1, min(1.0, best_t1["mean_score"] + 0.1)),
                reasoning=(
                    f"Cheapest model meeting MIN_ACCEPTABLE_SCORE "
                    f"({MIN_ACCEPTABLE_SCORE}) for {task}: {best_t1['model']} "
                    f"(score={best_t1['mean_score']:.2f}, "
                    f"cost=${float(best_t1['expected_cost_usd']):.8f})"
                ),
            )

        # All-fail path: no model on this task meets the minimum floor. Pick
        # the best available so the caller can still proceed, but flag it
        # loudly so downstream UIs can show the warning to the user.
        best_avail = max(task_rows, key=lambda r: r["mean_score"])
        warning_text = (
            f"All evaluated models score below {MIN_ACCEPTABLE_SCORE} on {task}. "
            f"Best available is {best_avail['model']} at score "
            f"{best_avail['mean_score']:.2f}. Consider human review or task "
            f"reformulation."
        )
        return RoutingDecision(
            recommended_model=best_avail["model"],
            expected_cost=float(best_avail["expected_cost_usd"]),
            confidence_interval=(
                max(0.0, best_avail["mean_score"] - 0.1),
                min(1.0, best_avail["mean_score"] + 0.1),
            ),
            reasoning=(
                f"No model meets MIN_ACCEPTABLE_SCORE ({MIN_ACCEPTABLE_SCORE}) "
                f"for {task}. Returning best available: {best_avail['model']} "
                f"at score={best_avail['mean_score']:.2f}, "
                f"cost=${float(best_avail['expected_cost_usd']):.8f}."
            ),
            below_threshold=True,
            warning=warning_text,
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

        from router.cost_model import compute_expected_cost, _rates_for
        input_cost, output_cost = _rates_for(model)
        cost = compute_expected_cost(input_cost, output_cost, prob)

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
