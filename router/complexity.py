"""Automatic complexity inference from code snippets.

Uses static heuristics with weighted voting:
  - Lines of code
  - Cyclomatic complexity proxy (control flow keywords)
  - Nesting depth of control-flow blocks (if/for/while/try inside each other)
  - Recursion (direct or mutual among defined functions)
  - Dangerous pattern detection (os.system, pickle, eval, etc.)
  - Import count

Each signal casts a weighted vote for easy/medium/hard. Majority wins.
Dangerous patterns are a hard override regardless of other signals.

The previous version was over-indexed on the dangerous-pattern keyword
override and missed structural complexity entirely — a 50-line
recursive-descent parser with depth-3 nesting was inferring as easy
because it had no dangerous keywords and a low control-flow count when
those keywords were spread across multiple short functions. The
rebalanced LOC thresholds (30 / 60 instead of 20 / 50) plus explicit
recursion and nesting signals fix that case without disturbing the
trivial / dangerous-override paths.
"""

import re


_CONTROL_FLOW = re.compile(
    r"\b(if|elif|else|for|while|try|except|finally|with|assert)\b"
)

# Same set as _CONTROL_FLOW but anchored to a leading-indent context so
# we can measure nesting depth from the indent of the matched keyword.
_CONTROL_FLOW_INDENTED = re.compile(
    r"^([ \t]+)(if|elif|else|for|while|try|except|finally|with)\b",
    re.MULTILINE,
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

_DEF = re.compile(r"^\s*(?:async\s+)?def\s+(\w+)\s*\(", re.MULTILINE)


def _max_nesting_depth(code: str) -> int:
    """Approximate the deepest indent level of any control-flow keyword,
    measured in 4-space units. Tabs are expanded to 4 spaces."""
    max_depth = 0
    for m in _CONTROL_FLOW_INDENTED.finditer(code):
        indent = m.group(1).expandtabs(4)
        depth = len(indent) // 4
        if depth > max_depth:
            max_depth = depth
    return max_depth


def _has_recursion(code: str) -> bool:
    """Detect any recursion among defined functions — direct, 2-cycle
    mutual, or longer cycles (parse_expr → parse_term → parse_factor →
    parse_expr is the canonical recursive-descent shape).

    Builds a call graph over the function names defined in `code` and
    runs a DFS that flags any back-edge as a cycle. Self-calls are
    detected as length-1 cycles by the same machinery.
    """
    defs = list(_DEF.finditer(code))
    if not defs:
        return False

    # Carve out each function's body span (def line through next def or EOF).
    bodies: list[tuple[str, str]] = []
    for i, m in enumerate(defs):
        body_start = m.end()
        body_end = defs[i + 1].start() if i + 1 < len(defs) else len(code)
        bodies.append((m.group(1), code[body_start:body_end]))

    fn_names = {name for name, _ in bodies}
    calls: dict[str, set[str]] = {}
    for name, body in bodies:
        # Include self in the candidate set so a function calling its own
        # name shows up as a self-loop in the graph.
        called = {
            other for other in fn_names
            if re.search(rf"\b{re.escape(other)}\s*\(", body)
        }
        calls[name] = called

    # Standard 3-color DFS for cycle detection.
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {n: WHITE for n in fn_names}

    def dfs(n: str) -> bool:
        color[n] = GRAY
        for nb in calls.get(n, ()):
            if color.get(nb) == GRAY:
                return True
            if color.get(nb) == WHITE and dfs(nb):
                return True
        color[n] = BLACK
        return False

    for n in fn_names:
        if color[n] == WHITE and dfs(n):
            return True
    return False


def infer_complexity(code: str) -> str:
    """Infer easy/medium/hard from a code snippet using static heuristics."""

    lines = [ln for ln in code.splitlines() if ln.strip() and not ln.strip().startswith("#")]
    loc = len(lines)

    cf_count = len(_CONTROL_FLOW.findall(code))
    has_dangerous = bool(_DANGEROUS.search(code))
    import_count = len(_IMPORT_LINE.findall(code))
    nesting = _max_nesting_depth(code)
    is_recursive = _has_recursion(code)

    # Dangerous patterns are a hard override — they're always sensitive
    # regardless of how short or simple the surrounding code is.
    if has_dangerous:
        return "hard"

    votes = {"easy": 0, "medium": 0, "hard": 0}

    # LOC signal (weight 2). Thresholds bumped from 20/50 to 30/60
    # because the 50-line recursive-descent parser the previous version
    # got wrong was sitting right at the old boundary and underweighted.
    if loc < 30:
        votes["easy"] += 2
    elif loc <= 60:
        votes["medium"] += 2
    else:
        votes["hard"] += 2

    # Cyclomatic complexity proxy (weight 3).
    if cf_count < 3:
        votes["easy"] += 3
    elif cf_count <= 7:
        votes["medium"] += 3
    else:
        votes["hard"] += 3

    # Import count (weight 1).
    if import_count < 3:
        votes["easy"] += 1
    elif import_count <= 6:
        votes["medium"] += 1
    else:
        votes["hard"] += 1

    # Recursion (weight 3). Direct or mutual recursion is a strong
    # signal that the code is non-trivial to reason about.
    if is_recursive:
        votes["hard"] += 3

    # Nesting depth (weight 3 at depth ≥3, weight 2 at depth 2). Three
    # levels of if/for/while/try inside each other is the classic shape
    # of code that's hard to follow line-by-line.
    if nesting >= 3:
        votes["hard"] += 3
    elif nesting == 2:
        votes["medium"] += 2

    return max(votes, key=votes.get)
