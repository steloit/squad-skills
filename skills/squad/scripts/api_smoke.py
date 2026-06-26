#!/usr/bin/env python3
"""api_smoke.py — live read-only smoke for api.py against the deployed board.

Manual harness (like coach_smoke.py): needs a real Personal Access Token in the
environment / ~/.squad/auth and a configured SQUAD_ORG. NOT run in CI (the
offline unit covers the hermetic cases). It mutates nothing — only GETs.

It proves auth + transport + decode + -q extraction end-to-end:
  A  GET /board?summary=true        -> exit 0, stdout is non-empty JSON
  B  GET /task/<id> -q version      -> exit 0, stdout is the version scalar only
                                       (only when a task id is supplied)

Usage:
  api_smoke.py [--task <id>]
  # or set SQUAD_SMOKE_TASK=<id>

Prints a one-line verdict per check to stderr. Exit 0 if all checks pass.
"""
import argparse
import json
import os
import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
API = HERE / "api.py"


def run_api(*api_args):
    return subprocess.run(
        [sys.executable, str(API), *api_args],
        capture_output=True,
        text=True,
    )


def check_board():
    res = run_api("GET", "/board?summary=true")
    if res.returncode != 0:
        print(
            f"[A board] FAIL exit={res.returncode}: {res.stderr.strip()}",
            file=sys.stderr,
        )
        return False
    try:
        json.loads(res.stdout)
    except json.JSONDecodeError as exc:
        print(f"[A board] FAIL stdout is not JSON: {exc}", file=sys.stderr)
        return False
    print("[A board] OK auth+transport+decode (GET /board?summary=true)", file=sys.stderr)
    return True


def check_task_version(task_id):
    res = run_api("GET", f"/task/{task_id}", "-q", "version")
    if res.returncode != 0:
        print(
            f"[B task] FAIL exit={res.returncode}: {res.stderr.strip()}",
            file=sys.stderr,
        )
        return False
    value = res.stdout.strip()
    if not value or "\n" in res.stdout.strip():
        print(f"[B task] FAIL expected a single scalar on stdout, got: {res.stdout!r}",
              file=sys.stderr)
        return False
    print(f"[B task] OK -q extraction (GET /task/{task_id} -q version -> {value})",
          file=sys.stderr)
    return True


def main():
    ap = argparse.ArgumentParser(description="Live read-only smoke for api.py.")
    ap.add_argument("--task", default=os.environ.get("SQUAD_SMOKE_TASK", ""),
                    help="a known task id to prove -q extraction (read-only GET).")
    args = ap.parse_args()

    ok = check_board()
    if args.task:
        ok = check_task_version(args.task) and ok
    else:
        print(
            "[B task] SKIP no task id given (pass --task <id> or set "
            "SQUAD_SMOKE_TASK to prove -q end-to-end)",
            file=sys.stderr,
        )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
