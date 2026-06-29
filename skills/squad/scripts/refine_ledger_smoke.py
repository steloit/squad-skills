#!/usr/bin/env python3
"""refine_ledger_smoke.py — manual self-check for refine_ledger.py (every branch).

Pure-logic harness: refine_ledger.py issues NO network and reads NO board, so —
unlike observe_smoke.py / api_smoke.py — this needs no token, no SQUAD_ORG, and no
opt-in env var. It runs unconditionally and exercises each verdict branch via the
CLI, asserting the EXIT CODE (the contract SKILL.md depends on) plus the --json
decision shape. The hermetic pytest lock (tests/test_refine_ledger.py) is the CI
gate; this is the quick "did I break the gate?" check you run by hand.

Usage:
  refine_ledger_smoke.py
Prints a one-line verdict per check to stderr. Exit 0 iff every check passes.
"""
import json
import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
LEDGER = HERE / "refine_ledger.py"

OPEN_WHAT = '[{"id":"g1","dimension":"WHAT","status":"OPEN","source":"original"}]'
RESOLVED_WHAT = '[{"id":"g1","dimension":"WHAT","status":"RESOLVED","source":"original"}]'
CAP_CORE_OPEN = (
    '[{"id":"g1","dimension":"SCOPE","status":"OPEN","source":"original"},'
    '{"id":"g2","dimension":"ACCEPTANCE","status":"RESOLVED","source":"original"}]'
)
CAP_NONCORE_OPEN = '[{"id":"g1","dimension":"EDGE","status":"OPEN","source":"raised-by-answer-R2"}]'


def run(ledger, *args):
    return subprocess.run(
        [sys.executable, str(LEDGER), "verdict", *args],
        input=ledger,
        capture_output=True,
        text=True,
    )


def check(label, ledger, args, expected_code, expected_verdict=None):
    res = run(ledger, *args)
    if res.returncode != expected_code:
        print(f"[{label}] FAIL exit={res.returncode} != {expected_code}: {res.stderr.strip()}",
              file=sys.stderr)
        return False
    if expected_verdict is not None:
        try:
            decision = json.loads(res.stdout)
        except json.JSONDecodeError as exc:
            print(f"[{label}] FAIL --json stdout not JSON: {exc}", file=sys.stderr)
            return False
        if decision.get("verdict") != expected_verdict:
            print(f"[{label}] FAIL verdict={decision.get('verdict')!r} != {expected_verdict!r}",
                  file=sys.stderr)
            return False
        for key in ("open_count", "core_unresolved", "residual_open", "reason", "degraded"):
            if key not in decision:
                print(f"[{label}] FAIL --json missing key {key!r}", file=sys.stderr)
                return False
    print(f"[{label}] OK exit={res.returncode}", file=sys.stderr)
    return True


def check_help():
    res = subprocess.run([sys.executable, str(LEDGER), "--help"], capture_output=True, text=True)
    if res.returncode != 0:
        print(f"[help] FAIL --help exit={res.returncode}", file=sys.stderr)
        return False
    print("[help] OK --help exit=0", file=sys.stderr)
    return True


def main():
    ok = True
    ok = check_help() and ok
    ok = check("CONTINUE", OPEN_WHAT, ["--round", "1", "--last-probe", "no_new_gaps", "--json"],
               1, "CONTINUE") and ok
    ok = check("STOP-CLEAN", RESOLVED_WHAT,
               ["--round", "2", "--last-probe", "no_new_gaps", "--json"], 0, "STOP-CLEAN") and ok
    ok = check("CONTINUE-unstable", RESOLVED_WHAT,
               ["--round", "2", "--last-probe", "new_gaps", "--json"], 1, "CONTINUE") and ok
    ok = check("STOP-DEGRADED", CAP_CORE_OPEN,
               ["--round", "6", "--cap", "6", "--json"], 2, "STOP-DEGRADED") and ok
    ok = check("STOP-CLEAN-cap", CAP_NONCORE_OPEN,
               ["--round", "6", "--cap", "6", "--json"], 0, "STOP-CLEAN") and ok
    ok = check("STOP-ENOUGH", OPEN_WHAT, ["--round", "1", "--user-enough", "--json"],
               3, "STOP-ENOUGH") and ok
    # anti-reask: a RESOLVED entry is never counted OPEN
    ok = check("anti-reask", RESOLVED_WHAT, ["--round", "1", "--last-probe", "no_new_gaps"],
               0) and ok
    # usage errors → 64 (distinct from the 2 STOP-DEGRADED verdict)
    ok = check("usage-badjson", "not json", ["--round", "1"], 64) and ok
    ok = check("usage-baddim", '[{"id":"g","dimension":"FOO","status":"OPEN"}]',
               ["--round", "1"], 64) and ok
    print(("ALL OK" if ok else "FAILURES"), file=sys.stderr)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
