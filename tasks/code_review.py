"""Code review / bug identification task.

Given a Python snippet with a known bug, the model must identify the bug type.
Categories: logic_error, null_pointer, off_by_one, resource_leak, race_condition.
Score is exact match on bug type (case-insensitive, stripped).
"""

from typing import Any

from tasks.base import Task


BUG_TYPES = ["logic_error", "null_pointer", "off_by_one", "resource_leak", "race_condition"]

EXAMPLES = [
    # --- easy (obvious bugs) ---
    {
        "complexity": "easy",
        "code": '''\
def is_even(n):
    return n % 2 == 1
''',
        "label": "logic_error",
    },
    {
        "complexity": "easy",
        "code": '''\
def get_name(user):
    return user["name"].upper()
# called with: get_name(None)
''',
        "label": "null_pointer",
    },
    {
        "complexity": "easy",
        "code": '''\
def first_n(items, n):
    result = []
    for i in range(1, n):
        result.append(items[i])
    return result
''',
        "label": "off_by_one",
    },
    {
        "complexity": "easy",
        "code": '''\
def read_config(path):
    f = open(path)
    data = f.read()
    return data
''',
        "label": "resource_leak",
    },
    # --- medium (subtle bugs) ---
    {
        "complexity": "medium",
        "code": '''\
def merge_sorted(a, b):
    result = []
    i = j = 0
    while i < len(a) and j < len(b):
        if a[i] <= b[j]:
            result.append(a[i])
            i += 1
        else:
            result.append(b[j])
            j += 1
    return result
''',
        "label": "logic_error",
    },
    {
        "complexity": "medium",
        "code": '''\
def find_parent(node):
    current = node
    while current.parent is not None:
        current = current.parent
    return current.parent.value
''',
        "label": "null_pointer",
    },
    {
        "complexity": "medium",
        "code": '''\
def binary_search(arr, target):
    lo, hi = 0, len(arr)
    while lo < hi:
        mid = (lo + hi) // 2
        if arr[mid] == target:
            return mid
        elif arr[mid] < target:
            lo = mid
        else:
            hi = mid
    return -1
''',
        "label": "off_by_one",
    },
    # --- hard (multi-line reasoning) ---
    {
        "complexity": "hard",
        "code": '''\
import threading

balance = 0

def deposit(amount):
    global balance
    current = balance
    current += amount
    balance = current

threads = [threading.Thread(target=deposit, args=(100,)) for _ in range(10)]
for t in threads:
    t.start()
for t in threads:
    t.join()
''',
        "label": "race_condition",
    },
    {
        "complexity": "hard",
        "code": '''\
import sqlite3

def get_users(db_path, filters):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users")
    rows = cursor.fetchall()
    if not filters:
        raise ValueError("filters required")
    return [r for r in rows if r[1] in filters]
''',
        "label": "resource_leak",
    },
    {
        "complexity": "hard",
        "code": '''\
def flatten(nested):
    result = []
    stack = list(nested)
    while stack:
        item = stack.pop(0)
        if isinstance(item, list):
            for sub in item:
                stack.append(sub)
        else:
            result.append(item)
    return result
# Bug: flatten([[1,2],[3,[4,5]]]) returns [1,2,3,4,5] but
# flatten([[3,[4,5]],[1,2]]) returns [3,4,5,1,2] — order depends
# on input nesting, not original position after unnesting.
''',
        "label": "logic_error",
    },
    # --- 5 additional hard examples ---
    {
        "complexity": "hard",
        "code": '''\
import threading

_c = {}
_lk = threading.Lock()

def cached_get(k, fn):
    if k in _c:
        return _c[k]
    with _lk:
        _c[k] = fn(k)
    return _c[k]
''',
        "label": "race_condition",
    },
    {
        "complexity": "hard",
        "code": '''\
class Paginator:
    def __init__(self, qs, sz):
        self._qs = qs
        self._sz = sz

    def page(self, n):
        s = n * self._sz
        e = s + self._sz
        return self._qs[s:e]

    def total_pages(self):
        return len(self._qs) // self._sz
''',
        "label": "off_by_one",
    },
    {
        "complexity": "hard",
        "code": '''\
import tempfile, json

def xform(recs):
    out = []
    for r in recs:
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
        json.dump(r, tmp)
        tmp.flush()
        with open(tmp.name) as f:
            out.append(json.load(f))
    return out
''',
        "label": "resource_leak",
    },
    {
        "complexity": "hard",
        "code": '''\
def _cmp(a, b):
    if a is None and b is None:
        return 0
    return (a > b) - (a < b)

def sort_nullable(items):
    return sorted(items, key=lambda x: (x is None, x))
# called with sort_nullable([3, None, 1, None, 2])
# _cmp is defined but the actual sort uses a lambda that will
# raise TypeError when comparing None with int via <
''',
        "label": "null_pointer",
    },
    {
        "complexity": "hard",
        "code": '''\
def avg_nested(data, key):
    vals = []
    for grp in data:
        for rec in grp.get("items", []):
            v = rec.get(key)
            if v:
                vals.append(v)
    return sum(vals) / len(vals)
# Bug: `if v` filters out 0 and 0.0, which are valid numeric values
# that should be included in the average.
''',
        "label": "logic_error",
    },
]


class CodeReview(Task):
    family = "classification"
    complexity = "mixed"
    threshold = 0.6

    def examples(self) -> list[dict[str, Any]]:
        return EXAMPLES

    def prompt(self, example: dict[str, Any]) -> str:
        cats = ", ".join(BUG_TYPES)
        return (
            "Review the following Python code and identify the bug type.\n"
            f"Bug types: {cats}\n"
            "Respond with ONLY the bug type, nothing else.\n\n"
            f"```python\n{example['code']}```\n"
            "Bug type:"
        )

    def eval(self, example: dict[str, Any], output: str) -> float:
        first = next((ln.strip() for ln in output.splitlines() if ln.strip()), "")
        guess = first.lower().strip(" .,:;\"'`*")
        return 1.0 if guess == example["label"] else 0.0
