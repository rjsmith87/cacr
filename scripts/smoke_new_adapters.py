"""Smoke-test the 4 new frontier adapters on one CodeReview/easy example.

Prints output + per-call usage (prompt/completion/reasoning tokens) so we
can extrapolate full-run cost. Does NOT touch BigQuery and does not run
the confidence probe — intentionally minimal to keep spend small.
"""

import os
import sys
import time
import traceback

# Reuse the runner's tiny dotenv loader.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from runner import _load_dotenv  # noqa: E402

_load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

from anthropic import Anthropic  # noqa: E402
from openai import OpenAI  # noqa: E402
from google import genai  # noqa: E402

from models.claude_opus_adapter import ClaudeOpus  # noqa: E402
from models.gemini_pro_adapter import GeminiPro  # noqa: E402
from models.gpt5_adapter import GPT5  # noqa: E402
from models.o3_adapter import O3  # noqa: E402
from tasks.code_review import CodeReview  # noqa: E402


def _count_anthropic_tokens(text: str) -> int:
    """Rough char/4 estimate; Anthropic SDK doesn't expose a tokenizer."""
    return max(1, len(text) // 4)


def smoke_claude_opus(prompt: str) -> dict:
    adapter = ClaudeOpus()
    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    t0 = time.perf_counter()
    resp = client.messages.create(
        model="claude-opus-4-7",
        max_tokens=256,
        messages=[{"role": "user", "content": prompt}],
    )
    latency_ms = (time.perf_counter() - t0) * 1000
    text = "".join(getattr(b, "text", "") for b in resp.content).strip()
    return {
        "model": adapter.name,
        "output": text,
        "input_tokens": resp.usage.input_tokens,
        "output_tokens": resp.usage.output_tokens,
        "reasoning_tokens": 0,
        "latency_ms": round(latency_ms, 1),
    }


def smoke_gpt5(prompt: str) -> dict:
    adapter = GPT5()
    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    t0 = time.perf_counter()
    resp = client.chat.completions.create(
        model="gpt-5",
        max_completion_tokens=512,
        messages=[{"role": "user", "content": prompt}],
    )
    latency_ms = (time.perf_counter() - t0) * 1000
    details = getattr(resp.usage, "completion_tokens_details", None)
    reasoning_tokens = getattr(details, "reasoning_tokens", 0) if details else 0
    return {
        "model": adapter.name,
        "output": (resp.choices[0].message.content or "").strip(),
        "input_tokens": resp.usage.prompt_tokens,
        "output_tokens": resp.usage.completion_tokens,
        "reasoning_tokens": reasoning_tokens,
        "latency_ms": round(latency_ms, 1),
    }


def smoke_o3(prompt: str) -> dict:
    adapter = O3()
    t0 = time.perf_counter()
    text = adapter.generate(prompt)
    latency_ms = (time.perf_counter() - t0) * 1000
    return {
        "model": adapter.name,
        "output": text,
        "input_tokens": adapter.last_usage["input_tokens"],
        "output_tokens": adapter.last_usage["output_tokens"],
        "reasoning_tokens": adapter.last_usage["reasoning_tokens"],
        "latency_ms": round(latency_ms, 1),
    }


def smoke_gemini_pro(prompt: str) -> dict:
    adapter = GeminiPro()
    client = genai.Client(api_key=os.environ["GOOGLE_API_KEY"])
    t0 = time.perf_counter()
    resp = client.models.generate_content(
        model="gemini-2.5-pro",
        contents=prompt,
        config=genai.types.GenerateContentConfig(
            max_output_tokens=4096,
            temperature=0.0,
        ),
    )
    latency_ms = (time.perf_counter() - t0) * 1000
    usage = resp.usage_metadata
    return {
        "model": adapter.name,
        "output": (resp.text or "").strip(),
        "input_tokens": usage.prompt_token_count,
        "output_tokens": usage.candidates_token_count or 0,
        "reasoning_tokens": getattr(usage, "thoughts_token_count", 0) or 0,
        "latency_ms": round(latency_ms, 1),
    }


def main() -> int:
    task = CodeReview()
    example = task.examples()[0]  # First easy example: is_even logic_error
    prompt = task.prompt(example)
    gold = example["label"]
    print(f"=== Smoke test ===")
    print(f"Task: CodeReview / easy / gold={gold}")
    print(f"Prompt length: {len(prompt)} chars\n")

    runners = [
        ("claude-opus-4-7", smoke_claude_opus),
        ("gpt-5", smoke_gpt5),
        ("o3", smoke_o3),
        ("gemini-2.5-pro", smoke_gemini_pro),
    ]

    results = []
    for label, fn in runners:
        print(f"--- {label} ---")
        try:
            r = fn(prompt)
            r["correct"] = task.eval(example, r["output"]) == 1.0
            results.append(r)
            print(f"  output:    {r['output']!r}")
            print(f"  correct:   {r['correct']}")
            print(f"  in/out/reason tokens: {r['input_tokens']}/{r['output_tokens']}/{r['reasoning_tokens']}")
            print(f"  latency:   {r['latency_ms']} ms\n")
        except Exception as exc:  # noqa: BLE001
            print(f"  ERROR: {type(exc).__name__}: {exc}")
            traceback.print_exc()
            results.append({"model": label, "error": f"{type(exc).__name__}: {exc}"})
            print()

    print("=== Summary (machine-readable) ===")
    import json
    print(json.dumps(results, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
