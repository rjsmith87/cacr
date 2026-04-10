#!/usr/bin/env python3
"""Sync .env variables to Render services via the Render API.

Usage:
  python scripts/sync_env_to_render.py                  # sync to both services
  python scripts/sync_env_to_render.py --service api    # sync to cacr-api only
  python scripts/sync_env_to_render.py --service dashboard  # sync to dashboard only

Requires RENDER_API_KEY env var or in .env.
"""

import argparse
import json
import os
import sys
import urllib.request

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

RENDER_API = "https://api.render.com/v1"

# Keys to sync per service
API_KEYS = ["GCP_PROJECT", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY",
            "GOOGLE_APPLICATION_CREDENTIALS"]
DASHBOARD_KEYS = ["VITE_API_URL"]


def _load_dotenv() -> dict[str, str]:
    env = {}
    path = os.path.join(_ROOT, ".env")
    if not os.path.exists(path):
        return env
    with open(path) as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip().strip('"').strip("'")
            if k and v:
                env[k] = v
    return env


def _get_services(api_key: str) -> list[dict]:
    req = urllib.request.Request(
        f"{RENDER_API}/services?limit=50",
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
    )
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read())
    return [s["service"] for s in data]


def _set_env_var(api_key: str, service_id: str, key: str, value: str) -> None:
    payload = json.dumps({"value": value}).encode()
    req = urllib.request.Request(
        f"{RENDER_API}/services/{service_id}/env-vars/{key}",
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="PUT",
    )
    try:
        urllib.request.urlopen(req)
    except urllib.error.HTTPError:
        # Key doesn't exist yet, create it
        req2 = urllib.request.Request(
            f"{RENDER_API}/services/{service_id}/env-vars",
            data=json.dumps([{"key": key, "value": value}]).encode(),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="PUT",
        )
        urllib.request.urlopen(req2)


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync .env to Render")
    parser.add_argument("--service", choices=["api", "dashboard"], default=None,
                        help="Sync to one service only")
    args = parser.parse_args()

    env = _load_dotenv()
    api_key = env.get("RENDER_API_KEY") or os.environ.get("RENDER_API_KEY")
    if not api_key:
        print("RENDER_API_KEY not set in .env or environment.", file=sys.stderr)
        return 1

    services = _get_services(api_key)
    svc_map = {s["name"]: s["id"] for s in services}

    targets = []
    if args.service is None or args.service == "api":
        sid = svc_map.get("cacr-api")
        if sid:
            targets.append(("cacr-api", sid, API_KEYS))
        else:
            print("Service 'cacr-api' not found on Render.", file=sys.stderr)

    if args.service is None or args.service == "dashboard":
        sid = svc_map.get("cacr-dashboard")
        if sid:
            targets.append(("cacr-dashboard", sid, DASHBOARD_KEYS))
        else:
            print("Service 'cacr-dashboard' not found on Render.", file=sys.stderr)

    for name, sid, keys in targets:
        for key in keys:
            val = env.get(key, os.environ.get(key, ""))
            if val:
                _set_env_var(api_key, sid, key, val)
                print(f"  {name}: set {key}")
            else:
                print(f"  {name}: skip {key} (empty)")

    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
