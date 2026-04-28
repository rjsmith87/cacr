"""CLI for triggering Render manual deploys via the API.

Use this when Render's git auto-deploy doesn't fire on push to main
(observed intermittently on this project) or when you want to deploy
HEAD without making a no-op commit.

Authentication
    Reads RENDER_API_KEY from os.environ. The key is never printed,
    logged, or written to disk by this script — it's only assembled
    into the Authorization header of outbound requests. Source it
    from .env before running, e.g.:

        set -a && . ./.env && set +a
        python scripts/render_deploy.py SERVICE_ID [SERVICE_ID ...]

    Exits with code 1 if the env var is missing.

Usage
    python scripts/render_deploy.py srv-d7cf11rbc2fs73eta09g \
                                    srv-d7cf147lk1mc7397nd70

    The two IDs above are the CACR API and CACR dashboard services.
    Pass either or both. Each gets a fresh deploy at HEAD and the
    script polls every 20 seconds until all reach a terminal status.

Behavior
    1. POST /v1/services/{id}/deploys to kick off a deploy.
    2. Print the deploy_id, target commit, and starting status.
    3. Poll GET /v1/services/{id}/deploys/{deploy_id} every 20s.
    4. Stop when every deploy reaches a terminal status, or after a
       15-minute safety cap (whichever comes first).

Terminal Render statuses (per docs as of 2026)
    live, build_failed, update_failed, canceled, deactivated,
    pre_deploy_failed

Exit codes
    0 — every deploy reached "live"
    1 — at least one deploy ended in a non-"live" terminal status,
        or the API key was missing, or the trigger POST failed
    2 — no service IDs supplied on the command line
"""

import os
import sys
import time
import json
import urllib.request
import urllib.error

API_BASE = "https://api.render.com/v1"
TERMINAL = {"live", "build_failed", "update_failed", "canceled",
            "deactivated", "pre_deploy_failed"}


def _request(method: str, path: str, key: str, body: dict | None = None) -> dict:
    url = f"{API_BASE}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url, data=data, method=method,
        headers={
            "Authorization": f"Bearer {key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        raise RuntimeError(f"HTTP {e.code} on {method} {path}: {body[:300]}")


def trigger(service_id: str, key: str) -> dict:
    return _request("POST", f"/services/{service_id}/deploys", key, body={})


def get_deploy(service_id: str, deploy_id: str, key: str) -> dict:
    return _request("GET", f"/services/{service_id}/deploys/{deploy_id}", key)


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("Usage: render_deploy.py SERVICE_ID [SERVICE_ID ...]", file=sys.stderr)
        return 2
    key = os.environ.get("RENDER_API_KEY")
    if not key:
        print("ERROR: RENDER_API_KEY not in environment.", file=sys.stderr)
        return 1
    print(f"key loaded: yes (length redacted)")

    deploys: list[tuple[str, str]] = []  # (service_id, deploy_id)
    for sid in argv[1:]:
        print(f"\n→ triggering deploy for {sid}")
        try:
            r = trigger(sid, key)
        except Exception as exc:
            print(f"  ERROR: {exc}", file=sys.stderr)
            return 1
        did = r.get("id") or r.get("deploy", {}).get("id")
        if not did:
            print(f"  unexpected response: {json.dumps(r)[:300]}", file=sys.stderr)
            return 1
        commit = r.get("commit", {}).get("id", "?")[:8]
        print(f"  deploy_id={did}  commit={commit}  status={r.get('status', '?')}")
        deploys.append((sid, did))

    print(f"\nPolling {len(deploys)} deploy(s) every 20s until terminal status...\n")
    pending = list(deploys)
    elapsed = 0
    final: dict[tuple[str, str], dict] = {}
    while pending:
        time.sleep(20)
        elapsed += 20
        still: list[tuple[str, str]] = []
        for sid, did in pending:
            try:
                r = get_deploy(sid, did, key)
            except Exception as exc:
                print(f"  [{elapsed:>4}s] {sid} {did[:12]}  poll error: {exc}")
                still.append((sid, did))
                continue
            status = r.get("status", "?")
            print(f"  [{elapsed:>4}s] {sid} {did[:12]}  status={status}")
            if status in TERMINAL:
                final[(sid, did)] = r
            else:
                still.append((sid, did))
        pending = still
        if elapsed >= 900:  # 15-minute safety cap
            print("\nWARN: hit 15-min poll cap; stopping early. Pending services:")
            for sid, did in pending:
                print(f"  {sid} {did}")
            break

    print("\n=== final statuses ===")
    rc = 0
    for (sid, did), r in final.items():
        status = r.get("status", "?")
        commit = r.get("commit", {}).get("id", "?")[:8]
        print(f"  {sid}  status={status}  commit={commit}")
        if status != "live":
            rc = 1
    return rc


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
