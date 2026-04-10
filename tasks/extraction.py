"""JSON extraction task.

The model is given freeform text and asked to return a JSON object
matching a fixed schema. Score is per-field: fraction of required
fields that parse and match the gold value (case-insensitive for strings).
"""

import json
import re
from typing import Any

from tasks.base import Task


# Required fields. Types are str unless noted; "amount" is a number.
SCHEMA_FIELDS = ["name", "email", "amount", "date"]


def _extract_json(text: str) -> dict[str, Any] | None:
    """Best-effort: find the first {...} block and json.loads it."""
    # Strip code fences if present.
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    candidate = fenced.group(1) if fenced else None
    if candidate is None:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        candidate = match.group(0) if match else None
    if candidate is None:
        return None
    try:
        obj = json.loads(candidate)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        return None


class JsonExtraction(Task):
    family = "extraction"
    complexity = "medium"
    threshold = 0.75

    def examples(self) -> list[dict[str, Any]]:
        return [
            {
                "text": (
                    "Hi, this is Jane Doe (jane.doe@example.com). I was charged "
                    "$129.99 on 2026-03-14 and need a receipt."
                ),
                "gold": {
                    "name": "Jane Doe",
                    "email": "jane.doe@example.com",
                    "amount": 129.99,
                    "date": "2026-03-14",
                },
            },
            {
                "text": (
                    "Order confirmation for Marcus Lee — total 45.00 USD, placed "
                    "on 2026-01-02. Contact: marcus.lee@acme.io."
                ),
                "gold": {
                    "name": "Marcus Lee",
                    "email": "marcus.lee@acme.io",
                    "amount": 45.00,
                    "date": "2026-01-02",
                },
            },
            {
                "text": (
                    "Refund issued to priya@kumar.dev (Priya Kumar) in the amount "
                    "of $12.50 on 2025-12-30."
                ),
                "gold": {
                    "name": "Priya Kumar",
                    "email": "priya@kumar.dev",
                    "amount": 12.50,
                    "date": "2025-12-30",
                },
            },
            {
                "text": (
                    "Invoice for Tomás Alvarez sent 2026-02-19. Amount due: "
                    "$1,250.00. Reply to tomas@alvarez.co."
                ),
                "gold": {
                    "name": "Tomás Alvarez",
                    "email": "tomas@alvarez.co",
                    "amount": 1250.00,
                    "date": "2026-02-19",
                },
            },
            {
                "text": (
                    "Customer Aiko Tanaka (aiko.t@nihon.jp) made a purchase of "
                    "78.20 on 2026-04-01."
                ),
                "gold": {
                    "name": "Aiko Tanaka",
                    "email": "aiko.t@nihon.jp",
                    "amount": 78.20,
                    "date": "2026-04-01",
                },
            },
        ]

    def prompt(self, example: dict[str, Any]) -> str:
        return (
            "Extract the following fields from the text below and return a JSON "
            "object with EXACTLY these keys:\n"
            "  - name (string, full person name)\n"
            "  - email (string)\n"
            "  - amount (number, no currency symbol or commas)\n"
            "  - date (string, ISO format YYYY-MM-DD)\n"
            "Return ONLY the JSON object, no prose, no code fences.\n\n"
            f"Text: {example['text']}\n"
            "JSON:"
        )

    def eval(self, example: dict[str, Any], output: str) -> float:
        obj = _extract_json(output)
        if obj is None:
            return 0.0

        gold = example["gold"]
        hits = 0
        for field in SCHEMA_FIELDS:
            if field not in obj:
                continue
            got, want = obj[field], gold[field]
            if field == "amount":
                try:
                    if abs(float(got) - float(want)) < 0.01:
                        hits += 1
                except (TypeError, ValueError):
                    pass
            else:
                if isinstance(got, str) and got.strip().lower() == str(want).strip().lower():
                    hits += 1
        return hits / len(SCHEMA_FIELDS)
