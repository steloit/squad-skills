#!/usr/bin/env python3
"""Behavioral eval harness — "are the skills working, and is a change better or worse?"

Runs each golden scenario through the *real* headless agent N times against the
`squad-eval` board, scoring on two axes:

  • deterministic board/file ground truth   (hard correctness gate, every run)
  • a GEval rubric via a keyless LLM judge   (output-quality score, 0–1)

Per-trial scores are appended to a git-versioned ``history.jsonl`` and compared against
a trailing baseline (per-scenario floor + Welch's t-test) so genuine regressions fail
the gate while run-to-run noise doesn't. A self-contained HTML trend dashboard is
written to ``results/report.html``.

    python evals/run_evals.py                      # light scenarios, 3 trials, no gate
    python evals/run_evals.py --heavy --trials 5 --gate   # + squad-run/squad-explore, gated
    python evals/run_evals.py --scenario squad-init       # one scenario (heavy/light either way)

Auth: the agent + judge use your Claude Code login (no API key); only a board token
(SQUAD_AUTH_TOKEN / ~/.squad/auth) is required. Set DEEPEVAL_OLLAMA_MODEL to judge
fully offline, or ANTHROPIC_API_KEY for the CI path.
"""
from __future__ import annotations

import argparse
import os
import pathlib
import shutil
import statistics
import subprocess
import sys
import tempfile
import time

import yaml

import baseline as bl
import judge as judgemod
import runner
import scoring
from report import render

MARKER = "[[eval]]"
HERE = pathlib.Path(__file__).parent


# ── helpers for inspecting board state ─────────────────────────────────────────
def _tagstr(tags) -> str:
    return " ".join(tags) if isinstance(tags, list) else (tags or "")


def _nonempty(val) -> bool:
    if isinstance(val, list):
        return len(val) > 0
    return bool(val and str(val).strip() not in ("", "[]", "null"))


def _locate(project: str, title_sub: str) -> dict | None:
    return next((t for t in runner.board_tasks(project)
                 if title_sub in (t.get("title") or "")), None)


def deterministic_check(sc: dict, res: dict, project: str, cwd: pathlib.Path,
                        setup_task_id: int | None = None) -> bool:
    """True iff the agent run reached the scenario's expected board / file state.

    When the scenario seeded the task itself (`setup.create_task`), it's checked by
    its task id — skills like squad-refine rewrite the title, so a title lookup would
    miss. Otherwise (the agent created the task) it's located by `title_contains`.
    """
    if res["returncode"] != 0:
        return False
    exp = sc.get("expect", {})
    ok = True

    bt = exp.get("board_task")
    if bt:
        if setup_task_id is not None:
            full = runner.get_task(project, setup_task_id)
        else:
            located = _locate(project, bt["title_contains"])
            full = runner.get_task(project, located["id"]) if located else None
        if not full or "_error" in full:
            return False
        if "priority" in bt and full.get("priority") != bt["priority"]:
            ok = False
        if "level" in bt and int(full.get("level", -1)) != bt["level"]:
            ok = False
        if "status" in bt and full.get("status") != bt["status"]:
            ok = False
        if "status_not" in bt and full.get("status") == bt["status_not"]:
            ok = False
        if "tags_contains" in bt and bt["tags_contains"] not in _tagstr(full.get("tags")):
            ok = False
        if "description_contains_any" in bt:
            desc = full.get("description") or ""
            if not any(s in desc for s in bt["description_contains_any"]):
                ok = False
        if bt.get("progressed") and not (
                full.get("status") != "todo" or _nonempty(full.get("agent_log"))
                or _nonempty(full.get("plan")) or _nonempty(full.get("implementation_notes"))):
            ok = False

    for crit in exp.get("board_has", []):
        tasks = runner.board_tasks(project)

        def matches(t: dict, crit=crit) -> bool:
            if "title_contains" in crit and crit["title_contains"] not in (t.get("title") or ""):
                return False
            if "tags_contains" in crit and crit["tags_contains"] not in _tagstr(t.get("tags")):
                return False
            return True

        if not any(matches(t) for t in tasks):
            ok = False

    fc = exp.get("file_contains")
    if fc:
        p = cwd / fc["path"]
        text = p.read_text(encoding="utf-8") if p.is_file() else ""
        if not any(s in text for s in fc["any"]):
            ok = False

    return ok


# ── temp workspace setup ───────────────────────────────────────────────────────
def _git_init(tmp: pathlib.Path) -> None:
    def run(*args: str) -> None:
        subprocess.run(["git", *args], cwd=str(tmp), capture_output=True)
    run("init", "-q")
    run("config", "user.email", "eval@squad.local")
    run("config", "user.name", "squad-eval")
    run("remote", "add", "origin", "https://example.com/squad-eval-probe.git")
    if not (tmp / "README.md").exists():
        (tmp / "README.md").write_text("# squad-eval probe\n", encoding="utf-8")
    run("add", "-A")
    run("commit", "-q", "-m", "init")


def _prepare_workspace(sc: dict, tmp: pathlib.Path, project: str) -> None:
    setup = sc.get("setup", {})
    if not setup.get("no_squadrc"):
        (tmp / ".squadrc").write_text(f"SQUAD_PROJECT={project}\n", encoding="utf-8")
    for rel, content in setup.get("workdir_files", {}).items():
        f = tmp / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(content, encoding="utf-8")
    if setup.get("git_init"):
        _git_init(tmp)


# ── one scenario × N trials ─────────────────────────────────────────────────────
def run_scenario(sc: dict, *, project: str, trials: int, judge, floor: float) -> scoring.ScenarioResult:
    score_trials: list[float] = []
    reasons: list[str] = []
    tool_calls: list[int] = []
    durations_s: list[float] = []
    det_passes = 0
    errors = 0
    rubric = sc.get("expect", {}).get("rubric")

    for trial in range(trials):
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="squad-eval-"))
        pre_tasks = {t["id"] for t in runner.board_tasks(project)}
        pre_projects = {p["id"] for p in runner.list_projects()}
        try:
            _prepare_workspace(sc, tmp, project)
            prompt = sc["prompt"]
            setup_task_id = None
            if "create_task" in sc.get("setup", {}):
                task = runner.create_task(project, **sc["setup"]["create_task"])
                setup_task_id = task["id"]
                prompt = prompt.replace("{{task_id}}", str(setup_task_id))

            t0 = time.perf_counter()
            res = runner.run_agent(prompt, cwd=str(tmp), timeout=sc.get("timeout", 600))
            durations_s.append(round(time.perf_counter() - t0, 1))
            if res["returncode"] != 0:
                errors += 1
            tool_calls.append(len(res.get("tools", [])))
            passed = deterministic_check(sc, res, project, tmp, setup_task_id)
            det_passes += int(passed)

            score_str = "n/a"
            if rubric and judge:
                from deepeval.metrics import GEval
                from deepeval.test_case import LLMTestCase, SingleTurnParams
                metric = GEval(
                    name=sc["id"], criteria=rubric.strip(),
                    evaluation_params=[SingleTurnParams.INPUT, SingleTurnParams.ACTUAL_OUTPUT],
                    threshold=floor, model=judge, async_mode=False,
                )
                metric.measure(LLMTestCase(input=prompt, actual_output=res["output"]))
                score_trials.append(float(metric.score))
                reasons.append(metric.reason or "")
                score_str = f"{metric.score:.2f}"
            print(f"  · {sc['id']} trial {trial + 1}/{trials}: "
                  f"board={'ok' if passed else 'FAIL'} score={score_str} "
                  f"t={durations_s[-1]}s tools={tool_calls[-1]}", flush=True)
        finally:
            # snapshot-diff cleanup: remove every task/project that appeared during the trial
            for tid in {t["id"] for t in runner.board_tasks(project)} - pre_tasks:
                runner.delete_task(project, tid)
            runner.delete_tasks_by_title(project, MARKER)
            for pid in {p["id"] for p in runner.list_projects()} - pre_projects:
                runner.delete_project(pid)
            shutil.rmtree(tmp, ignore_errors=True)

    return scoring.ScenarioResult(
        id=sc["id"],
        deterministic_pass=(det_passes == trials),
        deterministic_passes=det_passes,
        trials=trials,
        score=statistics.mean(score_trials) if score_trials else None,
        score_trials=score_trials,
        tool_calls=tool_calls,
        durations_s=durations_s,
        errors=errors,
        reasons=reasons,
        note="" if (not rubric or judge) else "rubric skipped — no judge available",
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--trials", type=int, default=3, help="runs per scenario (default 3)")
    ap.add_argument("--project", default=os.environ.get("SQUAD_EVAL_PROJECT", "squad-eval"))
    ap.add_argument("--scenarios", default=str(HERE / "scenarios.yaml"))
    ap.add_argument("--scenario", action="append", help="limit to scenario id(s); repeatable")
    ap.add_argument("--heavy", action="store_true",
                    help="include heavy scenarios (squad-run, squad-explore) — costlier")
    ap.add_argument("--window", type=int, default=5, help="trailing runs for the baseline")
    ap.add_argument("--floor", type=float, default=0.7, help="per-scenario score floor")
    ap.add_argument("--no-judge", action="store_true", help="board-state checks only")
    ap.add_argument("--no-report", action="store_true")
    ap.add_argument("--gate", action="store_true", help="exit non-zero on failure/regression")
    args = ap.parse_args()

    if not runner.have_agent():
        print("✗ the `claude` CLI is required (agent + keyless judge).", file=sys.stderr)
        return 2
    if not runner.have_board():
        print("✗ a board token is required (SQUAD_AUTH_TOKEN or ~/.squad/auth).", file=sys.stderr)
        return 2

    all_scenarios = yaml.safe_load(pathlib.Path(args.scenarios).read_text())
    if args.scenario:
        wanted = set(args.scenario)
        scenarios = [s for s in all_scenarios if s["id"] in wanted]
    else:
        scenarios = [s for s in all_scenarios if args.heavy or not s.get("heavy")]
    if not scenarios:
        print("✗ no scenarios selected", file=sys.stderr)
        return 2

    skipped_heavy = [s["id"] for s in all_scenarios
                     if s.get("heavy") and s not in scenarios]
    judge, judge_name = (None, None) if args.no_judge else judgemod.resolve_judge()
    print(f"▶ {len(scenarios)} scenario(s) × {args.trials} trial(s) on '{args.project}' "
          f"· judge: {judge_name or 'none (board-state only)'}")
    if skipped_heavy:
        print(f"  (skipping heavy: {', '.join(skipped_heavy)} — pass --heavy to include)")
    print()

    prior = scoring.load_history()  # baseline = runs before this one
    results = [run_scenario(sc, project=args.project, trials=args.trials,
                            judge=judge, floor=args.floor) for sc in scenarios]

    verdicts: dict[str, bl.Verdict] = {}
    for r in results:
        base_scores, base_runs = bl.trailing_scores(prior, r.id, args.window)
        verdicts[r.id] = bl.assess(current_trials=r.score_trials, baseline=base_scores,
                                   baseline_runs=base_runs, floor=args.floor)

    record = scoring.RunRecord.build(agent="claude-code-cli", judge=judge_name,
                                     trials=args.trials, scenarios=results)
    scoring.append_run(record)

    # ── summary ──
    icons = {bl.REGRESSION: "🔴", bl.BELOW_FLOOR: "🔴", bl.IMPROVE: "🟢",
             bl.PASS: "⚪", bl.NO_BASELINE: "🔵", bl.NO_SCORE: "⚪"}
    print("\n" + "=" * 72)
    hard_fail, regressed = [], []
    for r in results:
        v = verdicts[r.id]
        if not r.deterministic_pass:
            hard_fail.append(r.id)
        if v.gate_fails:
            regressed.append(r.id)
        score = "—" if r.score is None else f"{r.score:.2f}"
        print(f"{icons.get(v.status, '·')} {r.id:<14} board {r.deterministic_passes}/{r.trials}  "
              f"score {score:<6} {v.status:<11} {v.detail}")
    print("=" * 72)

    if not args.no_report:
        out = render(scoring.load_history(), verdicts, floor=args.floor,
                     out_path=scoring.RESULTS_DIR / "report.html")
        print(f"report → {out}")
    print(f"history → {scoring.HISTORY} ({len(scoring.load_history())} runs)")

    gate_ok = not hard_fail and not regressed
    if not gate_ok:
        print(f"\n✗ GATE: hard-fail={hard_fail or '∅'} regressions={regressed or '∅'}")
    else:
        print("\n✓ GATE: deterministic checks pass; no regressions vs baseline")
    return 1 if (args.gate and not gate_ok) else 0


if __name__ == "__main__":
    raise SystemExit(main())
