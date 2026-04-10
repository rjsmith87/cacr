"""Code summarization task.

Given a Python function, produce a one-sentence summary.
Scored using ROUGE-L (longest common subsequence) F1 against a reference.
"""

from typing import Any

from tasks.base import Task


def _tokenize(text: str) -> list[str]:
    """Lowercase word-level tokenization."""
    return text.lower().split()


def _lcs_length(a: list[str], b: list[str]) -> int:
    """Length of the longest common subsequence."""
    m, n = len(a), len(b)
    prev = [0] * (n + 1)
    for i in range(1, m + 1):
        curr = [0] * (n + 1)
        for j in range(1, n + 1):
            if a[i - 1] == b[j - 1]:
                curr[j] = prev[j - 1] + 1
            else:
                curr[j] = max(prev[j], curr[j - 1])
        prev = curr
    return prev[n]


def rouge_l(hypothesis: str, reference: str) -> float:
    """ROUGE-L F1 score between two strings."""
    hyp_tok = _tokenize(hypothesis)
    ref_tok = _tokenize(reference)
    if not hyp_tok or not ref_tok:
        return 0.0
    lcs = _lcs_length(hyp_tok, ref_tok)
    precision = lcs / len(hyp_tok)
    recall = lcs / len(ref_tok)
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


EXAMPLES = [
    # --- easy ---
    {
        "complexity": "easy",
        "code": '''\
def add(a, b):
    return a + b
''',
        "reference": "Returns the sum of two numbers.",
    },
    {
        "complexity": "easy",
        "code": '''\
def is_empty(lst):
    return len(lst) == 0
''',
        "reference": "Checks whether a list is empty.",
    },
    {
        "complexity": "easy",
        "code": '''\
def to_upper(s):
    return s.upper()
''',
        "reference": "Converts a string to uppercase.",
    },
    # --- medium ---
    {
        "complexity": "medium",
        "code": '''\
def fibonacci(n):
    if n <= 1:
        return n
    a, b = 0, 1
    for _ in range(2, n + 1):
        a, b = b, a + b
    return b
''',
        "reference": "Computes the nth Fibonacci number iteratively.",
    },
    {
        "complexity": "medium",
        "code": '''\
def flatten(nested):
    result = []
    for item in nested:
        if isinstance(item, list):
            result.extend(flatten(item))
        else:
            result.append(item)
    return result
''',
        "reference": "Recursively flattens a nested list into a single list.",
    },
    {
        "complexity": "medium",
        "code": '''\
def memoize(func):
    cache = {}
    def wrapper(*args):
        if args not in cache:
            cache[args] = func(*args)
        return cache[args]
    return wrapper
''',
        "reference": "A decorator that caches function results based on arguments.",
    },
    {
        "complexity": "medium",
        "code": '''\
def chunk(lst, size):
    return [lst[i:i + size] for i in range(0, len(lst), size)]
''',
        "reference": "Splits a list into chunks of a given size.",
    },
    # --- hard ---
    {
        "complexity": "hard",
        "code": '''\
def lru_evict(cache, capacity):
    if len(cache) <= capacity:
        return cache
    sorted_keys = sorted(cache, key=lambda k: cache[k]["last_access"])
    while len(cache) > capacity:
        del cache[sorted_keys.pop(0)]
    return cache
''',
        "reference": "Evicts the least recently used entries from a cache dict until it is within capacity.",
    },
    {
        "complexity": "hard",
        "code": '''\
def topological_sort(graph):
    visited = set()
    stack = []
    def dfs(node):
        visited.add(node)
        for neighbor in graph.get(node, []):
            if neighbor not in visited:
                dfs(neighbor)
        stack.append(node)
    for node in graph:
        if node not in visited:
            dfs(node)
    return stack[::-1]
''',
        "reference": "Performs a topological sort on a directed acyclic graph using depth-first search.",
    },
    {
        "complexity": "hard",
        "code": '''\
def rate_limit(max_calls, period):
    timestamps = []
    def decorator(func):
        def wrapper(*args, **kwargs):
            import time
            now = time.time()
            timestamps[:] = [t for t in timestamps if now - t < period]
            if len(timestamps) >= max_calls:
                raise RuntimeError("Rate limit exceeded")
            timestamps.append(now)
            return func(*args, **kwargs)
        return wrapper
    return decorator
''',
        "reference": "A decorator factory that enforces a rate limit on function calls within a sliding time window.",
    },
]


class CodeSummarization(Task):
    family = "generation"
    complexity = "mixed"
    threshold = 0.4

    def examples(self) -> list[dict[str, Any]]:
        return EXAMPLES

    def prompt(self, example: dict[str, Any]) -> str:
        return (
            "Summarize the following Python function in exactly one sentence.\n"
            "Respond with ONLY the summary sentence, nothing else.\n\n"
            f"```python\n{example['code']}```\n"
            "Summary:"
        )

    def eval(self, example: dict[str, Any], output: str) -> float:
        # Take the first non-empty line as the summary.
        first = next((ln.strip() for ln in output.splitlines() if ln.strip()), "")
        return rouge_l(first, example["reference"])
