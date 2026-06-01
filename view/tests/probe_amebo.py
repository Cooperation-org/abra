#!/usr/bin/env python3
"""Probe amebo's public API to verify the embed contract end-to-end.

Run this *before* wiring the view's `/abra-view/up/amebo/*` proxy + the
component install flow. If it passes, the proxy is just plumbing. If it
fails, the bug is in amebo's contract, not in the view's wiring.

What it checks (one section per amebo endpoint the components need):

  1. /health                — alive, no auth
  2. /embed/amebo.js        — bundle reachable (no auth)
  3. /api/digest/           — typed kinds {recent, hot, goal} present
  4. /api/goals/            — list returns array of GoalResponse
  5. /api/goals/{id}/events — events list works
  6. /api/qa/ask            — RAG roundtrip (POST with a question)

Each check prints a one-line PASS / FAIL and the offending body on FAIL.

Configuration is all env-driven — never hardcoded. The harness can run
against any amebo by changing `AMEBO_BASE_URL`.

Auth: this harness mints its own short-lived JWT for a user/org passed
via env. The view's real proxy will mint these the same way (jose +
amebo's `JWT_SECRET_KEY`).

Usage:
    JWT_SECRET_KEY=... \\
    PROBE_ORG_ID=1 PROBE_USER_ID=1 PROBE_EMAIL=test@example.com \\
    /opt/shared/repos/amebo/backend/venv/bin/python \\
      /opt/shared/repos/abra/view/tests/probe_amebo.py
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from jose import jwt

# ── config (env, never hardcoded) ────────────────────────────────────────

AMEBO_BASE = os.getenv("AMEBO_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
JWT_SECRET = os.getenv("JWT_SECRET_KEY")
JWT_ALGO   = os.getenv("JWT_ALGORITHM", "HS256")

PROBE_ORG_ID  = int(os.getenv("PROBE_ORG_ID",  "1"))
PROBE_USER_ID = int(os.getenv("PROBE_USER_ID", "1"))
PROBE_EMAIL   = os.getenv("PROBE_EMAIL", "probe@example.com")
PROBE_ROLE    = os.getenv("PROBE_ROLE", "admin")

if not JWT_SECRET:
    # Last-resort dev fallback: read it from amebo's .env so the harness
    # is runnable on the same VM without copying secrets around. Off by
    # default in production-style environments where the env is the
    # authority.
    env_path = Path("/opt/shared/repos/amebo/backend/.env")
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if line.startswith("JWT_SECRET_KEY=") and not line.startswith("#"):
                JWT_SECRET = line.split("=", 1)[1].strip()
                break

if not JWT_SECRET:
    print("FATAL: JWT_SECRET_KEY not in env and not in /opt/shared/repos/amebo/backend/.env")
    sys.exit(2)


def mint_jwt() -> str:
    """Mint an access token with the shape amebo's get_current_user expects."""
    now = datetime.now(timezone.utc)
    payload = {
        "user_id": PROBE_USER_ID,
        "org_id":  PROBE_ORG_ID,
        "email":   PROBE_EMAIL,
        "role":    PROBE_ROLE,
        "type":    "access",
        "exp":     now + timedelta(minutes=15),
        "iat":     now,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)


# ── tiny test runner ─────────────────────────────────────────────────────

PASS, FAIL = 0, 0
TOKEN = mint_jwt()
AUTH_HEADERS = {"Authorization": f"Bearer {TOKEN}"}


def check(name: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}")
        if detail:
            for line in detail.splitlines():
                print(f"        {line}")


def try_get(path: str, **kwargs) -> requests.Response | None:
    try:
        return requests.get(f"{AMEBO_BASE}{path}", timeout=10, **kwargs)
    except requests.RequestException as e:
        print(f"  ERR   GET {path}: {e}")
        return None


def try_post(path: str, **kwargs) -> requests.Response | None:
    try:
        return requests.post(f"{AMEBO_BASE}{path}", timeout=30, **kwargs)
    except requests.RequestException as e:
        print(f"  ERR   POST {path}: {e}")
        return None


# ── checks ───────────────────────────────────────────────────────────────

def check_health():
    print("\n[1] /health — alive, no auth")
    r = try_get("/health")
    check("/health responds", r is not None)
    if r is not None:
        check("/health 200", r.status_code == 200, f"status {r.status_code}, body {r.text[:200]}")


def check_bundle():
    print("\n[2] /embed/amebo.js — bundle reachable")
    r = try_get("/embed/amebo.js")
    if r is None:
        return
    check("bundle 200", r.status_code == 200, f"status {r.status_code}")
    if r.status_code == 200:
        body = r.text
        for tag in ("amebo-ask", "amebo-goal", "amebo-goals", "amebo-digest"):
            check(f"bundle defines <{tag}>", f"customElements.define" in body and tag in body,
                  f"missing tag '{tag}' in bundle")


def check_digest():
    print("\n[3] /api/digest/ — typed kinds present (JWT)")
    r = try_get("/api/digest/", headers=AUTH_HEADERS)
    if r is None:
        return
    check("digest 200", r.status_code == 200, f"status {r.status_code}, body {r.text[:300]}")
    if r.status_code != 200:
        return
    try:
        data = r.json()
    except json.JSONDecodeError as e:
        check("digest JSON", False, str(e))
        return
    check("digest has 'items'", "items" in data, f"keys: {list(data.keys())}")
    items = data.get("items", [])
    kinds = {item.get("kind") for item in items if isinstance(item, dict)}
    check("kind in {recent, hot, goal} when populated",
          not items or kinds.issubset({"recent", "hot", "goal"}),
          f"unexpected kinds: {kinds - {'recent', 'hot', 'goal'}}")
    print(f"        (digest carries {len(items)} items: {sorted(kinds) or 'empty'})")


def check_goals_list():
    print("\n[4] /api/goals/ — list (JWT)")
    r = try_get("/api/goals/", headers=AUTH_HEADERS)
    if r is None:
        return r
    check("goals list 200", r.status_code == 200, f"status {r.status_code}, body {r.text[:300]}")
    if r.status_code != 200:
        return r
    try:
        data = r.json()
    except json.JSONDecodeError as e:
        check("goals JSON", False, str(e))
        return r
    check("goals list is array", isinstance(data, list), f"got {type(data).__name__}")
    print(f"        (goals list carries {len(data) if isinstance(data, list) else '?'} items)")
    return r


def check_goal_events(goals_response):
    print("\n[5] /api/goals/{id}/events — events (JWT)")
    if goals_response is None or goals_response.status_code != 200:
        check("events probe (skipped, no goal id)", False, "list call failed")
        return
    goals = goals_response.json()
    if not goals:
        check("events probe (no goals to probe — info only)", True, "")
        print("        (no goals in this org; events shape unverified)")
        return
    gid = goals[0].get("id")
    if not gid:
        check("first goal has id", False, f"first goal: {goals[0]}")
        return
    r = try_get(f"/api/goals/{gid}/events", headers=AUTH_HEADERS)
    if r is None:
        return
    check(f"goals/{gid}/events 200", r.status_code == 200,
          f"status {r.status_code}, body {r.text[:300]}")
    if r.status_code == 200:
        try:
            data = r.json()
            check("events list is array", isinstance(data, list))
        except json.JSONDecodeError as e:
            check("events JSON", False, str(e))


def check_qa_ask():
    print("\n[6] /api/qa/ask — RAG roundtrip (JWT)")
    body = {"question": "hello — probe smoke test, please respond briefly"}
    r = try_post("/api/qa/ask", json=body, headers=AUTH_HEADERS)
    if r is None:
        return
    check("qa/ask responds", r.status_code in (200, 201),
          f"status {r.status_code}, body {r.text[:400]}")
    if r.status_code in (200, 201):
        try:
            data = r.json()
            check("qa/ask returns dict", isinstance(data, dict), f"got {type(data).__name__}")
        except json.JSONDecodeError as e:
            check("qa/ask JSON", False, str(e))


# ── main ─────────────────────────────────────────────────────────────────

def main() -> int:
    print(f"probing amebo at {AMEBO_BASE}")
    print(f"  using minted JWT for org_id={PROBE_ORG_ID} user_id={PROBE_USER_ID}")
    check_health()
    check_bundle()
    check_digest()
    goals_r = check_goals_list()
    check_goal_events(goals_r)
    check_qa_ask()
    print()
    total = PASS + FAIL
    print(f"summary: {PASS}/{total} pass, {FAIL} fail")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
