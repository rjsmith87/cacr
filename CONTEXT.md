# CACR — Session Log

A running log of work sessions on the CACR project. Each entry captures
the date, what was done, why, and where it landed (commits, services,
config). For longer-form architectural notes and durable decisions, see
`CLAUDE.md`. For benchmark / methodology results, see `FINDINGS.md` and
`METHODOLOGY.md`.

## 2026-04-30

Goal: make the Cascade Demo tab on cacr-dashboard.onrender.com actually
work in production. It had been stuck on "Network error: Failed to
fetch" through several layered bugs.

### Resolved

- **Plan upgrade.** Upgraded cacr-api (`srv-d7cf11rbc2fs73eta09g`) from
  Free to Standard ($25/mo, 2 GB RAM) via the Render dashboard. This
  was the standing 2026-04-29 blocker for `/api/cascade-compare` —
  workers had been SIGKILLed at the Free plan's 512 MB ceiling. Plan
  upgrade had to be a manual dashboard action; the Render API still
  rejects `PATCH /v1/services/{id}` with `serviceDetails.plan` (HTTP
  500).

- **`VITE_API_URL` not baked into the dashboard bundle.** The Render
  static-site env var alone wasn't reaching Vite at build time, so the
  bundle fell back to its `'http://localhost:8000'` default — every
  dashboard view (not just Cascade Demo) was hitting the dashboard's
  own origin instead of cacr-api. Committed `dashboard/.env.production`
  with `VITE_API_URL=https://cacr-api.onrender.com` (`46cc2e9`),
  pushed, triggered a `clearCache` deploy of cacr-dashboard
  (`srv-d7cf147lk1mc7397nd70`). Verified: the new bundle
  (`assets/index-ViUa0EnF.js`) contains `https://cacr-api.onrender.com`
  and no `localhost:8000` references.

- **cacr-api gunicorn config was wrong.** The render.yaml startCommand
  (`--worker-class gthread --timeout 180 --threads 2 ...`) had never
  applied because Blueprint sync was never triggered. The dashboard's
  stored value was the Render Python-runtime default
  `gunicorn api.main:app --workers 2` — sync worker, default 30 s
  timeout. Cascade-compare requests routinely take 25-35 s, so workers
  got SIGABRT'ed mid-`ssl.recv` from Gemini, and Render's edge served
  an HTML 500 with no `Access-Control-Allow-Origin` header — which the
  browser surfaces as "Network error: Failed to fetch." Patched via
  the Render API:
  ```
  PATCH /v1/services/srv-d7cf11rbc2fs73eta09g
  {"serviceDetails": {"envSpecificDetails": {
    "startCommand": "gunicorn api.main:app --bind 0.0.0.0:$PORT
                     --workers 1 --threads 2 --worker-class gthread
                     --timeout 180 --max-requests 100
                     --max-requests-jitter 25"
  }}}
  ```
  HTTP 200, change reflected, took effect on the next deploy. Logs
  now show `Using worker: gthread` and the correct timeout.

- **Per-request timeout on Flash and Flash Lite Gemini adapters**
  (`ad81bf2`). The Pro adapter had been hardened during the v2 hang
  incident with `HttpOptions(timeout=60_000)` plus
  `httpx.TimeoutException` / `NetworkError` retries — but Flash and
  Flash Lite never got the same fix. Same CLOSE_WAIT failure mode:
  the SDK can sit in `ssl.recv()` indefinitely when the server has
  closed its side of the socket without surfacing it as retryable.
  Mirrored the Pro adapter's defenses on both Flash variants. 19/19
  pytest still pass.

### Verification

- `GET /health` → 200 OK
- 3 sequential `POST /api/cascade-compare` from `Origin:
  https://cacr-dashboard.onrender.com` → all 200 OK in 28–35 s, with
  `access-control-allow-origin: https://cacr-dashboard.onrender.com`
  on every response.
- `comparison.b_escalated: true` on the SSRF example confirms the
  cascade router's runtime confidence escalation is firing.
- Cascade Demo tab is now functional end-to-end in the browser.

### Followups noted

- Worth double-checking that the Render dashboard's stored
  startCommand and buildCommand match render.yaml after any future
  Blueprint resync — the dashboard value is what actually runs, not
  the YAML.
- The Free → Standard upgrade ($25/mo) should be reviewed for
  necessity once the cascade-compare workload settles. Standard's 2 GB
  is generous for the current load; Starter (512 MB → 1 GB depending
  on tier) might suffice with the JIT-imported adapters and the GC
  sweep already in place.
