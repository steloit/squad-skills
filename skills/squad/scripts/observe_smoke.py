#!/usr/bin/env python3
"""observe_smoke.py — live read-only round-trip for observe.py against a real board.

Manual harness (like api_smoke.py): needs a real Personal Access Token in the
environment / ~/.squad/auth and a configured SQUAD_ORG. NOT run in CI (the offline
hermetic unit `tests/test_observe.py` is the gate). It mutates NOTHING — observe.py
only ever issues `GET /consent`, and never grants/withdraws (the human opt-in act
lives in the web app).

HONEST SCOPE: production `GET /consent` (SQD-937) is NOT deployed yet, so the
opted-in → gate-ON path is verifiable ONLY against a LOCALLY-booted consent-branch
platform (point SQUAD_BASE_URL at it). The production live-test is deferred to deploy.

Opt-in only — runs the round-trip only under SQUAD_OBSERVE_LIVE=1. It proves the gate
reflects the real server state end-to-end:
  A  observe.py status  -> exit in {0,1,2}, names a source + the manage pointer
  B  observe.py gate    -> exit code matches status (same resolution); 0=on else off
  C  observe.py emit --dry-run -> assembles a valid user_steering body (NO gate, NO
     POST). The live opted-in emit POST is DEPLOY-DEFERRED (needs SQD-937 /consent +
     the user_steering activity write path); only the local dry-run preview is checked.

Usage:
  SQUAD_OBSERVE_LIVE=1 observe_smoke.py
Prints a one-line verdict per check to stderr. Exit 0 if the checks pass.
"""
import json
import os
import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
OBSERVE = HERE / "observe.py"


def run_observe(*observe_args):
    return subprocess.run(
        [sys.executable, str(OBSERVE), *observe_args],
        capture_output=True,
        text=True,
    )


def check_status():
    res = run_observe("status", "--json")
    if res.returncode not in (0, 1, 2):
        print(f"[A status] FAIL unexpected exit={res.returncode}: {res.stderr.strip()}",
              file=sys.stderr)
        return False, res.returncode
    try:
        decision = json.loads(res.stdout)
    except json.JSONDecodeError as exc:
        print(f"[A status] FAIL stdout is not JSON: {exc}", file=sys.stderr)
        return False, res.returncode
    if "source" not in decision or "manage" not in decision:
        print(f"[A status] FAIL decision missing source/manage: {decision!r}", file=sys.stderr)
        return False, res.returncode
    print(
        f"[A status] OK live read (exit={res.returncode}, source={decision['source']}, "
        f"capture={decision['capture']})",
        file=sys.stderr,
    )
    return True, res.returncode


def check_gate(expected_code):
    res = run_observe("gate", "--json")
    if res.returncode != expected_code:
        print(
            f"[B gate] FAIL exit={res.returncode} did not match status exit={expected_code}: "
            f"{res.stderr.strip()}",
            file=sys.stderr,
        )
        return False
    print(f"[B gate] OK gate exit={res.returncode} matches status (same resolution)",
          file=sys.stderr)
    return True


def check_emit_dry_run():
    """C — local emit preview: assemble a real user_steering body, NO gate, NO POST.
    The live opted-in emit POST is deploy-deferred (SQD-937); only this is checked."""
    res = run_observe(
        "emit", "SQD-0",
        "--modality", "corrective",
        "--valence", "negative",
        "--target", "planning",
        "--severity", "moderate",
        "--attributability", "latent_preference",
        "--comment", "preferred a smaller scope",
        "--dry-run",
    )
    if res.returncode != 0:
        print(f"[C emit] FAIL --dry-run exit={res.returncode}: {res.stderr.strip()}",
              file=sys.stderr)
        return False
    try:
        body = json.loads(res.stdout)
    except json.JSONDecodeError as exc:
        print(f"[C emit] FAIL --dry-run stdout is not JSON: {exc}", file=sys.stderr)
        return False
    payload = body.get("payload", {})
    if body.get("kind") != "user_steering" or payload.get("v") != 1 or not body.get("message"):
        print(f"[C emit] FAIL --dry-run body malformed: {body!r}", file=sys.stderr)
        return False
    print(
        f"[C emit] OK dry-run body assembled (modality={payload.get('modality')}, "
        f"comment={payload.get('comment')!r}); live POST is deploy-deferred (SQD-937)",
        file=sys.stderr,
    )
    return True


def main():
    if os.environ.get("SQUAD_OBSERVE_LIVE", "") != "1":
        print(
            "[skip] SQUAD_OBSERVE_LIVE!=1 — live round-trip not requested. Set "
            "SQUAD_OBSERVE_LIVE=1 (and point SQUAD_BASE_URL at a locally-booted "
            "SQD-937 consent branch; production GET /consent is not deployed).",
            file=sys.stderr,
        )
        return 0

    ok, status_code = check_status()
    if ok:
        ok = check_gate(status_code) and ok
    ok = check_emit_dry_run() and ok
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
