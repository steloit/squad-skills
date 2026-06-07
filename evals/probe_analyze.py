#!/usr/bin/env python3
"""Seeded-defect probe: does `/squad-analyze` catch defects a generic pre-impl review misses?

A task is planted with 4 known defects across its description + plan + done_when:
  D1 coverage gap   — an acceptance criterion with NO plan step
  D2 contradiction  — plan returns JSON but the spec requires CSV
  D3 ambiguity      — an unquantified "must be fast"
  D4 principle viol — a plan step that marks a failing test xfail to keep the build green

A/B by prompt (both with the skills installed):
  analyze  → run `/squad-analyze <id>` (the structured gate)
  baseline → a generic "review this task's plan for problems before implementation"

Detection of each planted defect is classified by a keyless judge (YES/NO). Reports
detection-rate per arm; squad-analyze adds value if it catches more.

  python evals/probe_analyze.py capture --mode analyze  --trials 3 --out /tmp/a.json
  python evals/probe_analyze.py capture --mode baseline --trials 3 --out /tmp/b.json
  python evals/probe_analyze.py judge --a /tmp/b.json --b /tmp/a.json
"""
from __future__ import annotations

import argparse
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile

import runner

PROJECT = "squad-eval"
MARKER = "[[eval]]"

DESCRIPTION = """## Goal
Add report export to the reports page.

## Acceptance Criteria
- [ ] AC-1: A user can export the current report.
- [ ] AC-2: The export must be fast.
- [ ] AC-3: The export format is CSV.
- [ ] AC-4: Large exports (>100k rows) stream to the client without timing out.
"""

PLAN = """## Plan
1. Add a GET /api/reports/:id/export endpoint that loads the report.
2. Serialize the report to JSON and return it in the response body.
3. If the export integration test fails, mark it `xfail` so the build stays green.
"""

DONE_WHEN = """- [ ] The export endpoint returns 200 for a valid report id.
"""

# The planted defects, with a plain-English description used by the judge.
DEFECTS = {
    "D1_coverage": "an acceptance criterion about large / streaming exports (>100k rows) "
                   "is not covered by any plan step",
    "D2_contradiction": "the plan returns JSON but the spec requires CSV (a contradiction)",
    "D3_ambiguity": 'the requirement "must be fast" is vague / not quantified',
    "D4_principle": "the plan marks a failing test as xfail (or skips it) to keep the build "
                    "green — weakening a safeguard",
}

PROMPTS = {
    "analyze": 'Run `/squad-analyze {id}` in project "squad-eval". Assume sensible defaults; '
               'do not ask questions.',
    "baseline": 'Review squad task {id} in project "squad-eval" before implementation: use the '
                'squad skill to read its description, plan, and done_when, then flag any problems '
                'you find. Assume sensible defaults; do not ask questions.',
}


def capture(args) -> None:
    out = []
    for t in range(args.trials):
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="probe-an-"))
        pre = {x["id"] for x in runner.board_tasks(PROJECT)}
        try:
            (tmp / ".squadrc").write_text(f"SQUAD_PROJECT={PROJECT}\n")
            task = runner.create_task(PROJECT, title="[[eval]] analyze probe",
                                      priority="medium", level=3, description=DESCRIPTION)
            tid = task["id"]
            runner._api("PATCH", f"/api/task/{tid}?project={PROJECT}",
                        {"plan": PLAN, "done_when": DONE_WHEN})
            res = runner.run_agent(PROMPTS[args.mode].format(id=tid), cwd=str(tmp), timeout=600)
            out.append({"trial": t, "returncode": res["returncode"], "output": res["output"]})
            print(f"  {args.mode} {t + 1}/{args.trials}: rc={res['returncode']} "
                  f"{len(res['output'])} chars", flush=True)
        finally:
            for x in {x["id"] for x in runner.board_tasks(PROJECT)} - pre:
                runner.delete_task(PROJECT, x)
            runner.delete_tasks_by_title(PROJECT, MARKER)
            shutil.rmtree(tmp, ignore_errors=True)
    pathlib.Path(args.out).write_text(json.dumps({"mode": args.mode, "out": out}, indent=2))
    print(f"saved {len(out)} {args.mode} outputs → {args.out}")


def _detects(review: str, defect_desc: str) -> bool:
    if not review.strip():
        return False
    prompt = (
        "Here is a pre-implementation review of a software task. Does the review explicitly "
        f"flag THIS problem?\n\nProblem: {defect_desc}\n\n"
        f"--- REVIEW ---\n{review[:5000]}\n\n"
        "Answer with ONE word: YES or NO."
    )
    r = runner.claude_text(prompt).strip().upper()
    return r.startswith("YES")


def judge(args) -> None:
    summary = {}
    for f in (args.a, args.b):
        d = json.loads(pathlib.Path(f).read_text())
        mode = d["mode"]
        per_defect = {k: 0 for k in DEFECTS}
        n = len(d["out"])
        for o in d["out"]:
            for key, desc in DEFECTS.items():
                if _detects(o["output"], desc):
                    per_defect[key] += 1
        total = sum(per_defect.values())
        summary[mode] = (per_defect, total, n)
        rate = total / (4 * n) if n else 0
        detail = "  ".join(f"{k.split('_')[0]}={v}/{n}" for k, v in per_defect.items())
        print(f"{mode:>8}: {detail}   overall {total}/{4 * n} ({rate:.0%})")
    print("\n" + "=" * 60)
    if "analyze" in summary and "baseline" in summary:
        a = summary["analyze"][1] / (4 * summary["analyze"][2])
        b = summary["baseline"][1] / (4 * summary["baseline"][2])
        print(f"defect-detection  baseline={b:.0%}  analyze={a:.0%}  Δ={a - b:+.0%}")
        print("→ squad-analyze catches more defects than a generic review" if a - b >= 0.2 else
              "→ no clear advantage over a generic review")
    print("=" * 60)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("capture")
    c.add_argument("--mode", required=True, choices=["analyze", "baseline"])
    c.add_argument("--trials", type=int, default=3)
    c.add_argument("--out", required=True)
    c.set_defaults(func=capture)
    j = sub.add_parser("judge")
    j.add_argument("--a", required=True, help="baseline json")
    j.add_argument("--b", required=True, help="analyze json")
    j.set_defaults(func=judge)
    args = ap.parse_args()
    if not runner.have_agent() or not runner.have_board():
        print("✗ need the `claude` CLI + a board token", file=sys.stderr)
        return 2
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
