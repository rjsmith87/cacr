"""Automatic complexity inference from code snippets.

Uses static heuristics with weighted voting:
  - Lines of code
  - Cyclomatic complexity proxy (control flow keywords)
  - Dangerous pattern detection (os.system, pickle, eval, etc.)
  - Import count

Each signal votes easy/medium/hard. Majority wins.
Dangerous patterns override to hard regardless of other signals.
"""

import re


_CONTROL_FLOW = re.compile(
    r"\b(if|elif|else|for|while|try|except|finally|with|assert)\b"
)

_DANGEROUS = re.compile(
    r"\b(os\.system|subprocess\.(call|run|Popen|check_output)"
    r"|pickle\.(loads?|dumps?)"
    r"|eval\s*\(|exec\s*\("
    r"|__import__"
    r"|yaml\.load\b"
    r"|shelve\.open)"
    r"|f['\"]SELECT\b|f['\"]INSERT\b|f['\"]UPDATE\b|f['\"]DELETE\b"
    r"|\+\s*['\"].*(?:SELECT|INSERT|UPDATE|DELETE)",
    re.IGNORECASE,
)

_IMPORT_LINE = re.compile(r"^\s*(?:import |from \S+ import )", re.MULTILINE)


def infer_complexity(code: str) -> str:
    """Infer easy/medium/hard from a code snippet using static heuristics."""

    lines = [ln for ln in code.splitlines() if ln.strip() and not ln.strip().startswith("#")]
    loc = len(lines)

    cf_count = len(_CONTROL_FLOW.findall(code))

    has_dangerous = bool(_DANGEROUS.search(code))

    import_count = len(_IMPORT_LINE.findall(code))

    # --- Dangerous patterns override to hard ---
    if has_dangerous:
        return "hard"

    # --- Weighted vote: each signal casts easy/medium/hard ---
    votes = {"easy": 0, "medium": 0, "hard": 0}

    # LOC signal (weight 2)
    if loc < 20:
        votes["easy"] += 2
    elif loc <= 50:
        votes["medium"] += 2
    else:
        votes["hard"] += 2

    # Cyclomatic complexity proxy (weight 3 — strongest signal)
    if cf_count < 3:
        votes["easy"] += 3
    elif cf_count <= 7:
        votes["medium"] += 3
    else:
        votes["hard"] += 3

    # Import count (weight 1)
    if import_count < 3:
        votes["easy"] += 1
    elif import_count <= 6:
        votes["medium"] += 1
    else:
        votes["hard"] += 1

    return max(votes, key=votes.get)
