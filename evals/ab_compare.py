#!/usr/bin/env python3
"""A/B comparison harness — pairwise LLM-judge of two skill versions on the same task.

Pointwise GEval scores floor near the top of the keyless judge's range and can't resolve
*incremental* quality ("is B better than A?"). Pairwise comparison is far more sensitive
and stays keyless. Two phases:

  capture : run the *currently installed* skill on a scenario N times; save the refined
            artifact to JSON. Run once per version, swapping the install between.
  judge   : pairwise-judge A vs B on each trial in BOTH orderings (cancels position bias);
            report wins / losses / ties.

    python evals/ab_compare.py capture --scenario refine-gaps --trials 3 --label old --out /tmp/old.json
    # (swap the install)
    python evals/ab_compare.py capture --scenario refine-gaps --trials 3 --label improved --out /tmp/new.json
    python evals/ab_compare.py judge --a /tmp/old.json --b /tmp/new.json

Keyless: agent runs + judge both use the Claude Code login. Only a board token is needed.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import shutil
import sys
import tempfile

import yaml

import runner

HERE = pathlib.Path(__file__).parent
MARKER = "[[eval]]"


def _load_scenario(scenario_id: str, path: str) -> dict:
    scs = yaml.safe_load(pathlib.Path(path).read_text())
    sc = next((s for s in scs if s["id"] == scenario_id), None)
    if not sc:
        sys.exit(f"✗ no scenario '{scenario_id}' in {path}")
    return sc


def capture(args) -> None:
    sc = _load_scenario(args.scenario, args.scenarios)
    project = args.project
    outputs = []
    for t in range(args.trials):
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="ab-"))
        pre = {x["id"] for x in runner.board_tasks(project)}
        try:
            (tmp / ".squadrc").write_text(f"SQUAD_PROJECT={project}\n")
            prompt, task_id = sc["prompt"], None
            if "create_task" in sc.get("setup", {}):
                task = runner.create_task(project, **sc["setup"]["create_task"])
                task_id = task["id"]
                prompt = prompt.replace("{{task_id}}", str(task_id))
            res = runner.run_agent(prompt, cwd=str(tmp), timeout=sc.get("timeout", 600))
            refined = runner.get_task(project, task_id).get("description", "") if task_id else ""
            artifact = (refined or "").strip() or res["output"]
            outputs.append({"trial": t, "refined_description": refined,
                            "artifact": artifact, "returncode": res["returncode"]})
            print(f"  captured {args.label} {t + 1}/{args.trials} "
                  f"(rc={res['returncode']}, {len(artifact)} chars)", flush=True)
        finally:
            for tid in {x["id"] for x in runner.board_tasks(project)} - pre:
                runner.delete_task(project, tid)
            runner.delete_tasks_by_title(project, MARKER)
            shutil.rmtree(tmp, ignore_errors=True)
    data = {
        "scenario": args.scenario,
        "label": args.label,
        "rubric": (sc.get("expect", {}).get("rubric") or "").strip(),
        "brief": (sc.get("setup", {}).get("create_task", {}).get("description") or "").strip(),
        "outputs": outputs,
    }
    pathlib.Path(args.out).write_text(json.dumps(data, indent=2))
    print(f"saved {len(outputs)} {args.label} outputs → {args.out}")


def _which_better(rubric: str, brief: str, spec_x: str, spec_y: str) -> str:
    """Ask the keyless judge which of two specs is better. Returns 'X', 'Y', or 'TIE'."""
    prompt = (
        "You are judging two refined requirement specs produced for the SAME task.\n\n"
        f"Original brief:\n{brief}\n\n"
        f"Quality criteria:\n{rubric}\n\n"
        f"--- SPEC X ---\n{spec_x}\n\n"
        f"--- SPEC Y ---\n{spec_y}\n\n"
        "Which spec better satisfies the criteria? Consider only the criteria above.\n"
        'Reply with ONLY one token: "X", "Y", or "TIE".'
    )
    resp = runner.claude_text(prompt).strip().upper()
    head = resp[:8]
    if "TIE" in head:
        return "TIE"
    if "X" in head and "Y" not in head:
        return "X"
    if "Y" in head and "X" not in head:
        return "Y"
    return "TIE"


def judge(args) -> None:
    A = json.loads(pathlib.Path(args.a).read_text())
    B = json.loads(pathlib.Path(args.b).read_text())
    rubric = A.get("rubric") or B.get("rubric")
    brief = A.get("brief") or B.get("brief")
    a_label, b_label = A.get("label", "A"), B.get("label", "B")
    a_out = [o["artifact"] for o in A["outputs"]]
    b_out = [o["artifact"] for o in B["outputs"]]
    n = min(len(a_out), len(b_out))
    print(f"pairwise: {a_label} vs {b_label} · {n} pairs × 2 orderings\n")

    wins = {a_label: 0, b_label: 0, "TIE": 0}

    def tally(verdict: str, x_label: str, y_label: str) -> str:
        w = x_label if verdict == "X" else y_label if verdict == "Y" else "TIE"
        wins[w] += 1
        return w

    for i in range(n):
        r1 = _which_better(rubric, brief, a_out[i], b_out[i])   # X=a, Y=b
        r2 = _which_better(rubric, brief, b_out[i], a_out[i])   # X=b, Y=a (swapped)
        w1, w2 = tally(r1, a_label, b_label), tally(r2, b_label, a_label)
        print(f"  pair {i + 1}/{n}: ordering1 → {w1:<10} ordering2 → {w2}", flush=True)

    decided = wins[a_label] + wins[b_label]
    print("\n" + "=" * 56)
    print(f"  {a_label}: {wins[a_label]}   {b_label}: {wins[b_label]}   tie: {wins['TIE']}"
          f"   (of {sum(wins.values())} judgments)")
    if decided:
        rate = wins[b_label] / decided
        winner = b_label if wins[b_label] > wins[a_label] else a_label if wins[a_label] > wins[b_label] else "even"
        print(f"  decided win-rate for '{b_label}': {rate:.0%}  →  winner: {winner}")
    print("=" * 56)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="mode", required=True)

    c = sub.add_parser("capture", help="run installed skill N times, save artifacts")
    c.add_argument("--scenario", required=True)
    c.add_argument("--trials", type=int, default=3)
    c.add_argument("--label", required=True, help="version label, e.g. old / improved")
    c.add_argument("--out", required=True)
    c.add_argument("--project", default="squad-eval")
    c.add_argument("--scenarios", default=str(HERE / "scenarios.yaml"))
    c.set_defaults(func=capture)

    j = sub.add_parser("judge", help="pairwise-judge two captured sets")
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
