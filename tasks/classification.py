"""Intent classification task.

5 categories. Gold labels hardcoded. Metric is exact-match accuracy
(case-insensitive, stripped) over the model's first non-empty line.
"""

from typing import Any

from tasks.base import Task


CATEGORIES = ["billing", "tech_support", "sales", "account", "other"]


class IntentClassification(Task):
    family = "classification"
    complexity = "easy"
    threshold = 0.8

    def examples(self) -> list[dict[str, Any]]:
        return [
            {"text": "My credit card was charged twice this month.", "label": "billing"},
            {"text": "The app keeps crashing when I open settings.", "label": "tech_support"},
            {"text": "Do you offer a discount for annual plans?", "label": "sales"},
            {"text": "I want to change the email on my account.", "label": "account"},
            {"text": "Just wanted to say hi to the team.", "label": "other"},
            {"text": "Please refund the duplicate transaction from yesterday.", "label": "billing"},
            {"text": "I can't log in, the password reset link is broken.", "label": "tech_support"},
            {"text": "Can you send pricing for the enterprise tier?", "label": "sales"},
            {"text": "How do I delete my profile permanently?", "label": "account"},
            {"text": "Your hold music is surprisingly good.", "label": "other"},
        ]

    def prompt(self, example: dict[str, Any]) -> str:
        cats = ", ".join(CATEGORIES)
        return (
            "Classify the following customer message into exactly one category.\n"
            f"Categories: {cats}\n"
            "Respond with ONLY the category name, nothing else.\n\n"
            f"Message: {example['text']}\n"
            "Category:"
        )

    def eval(self, example: dict[str, Any], output: str) -> float:
        # Take the first non-empty line, lowercase, strip punctuation/whitespace.
        first = next((ln.strip() for ln in output.splitlines() if ln.strip()), "")
        guess = first.lower().strip(" .,:;\"'`")
        return 1.0 if guess == example["label"] else 0.0
