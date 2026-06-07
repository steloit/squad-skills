#!/usr/bin/env python3
"""Counterfactual probe: does the Decisions Registry make the Planner follow a settled
decision that FIGHTS the model's own default?

Why counterfactual: if a decision agrees with the model's prior (e.g. "use snake-free
camelCase"), the agent complies anyway and you can't measure the registry's effect.
So the relevant decision here is **counter-prior** — `D-007: all names must be snake_case`
(agents default hard to camelCase in TS). It's buried among ~9 distractor decisions
(retrieval-under-distraction). The task naturally wants a camelCase name; following the
registry REQUIRES reading + obeying D-007.

Classification is **deterministic**: the plan naming the function `get_user_profile`
= FOLLOWED, `getUserProfile` = CONTRADICTED (the model's default), neither = UNCLEAR.

A/B by installed skill version (both arms have docs/decisions.md present; only the
squad-run wiring differs):

  python evals/probe_decisions.py capture --label without --trials 5 --out /tmp/wo.json
  # (swap install)
  python evals/probe_decisions.py capture --label with    --trials 5 --out /tmp/w.json
  python evals/probe_decisions.py judge --a /tmp/wo.json --b /tmp/w.json

NOT tested here: the *append* half (does the agent maintain the log) — that needs a full
run to Done, not just the planning step.
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

# A realistic registry: 9 distractors + one counter-prior decision (D-007), buried.
DECISIONS_MD = """# Decisions

### D-001 · App shell uses a persistent left sidebar (shadcn Sidebar)
Status: accepted · Date: 2026-05-01 · Task: #3
Decision: All pages render inside the shared sidebar layout.

### D-002 · Money is formatted with the Indian grouping (₹10,00,000)
Status: accepted · Date: 2026-05-02 · Task: #5
Decision: Use Intl.NumberFormat('en-IN'); never raw toLocaleString().

### D-003 · Persistence is PostgreSQL only
Status: accepted · Date: 2026-05-03 · Task: #7
Decision: No MongoDB/NoSQL. Schema via numbered up/down SQL migrations.

### D-004 · Auth is handled by Clerk
Status: accepted · Date: 2026-05-04 · Task: #9
Decision: Do not hand-roll sessions; use Clerk on both ends.

### D-005 · API is REST, not GraphQL (for MVP)
Status: accepted · Date: 2026-05-05 · Task: #11
Decision: REST endpoints under /api/v1; no GraphQL layer.

### D-006 · Validation uses Zod schemas at the boundary
Status: accepted · Date: 2026-05-06 · Task: #13
Decision: Every request body parsed by a Zod schema before use.

### D-007 · All exported names use snake_case (legacy interop constraint)
Status: accepted · Date: 2026-05-07 · Task: #15 · Supersedes: —
Context: The platform interops with a legacy Python service whose codegen expects
         snake_case identifiers across the wire and in shared modules.
Decision: Every exported function and variable name MUST be snake_case
          (e.g. `get_user_profile`, `fetch_invoice_list`). camelCase is FORBIDDEN
          for exported names. This is intentional and overrides the usual TS convention.
Consequences: Consistent with the legacy codegen. Rejected: camelCase, PascalCase.

### D-008 · Charts use recharts with OKLCH categorical hues
Status: accepted · Date: 2026-05-08 · Task: #17
Decision: recharts only; 8 categorically-distinct OKLCH colors.

### D-009 · Icons come from lucide-react only
Status: accepted · Date: 2026-05-09 · Task: #19
Decision: No mixed icon sets.

### D-010 · Background jobs run on BullMQ + Redis
Status: accepted · Date: 2026-05-10 · Task: #21
Decision: Async work goes through BullMQ queues, not inline.
"""

TASK = {
    "title": "[[eval]] fetch the user profile",
    "priority": "medium",
    "level": 3,  # L2/L3 so the Planner runs (L1 skips planning)
    "description": ("Add an exported function that fetches the user profile by id from "
                    "GET /api/v1/users/:id and returns the parsed JSON. Put it in "
                    "src/users.ts. Plan the implementation."),
}

PROMPT = ('Run a single planning step on task {id} in project "squad-eval": '
          '`/squad-run step {id}`. This dispatches the Planner to produce a plan. '
          'Assume sensible defaults; do not ask questions.')


def capture(args) -> None:
    out = []
    for t in range(args.trials):
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="probe-dec-"))
        pre = {x["id"] for x in runner.board_tasks(PROJECT)}
        try:
            (tmp / ".squadrc").write_text(f"SQUAD_PROJECT={PROJECT}\n")
            (tmp / "docs").mkdir()
            (tmp / "docs" / "decisions.md").write_text(DECISIONS_MD)
            (tmp / "src").mkdir()
            (tmp / "src" / "users.ts").write_text("// add the fetch function here\n")
            subprocess.run(["git", "init", "-q"], cwd=str(tmp), capture_output=True)

            task = runner.create_task(PROJECT, **TASK)
            tid = task["id"]
            res = runner.run_agent(PROMPT.format(id=tid), cwd=str(tmp), timeout=900)
            full = runner.get_task(PROJECT, tid)
            plan = ((full.get("plan") or "") + "\n\n" + (full.get("decision_log") or "")).strip()
            verdict = _classify(plan)
            out.append({"trial": t, "returncode": res["returncode"],
                        "verdict": verdict, "plan_len": len(plan), "plan": plan[:3000]})
            print(f"  {args.label} {t + 1}/{args.trials}: rc={res['returncode']} "
                  f"{verdict} ({len(plan)} chars)", flush=True)
        finally:
            for x in {x["id"] for x in runner.board_tasks(PROJECT)} - pre:
                runner.delete_task(PROJECT, x)
            runner.delete_tasks_by_title(PROJECT, MARKER)
            shutil.rmtree(tmp, ignore_errors=True)
    pathlib.Path(args.out).write_text(json.dumps({"label": args.label, "out": out}, indent=2))
    print(f"saved {len(out)} {args.label} outputs → {args.out}")


def _classify(plan: str) -> str:
    """Deterministic: did the plan name the function snake_case (FOLLOWED D-007) or
    camelCase (CONTRADICTED — the model's default)?"""
    if not plan.strip():
        return "UNCLEAR"
    snake = plan.count("get_user_profile") + plan.count("fetch_user_profile")
    camel = plan.count("getUserProfile") + plan.count("fetchUserProfile") \
        + plan.count("getUserprofile")
    if snake > camel:
        return "FOLLOWED"
    if camel > snake:
        return "CONTRADICTED"
    return "UNCLEAR"


def judge(args) -> None:
    rates = {}
    for f in (args.a, args.b):
        d = json.loads(pathlib.Path(f).read_text())
        label = d["label"]
        verdicts = [o["verdict"] for o in d["out"]]
        n = len(verdicts)
        foll = verdicts.count("FOLLOWED")
        contr = verdicts.count("CONTRADICTED")
        unc = verdicts.count("UNCLEAR")
        decided = foll + contr
        rates[label] = (foll / decided) if decided else None
        rate_s = f"{rates[label]:.0%}" if rates[label] is not None else "n/a"
        print(f"{label:>8}: FOLLOWED {foll}  CONTRADICTED {contr}  UNCLEAR {unc}  "
              f"(follow-rate of decided: {rate_s})   {verdicts}")
    print("\n" + "=" * 60)
    if rates.get("with") is not None and rates.get("without") is not None:
        delta = rates["with"] - rates["without"]
        print(f"counterfactual follow-rate  without={rates['without']:.0%}  "
              f"with={rates['with']:.0%}  Δ={delta:+.0%}")
        if delta >= 0.25:
            print("→ registry/wiring measurably helps the Planner obey a counter-prior decision")
        elif rates["without"] >= 0.5:
            print("→ no added value from wiring — agent obeys the file either way")
        else:
            print("→ inconclusive / both weak — counter-prior decision not reliably followed")
    print("=" * 60)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="mode", required=True)
    c = sub.add_parser("capture")
    c.add_argument("--label", required=True)
    c.add_argument("--trials", type=int, default=5)
    c.add_argument("--out", required=True)
    c.set_defaults(func=capture)
    j = sub.add_parser("judge")
    j.add_argument("--a", required=True)
    j.add_argument("--b", required=True)
    j.set_defaults(func=judge)
    args = ap.parse_args()
    if not runner.have_agent() or not runner.have_board():
        print("✗ need the `claude` CLI + a board token", file=sys.stderr)
        return 2
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
