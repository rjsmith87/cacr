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
    # --- 5 additional hard examples ---
    {
        "complexity": "hard",
        "code": '''\
def retry(fn, mx=3, bk=1.0):
    import time
    for i in range(mx):
        try:
            return fn()
        except Exception:
            if i == mx - 1:
                raise
            time.sleep(bk * (2 ** i))
''',
        "reference": "Retries a callable up to a maximum number of times with exponential backoff between attempts.",
    },
    {
        "complexity": "hard",
        "code": '''\
def dtw(s, t):
    n, m = len(s), len(t)
    dp = [[float("inf")] * (m + 1) for _ in range(n + 1)]
    dp[0][0] = 0
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            cost = abs(s[i-1] - t[j-1])
            dp[i][j] = cost + min(dp[i-1][j], dp[i][j-1], dp[i-1][j-1])
    return dp[n][m]
''',
        "reference": "Computes the dynamic time warping distance between two numeric sequences.",
    },
    {
        "complexity": "hard",
        "code": '''\
class RB:
    def __init__(self, cap):
        self._b = [None] * cap
        self._h = 0
        self._t = 0
        self._n = 0
        self._c = cap

    def push(self, v):
        if self._n == self._c:
            raise OverflowError
        self._b[self._t] = v
        self._t = (self._t + 1) % self._c
        self._n += 1

    def pop(self):
        if self._n == 0:
            raise IndexError
        v = self._b[self._h]
        self._h = (self._h + 1) % self._c
        self._n -= 1
        return v
''',
        "reference": "Implements a fixed-capacity circular ring buffer with push and pop operations.",
    },
    {
        "complexity": "hard",
        "code": '''\
def par(tks):
    stk = []
    for t in tks:
        if t == "(":
            stk.append([])
        elif t == ")":
            inner = stk.pop()
            if stk:
                stk[-1].append(inner)
            else:
                return inner
        else:
            if stk:
                stk[-1].append(t)
    return stk[0] if stk else []
''',
        "reference": "Parses a flat list of tokens with parentheses into a nested list structure.",
    },
    {
        "complexity": "hard",
        "code": '''\
def crc32(data: bytes) -> int:
    crc = 0xFFFFFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0xEDB88320
            else:
                crc >>= 1
    return crc ^ 0xFFFFFFFF
''',
        "reference": "Computes a CRC-32 checksum for a bytes object using the standard polynomial.",
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
