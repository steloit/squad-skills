#!/usr/bin/env python3
"""Coach smoke harness — seeded synthetic trajectories for the friction judge.

Two hard-coded smokes from the approved plan:
  A (recall):    one unambiguous Squad-itself friction (squad-heartbeat scans last activity
                 with one GET /api/task/:id/activity per task at squad-heartbeat/SKILL.md:250,
                 an N+1 read against the board) → expect EXACTLY 1 friction report (area board-api).
  B (precision): a deliberately friction-free trajectory (only a worked-project bug at
                 demo/src/app.js:42) → expect 0 reports.

The Coach is an LLM, so the live judgment passes on a 2-of-3-runs basis (Shield runs the live
model dispatch). This harness is the DETERMINISTIC part: it renders templates/coach.md with each
seeded trajectory and emits the ready-to-dispatch prompt, asserting the seeded evidence is present
and the render is --strict-clean (no leftover <MODEL_COACH>/<EFFORT_COACH>).

Usage:
  python3 coach_smoke.py [--provider claude|codex] [--smoke A|B|both]
Prints each rendered prompt to stdout and a one-line verdict per smoke to stderr.
Exit 0 if both render cleanly; non-zero otherwise.
"""
import argparse
import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
SQUAD = HERE.parent  # skills/squad
RENDER = HERE / "render_agent_prompt.py"
TEMPLATE = SQUAD / "templates" / "coach.md"
MODELS = SQUAD / "models.json"

TRAJ_SET_KEYS = [
    "run_summary", "trajectory", "friction_signals",
    "skill_name", "source_project", "source_task", "PROJECT", "TIMESTAMP",
]

# ── Seeded synthetic trajectories (hard-coded; from the approved plan) ──────────
SMOKE_A = {
    "skill_name": "squad-heartbeat",
    "source_project": "demo",
    "source_task": "1",
    "run_summary": "squad-heartbeat scanned demo for stagnant tasks.",
    "trajectory": (
        "[activity] Heartbeat scanned 40 active tasks on demo. To find each task's last-activity\n"
        "    timestamp it issued one GET /api/task/:id/activity per task (squad-heartbeat/SKILL.md:250),\n"
        "    because the board list does not embed the activity stream -> 40 round-trips for one scan\n"
        "    (an N+1 read against the board). A single project-scoped batch reader would collapse this.\n"
        "[activity] Scan completed but was visibly slow on the larger boards due to the per-task fan-out."
    ),
    "friction_signals": "N+1 activity reads (one GET per task) in the heartbeat scan, traced to squad-heartbeat/SKILL.md:250.",
    "expect_reports": 1,
    "expect_area": "board-api",
    "evidence_marker": "squad-heartbeat/SKILL.md:250",
}

SMOKE_B = {
    "skill_name": "squad-run",
    "source_project": "demo",
    "source_task": "2",
    "run_summary": "squad-run pipeline completed demo task 2 to done.",
    "trajectory": (
        "[activity] All 6 agents ran clean: each board call returned 200 first try; no reject loops,\n"
        "    no retries, no circuit-breaker trips. The only issue found was a NullPointerException in\n"
        "    demo/src/app.js:42 - a bug in the WORKED PROJECT, which the Builder fixed."
    ),
    "friction_signals": "none (zero errors against Squad's own skills/board/orchestrator/templates).",
    "expect_reports": 0,
    "evidence_marker": "demo/src/app.js:42",
}


def render(smoke, provider):
    args = [
        sys.executable, str(RENDER),
        "--template", str(TEMPLATE),
        "--models", str(MODELS),
        "--provider", provider,
        "--set", f"PROJECT=squad",
        "--set", f"skill_name={smoke['skill_name']}",
        "--set", f"source_project={smoke['source_project']}",
        "--set", f"source_task={smoke['source_task']}",
        "--set", f"run_summary={smoke['run_summary']}",
        "--set", f"trajectory={smoke['trajectory']}",
        "--set", f"friction_signals={smoke['friction_signals']}",
        "--set", "TIMESTAMP=2026-06-08T00:00:00Z",
        "--strict",
    ]
    for k in TRAJ_SET_KEYS:
        args += ["--ignore", k]
    res = subprocess.run(args, capture_output=True, text=True)
    return res


def check(smoke, name, provider):
    res = render(smoke, provider)
    ok = True
    if res.returncode != 0:
        print(f"[{name}] FAIL render exit={res.returncode}: {res.stderr.strip()}", file=sys.stderr)
        return False, res.stdout
    out = res.stdout
    if "<MODEL_COACH>" in out or "<EFFORT_COACH>" in out:
        print(f"[{name}] FAIL leftover model placeholder in rendered prompt", file=sys.stderr)
        ok = False
    if smoke["evidence_marker"] not in out:
        print(f"[{name}] FAIL seeded evidence '{smoke['evidence_marker']}' not embedded", file=sys.stderr)
        ok = False
    if ok:
        print(
            f"[{name}] OK render clean (provider={provider}); "
            f"expect {smoke['expect_reports']} report(s) on live dispatch",
            file=sys.stderr,
        )
    return ok, out


def main():
    ap = argparse.ArgumentParser(description="Coach smoke harness (seeded trajectories).")
    ap.add_argument("--provider", choices=["claude", "codex"], default="claude")
    ap.add_argument("--smoke", choices=["A", "B", "both"], default="both")
    args = ap.parse_args()

    smokes = []
    if args.smoke in ("A", "both"):
        smokes.append(("A", SMOKE_A))
    if args.smoke in ("B", "both"):
        smokes.append(("B", SMOKE_B))

    all_ok = True
    for name, smoke in smokes:
        ok, out = check(smoke, name, args.provider)
        all_ok = all_ok and ok
        print(f"\n===== SMOKE {name} — ready-to-dispatch Coach prompt (provider={args.provider}) =====")
        sys.stdout.write(out)
        print(f"\n===== END SMOKE {name} =====\n")

    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
