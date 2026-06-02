"""Behavioral evals — run the real agent against `squad-eval`, score with DeepEval.

Per scenario: optional setup → headless agent run → DETERMINISTIC board-state
assertions (ground truth) → GEval rubric on output quality. Created tasks are
cleaned up after each run (titles carry the "[[eval]]" marker).

Skips cleanly unless the `claude` CLI, ANTHROPIC_API_KEY, and a board token are all
present — so it never blocks a secret-less CI run. Heavy + costs tokens: run
on-demand / nightly, not per-PR (see EVALS.md).
"""
import os
import pathlib
import sys

import pytest
import yaml

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import runner  # noqa: E402

PROJECT = os.environ.get("SQUAD_EVAL_PROJECT", "squad-eval")
SCENARIOS = yaml.safe_load((pathlib.Path(__file__).parent / "scenarios.yaml").read_text())

pytestmark = pytest.mark.skipif(
    not (runner.have_agent() and runner.have_board()),
    reason="behavioral evals need the `claude` CLI, ANTHROPIC_API_KEY, and a board token",
)


def _judge():
    """Prefer an Anthropic judge (the key we already have); else DeepEval default."""
    try:
        if os.environ.get("ANTHROPIC_API_KEY"):
            from deepeval.models import AnthropicModel
            return AnthropicModel(model="claude-sonnet-4-6")
    except Exception:
        pass
    return None


@pytest.mark.parametrize("sc", SCENARIOS, ids=[s["id"] for s in SCENARIOS])
def test_scenario(sc):
    created: list[int] = []
    prompt = sc["prompt"]

    setup = sc.get("setup", {})
    if "create_task" in setup:
        task = runner.create_task(PROJECT, **setup["create_task"])
        created.append(task["id"])
        prompt = prompt.replace("{{task_id}}", str(task["id"]))

    try:
        res = runner.run_agent(prompt)
        assert res["returncode"] == 0, f"agent exited {res['returncode']}"
        exp = sc.get("expect", {})

        # ── deterministic board ground truth ──
        board = exp.get("board")
        if board:
            tasks = runner.board_tasks(PROJECT)
            match = next(
                (t for t in tasks if board["task_with_title"] in (t.get("title") or "")), None)
            assert match, f"no board task titled containing {board['task_with_title']!r}"
            created.append(match["id"])
            if "priority" in board:
                assert match.get("priority") == board["priority"], "priority mismatch"
            if "level" in board:
                assert int(match.get("level")) == board["level"], "level mismatch"

        if "task_description_contains_any" in exp:
            desc = runner.get_task(PROJECT, created[0]).get("description") or ""
            assert any(s in desc for s in exp["task_description_contains_any"]), \
                "refined description missing expected sections"

        # ── output-quality rubric (LLM-as-judge) ──
        rubric = exp.get("rubric")
        if rubric:
            from deepeval import assert_test
            from deepeval.metrics import GEval
            from deepeval.test_case import LLMTestCase, LLMTestCaseParams
            kwargs = dict(
                name=sc["id"],
                criteria=rubric.strip(),
                evaluation_params=[LLMTestCaseParams.INPUT, LLMTestCaseParams.ACTUAL_OUTPUT],
                threshold=0.7,
            )
            judge = _judge()
            if judge:
                kwargs["model"] = judge
            assert_test(LLMTestCase(input=prompt, actual_output=res["output"]), [GEval(**kwargs)])
    finally:
        for tid in dict.fromkeys(created):
            runner.delete_task(PROJECT, tid)
        runner.delete_tasks_by_title(PROJECT, "[[eval]]")
