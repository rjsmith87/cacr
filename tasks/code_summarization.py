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
    # ---- easy (10) ----
    {
        "complexity": "easy",
        "code": '''\
def add(a, b):
    return a + b
''',
        "reference": "Returns the arithmetic sum of two given numbers.",
    },
    {
        "complexity": "easy",
        "code": '''\
def is_empty(lst):
    return len(lst) == 0
''',
        "reference": "Checks whether a given list contains no elements.",
    },
    {
        "complexity": "easy",
        "code": '''\
def to_upper(s):
    return s.upper()
''',
        "reference": "Converts all characters in a string to uppercase.",
    },
    {
        "complexity": "easy",
        "code": '''\
def max_of_three(a, b, c):
    return max(a, b, c)
''',
        "reference": "Returns the maximum value among three given inputs.",
    },
    {
        "complexity": "easy",
        "code": '''\
def square(n):
    return n * n
''',
        "reference": "Returns the square of a given number by multiplication.",
    },
    {
        "complexity": "easy",
        "code": '''\
def greet(name):
    return f"Hello, {name}!"
''',
        "reference": "Returns a greeting string for the given name.",
    },
    {
        "complexity": "easy",
        "code": '''\
def is_even(n):
    return n % 2 == 0
''',
        "reference": "Checks whether a given integer is an even number.",
    },
    {
        "complexity": "easy",
        "code": '''\
def first_element(lst):
    return lst[0]
''',
        "reference": "Returns the first element of a given list.",
    },
    {
        "complexity": "easy",
        "code": '''\
def reverse_string(s):
    return s[::-1]
''',
        "reference": "Returns a new string with characters in reverse order.",
    },
    {
        "complexity": "easy",
        "code": '''\
def absolute(n):
    return n if n >= 0 else -n
''',
        "reference": "Returns the absolute value of a given number.",
    },
    # ---- medium (10) ----
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
        "reference": "Computes the nth Fibonacci number using an iterative approach.",
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
        "reference": "Decorator that caches function results based on arguments.",
    },
    {
        "complexity": "medium",
        "code": '''\
def binary_search(arr, target):
    lo, hi = 0, len(arr) - 1
    while lo <= hi:
        mid = (lo + hi) // 2
        if arr[mid] == target:
            return mid
        elif arr[mid] < target:
            lo = mid + 1
        else:
            hi = mid - 1
    return -1
''',
        "reference": "Performs binary search on a sorted list and returns the index.",
    },
    {
        "complexity": "medium",
        "code": '''\
def merge_sort(lst):
    if len(lst) <= 1:
        return lst
    mid = len(lst) // 2
    left = merge_sort(lst[:mid])
    right = merge_sort(lst[mid:])
    merged = []
    i = j = 0
    while i < len(left) and j < len(right):
        if left[i] <= right[j]:
            merged.append(left[i])
            i += 1
        else:
            merged.append(right[j])
            j += 1
    merged.extend(left[i:])
    merged.extend(right[j:])
    return merged
''',
        "reference": "Sorts a list using the merge sort algorithm.",
    },
    {
        "complexity": "medium",
        "code": '''\
def chunk(lst, size):
    return [lst[i:i + size] for i in range(0, len(lst), size)]
''',
        "reference": "Splits a list into chunks of a given size.",
    },
    {
        "complexity": "medium",
        "code": '''\
def unique(lst):
    seen = set()
    result = []
    for item in lst:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result
''',
        "reference": "Returns a list with duplicates removed preserving order.",
    },
    {
        "complexity": "medium",
        "code": '''\
def transpose(matrix):
    if not matrix:
        return []
    rows, cols = len(matrix), len(matrix[0])
    result = []
    for c in range(cols):
        row = []
        for r in range(rows):
            row.append(matrix[r][c])
        result.append(row)
    return result
''',
        "reference": "Transposes a two-dimensional matrix swapping rows and columns.",
    },
    {
        "complexity": "medium",
        "code": '''\
def count_words(text):
    counts = {}
    for word in text.lower().split():
        word = word.strip(".,!?;:")
        counts[word] = counts.get(word, 0) + 1
    return counts
''',
        "reference": "Counts the frequency of each word in a text string.",
    },
    {
        "complexity": "medium",
        "code": '''\
def is_palindrome(s):
    cleaned = ''.join(c.lower() for c in s if c.isalnum())
    left, right = 0, len(cleaned) - 1
    while left < right:
        if cleaned[left] != cleaned[right]:
            return False
        left += 1
        right -= 1
    return True
''',
        "reference": "Checks whether a string is a palindrome ignoring case and punctuation.",
    },
    # ---- hard (10) ----
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
        "reference": "Parses a flat list of tokens with parentheses into a nested structure.",
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
def topo(g):
    v = set()
    stk = []
    def _d(n):
        v.add(n)
        for nb in g.get(n, []):
            if nb not in v:
                _d(nb)
        stk.append(n)
    for n in g:
        if n not in v:
            _d(n)
    return stk[::-1]
''',
        "reference": "Performs topological sort on a directed acyclic graph using depth-first search.",
    },
    {
        "complexity": "hard",
        "code": '''\
def lru(cap):
    from collections import OrderedDict
    c = OrderedDict()
    def get(k):
        if k not in c:
            return -1
        c.move_to_end(k)
        return c[k]
    def put(k, v):
        if k in c:
            c.move_to_end(k)
        c[k] = v
        if len(c) > cap:
            c.popitem(last=False)
    return get, put
''',
        "reference": "Implements an LRU cache with get and put operations using ordered dict.",
    },
    {
        "complexity": "hard",
        "code": '''\
def ed(a, b):
    m, n = len(a), len(b)
    dp = [[0] * (n + 1) for _ in range(m + 1)]
    for i in range(m + 1):
        dp[i][0] = i
    for j in range(n + 1):
        dp[0][j] = j
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            if a[i-1] == b[j-1]:
                dp[i][j] = dp[i-1][j-1]
            else:
                dp[i][j] = 1 + min(dp[i-1][j], dp[i][j-1], dp[i-1][j-1])
    return dp[m][n]
''',
        "reference": "Computes the edit distance between two strings using dynamic programming.",
    },
    {
        "complexity": "hard",
        "code": '''\
def dij(g, src):
    import heapq
    d = {src: 0}
    pq = [(0, src)]
    vis = set()
    while pq:
        cd, u = heapq.heappop(pq)
        if u in vis:
            continue
        vis.add(u)
        for v, w in g.get(u, []):
            nd = cd + w
            if nd < d.get(v, float('inf')):
                d[v] = nd
                heapq.heappush(pq, (nd, v))
    return d
''',
        "reference": "Finds shortest paths from a source node using Dijkstra's algorithm.",
    },
    {
        "complexity": "hard",
        "code": '''\
def ks(W, wt, vl):
    n = len(wt)
    dp = [[0] * (W + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        for w in range(W + 1):
            if wt[i-1] <= w:
                dp[i][w] = max(dp[i-1][w], dp[i-1][w - wt[i-1]] + vl[i-1])
            else:
                dp[i][w] = dp[i-1][w]
    return dp[n][W]
''',
        "reference": "Solves the 0-1 knapsack problem using dynamic programming.",
    },
    {
        "complexity": "hard",
        "code": '''\
def conv(sg, k):
    ks = len(k)
    n = len(sg)
    out = [0.0] * n
    hk = ks // 2
    for i in range(n):
        acc = 0.0
        for j in range(ks):
            idx = i - hk + j
            if 0 <= idx < n:
                acc += sg[idx] * k[j]
        out[i] = acc
    return out
''',
        "reference": "Applies a one-dimensional convolution of a signal with a kernel.",
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
