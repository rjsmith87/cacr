"""Code review / bug identification task.

Given a Python snippet with a known bug, the model must identify the bug type.
Categories: logic_error, null_pointer, off_by_one, resource_leak, race_condition.
Score is exact match on bug type (case-insensitive, stripped).
"""

from typing import Any

from tasks.base import Task


BUG_TYPES = ["logic_error", "null_pointer", "off_by_one", "resource_leak", "race_condition"]

EXAMPLES = [
    # ===================================================================
    # EASY (10 examples) — obvious single-line bugs
    # ===================================================================
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
def negate(flag):
    if flag:
        return True
    return True
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
def greet(cfg):
    msg = cfg.get("greeting")
    return msg.format(name="Alice")
# called with: greet({})
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
def last_element(seq):
    return seq[len(seq)]
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
    {
        "complexity": "easy",
        "code": '''\
def write_log(path, msg):
    fh = open(path, "a")
    fh.write(msg + "\\n")
''',
        "label": "resource_leak",
    },
    {
        "complexity": "easy",
        "code": '''\
import threading
counter = 0
def bump():
    global counter
    counter += 1
# bump() is called from 50 threads simultaneously
''',
        "label": "race_condition",
    },
    {
        "complexity": "easy",
        "code": '''\
shared_list = []
import threading
def append_item(x):
    shared_list.append(x)
    shared_list.sort()
# called from multiple threads concurrently
''',
        "label": "race_condition",
    },
    # ===================================================================
    # MEDIUM (10 examples) — subtle bugs requiring reading 3-5 lines
    # ===================================================================
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
def power(base, exp):
    if exp == 0:
        return 1
    result = base
    for _ in range(exp):
        result *= base
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
def safe_divide(mapping, key, divisor):
    value = mapping.get(key)
    if divisor == 0:
        return None
    return value / divisor
# called with a key that doesn't exist in mapping
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
    {
        "complexity": "medium",
        "code": '''\
def sliding_window_max(nums, k):
    results = []
    for i in range(len(nums) - k):
        window = nums[i:i + k]
        results.append(max(window))
    return results
''',
        "label": "off_by_one",
    },
    {
        "complexity": "medium",
        "code": '''\
def download_all(urls):
    import urllib.request
    results = []
    for url in urls:
        resp = urllib.request.urlopen(url)
        results.append(resp.read())
    return results
''',
        "label": "resource_leak",
    },
    {
        "complexity": "medium",
        "code": '''\
import socket
def check_port(host, port):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    result = s.connect_ex((host, port))
    return result == 0
''',
        "label": "resource_leak",
    },
    {
        "complexity": "medium",
        "code": '''\
import threading

class LazyLoader:
    def __init__(self):
        self._cache = None

    def get(self, loader_fn):
        if self._cache is None:
            self._cache = loader_fn()
        return self._cache
# get() is called from multiple threads
''',
        "label": "race_condition",
    },
    {
        "complexity": "medium",
        "code": '''\
import threading

registry = {}
lock = threading.Lock()

def register(name, obj):
    with lock:
        registry[name] = obj

def get_or_create(name, factory):
    if name not in registry:
        register(name, factory())
    return registry[name]
# get_or_create called from multiple threads
''',
        "label": "race_condition",
    },
    # ===================================================================
    # HARD (10 examples) — obfuscated names, multi-line reasoning
    # ===================================================================
    {
        "complexity": "hard",
        "code": '''\
def _agg(seqs, fn):
    buf = []
    for s in seqs:
        for rec in s.get("items", []):
            v = rec.get("val")
            if v:
                buf.append(v)
    return fn(buf) / len(buf)
# _agg([{"items": [{"val": 0}, {"val": 5}]}], sum)
# Bug: `if v` filters out 0 and 0.0, skewing the result
''',
        "label": "logic_error",
    },
    {
        "complexity": "hard",
        "code": '''\
def _dedup(xs):
    seen = set()
    out = []
    for x in xs:
        h = hash(x)
        if h not in seen:
            seen.add(h)
            out.append(x)
    return out
# Bug: hash collisions mean distinct objects with same hash
# are silently dropped — dedup is based on hash, not equality
''',
        "label": "logic_error",
    },
    {
        "complexity": "hard",
        "code": '''\
def _parse(raw):
    parts = raw.strip().split(";")
    cfg = {}
    for p in parts:
        k, v = p.split("=")
        cfg[k.strip()] = v.strip()
    head = cfg.get("host")
    return head.upper()
# called with raw = "port=8080;timeout=30"
# head is None because "host" key is absent
''',
        "label": "null_pointer",
    },
    {
        "complexity": "hard",
        "code": '''\
class _Node:
    __slots__ = ("v", "nxt")
    def __init__(self, v, nxt=None):
        self.v = v
        self.nxt = nxt

def _tail(nd):
    _r = nd
    while _r.nxt:
        _r = _r.nxt
    return _r.nxt.v
# After the loop _r.nxt is None, so .v raises AttributeError
''',
        "label": "null_pointer",
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
# 7 items with sz=3 => total_pages returns 2, but page(2) has 1 item
# Should be ceil division; page 3 is silently lost
''',
        "label": "off_by_one",
    },
    {
        "complexity": "hard",
        "code": '''\
def _chunk(buf, w):
    out = []
    i = 0
    while i < len(buf):
        out.append(buf[i:i + w])
        i += w
    return out

def _proc(data, w):
    cs = _chunk(data, w)
    for idx in range(1, len(cs)):
        cs[idx] = cs[idx - 1] + cs[idx]
    return cs
# _proc("abcdefg", 3) skips processing cs[0] entirely,
# first chunk is never prefixed — range should start at 0
# but then cs[idx-1] would be cs[-1], a different bug
# The real issue: range(1, len(cs)) loses the first chunk transform
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
# NamedTemporaryFile with delete=False is never closed or unlinked
''',
        "label": "resource_leak",
    },
    {
        "complexity": "hard",
        "code": '''\
import sqlite3

def _q(db, flt):
    conn = sqlite3.connect(db)
    cur = conn.cursor()
    cur.execute("SELECT * FROM t WHERE active=1")
    rows = cur.fetchall()
    if not flt:
        raise ValueError("empty filter")
    return [r for r in rows if r[1] in flt]
# When flt is empty the exception is raised and conn is never closed
''',
        "label": "resource_leak",
    },
    {
        "complexity": "hard",
        "code": '''\
import threading

_bal = 0

def _xfer(amt):
    global _bal
    tmp = _bal
    tmp += amt
    _bal = tmp

ts = [threading.Thread(target=_xfer, args=(100,)) for _ in range(10)]
for t in ts:
    t.start()
for t in ts:
    t.join()
# read-modify-write without lock; final _bal may be < 1000
''',
        "label": "race_condition",
    },
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
# Check-then-act outside the lock: two threads may both miss
# the cache and call fn(k) concurrently
''',
        "label": "race_condition",
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
