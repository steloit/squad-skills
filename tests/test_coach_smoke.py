"""Deterministic checks for the Coach smoke harness + coach.md render.

The Coach itself is an LLM (live dispatch + 2-of-3 judgment runs in Shield); these tests cover the
deterministic render layer only: coach.md resolves <MODEL_COACH>/<EFFORT_COACH> from models.json and
both seeded smoke trajectories render --strict-clean with their seeded evidence embedded.
"""
import json
import subprocess
import sys


def _coach_smoke_path(repo_root):
    return repo_root / "skills" / "squad" / "scripts" / "coach_smoke.py"


def test_coach_key_in_models(repo_root):
    cfg = json.loads((repo_root / "skills" / "squad" / "models.json").read_text())
    assert cfg["providers"]["claude"]["coach"] == "haiku"
    assert cfg["providers"]["codex"]["coach"] == "gpt-5.2"
    assert cfg["reasoning_effort"]["codex"]["coach"] == "low"


def test_render_resolves_coach_tokens(repo_root, tmp_path):
    models = repo_root / "skills" / "squad" / "models.json"
    template = repo_root / "skills" / "squad" / "templates" / "coach.md"
    script = repo_root / "skills" / "squad" / "scripts" / "render_agent_prompt.py"
    res = subprocess.run(
        [sys.executable, str(script), "--template", str(template),
         "--models", str(models), "--provider", "claude",
         "--set", "run_summary=x", "--set", "trajectory=x", "--set", "friction_signals=x",
         "--set", "skill_name=squad-run", "--set", "source_project=p", "--set", "source_task=1",
         "--set", "TIMESTAMP=t", "--set", "PROJECT=squad", "--strict",
         "--ignore", "run_summary", "--ignore", "trajectory", "--ignore", "friction_signals",
         "--ignore", "skill_name", "--ignore", "source_project", "--ignore", "source_task",
         "--ignore", "PROJECT", "--ignore", "TIMESTAMP"],
        capture_output=True, text=True,
    )
    assert res.returncode == 0, res.stderr
    assert "<MODEL_COACH>" not in res.stdout
    assert "<EFFORT_COACH>" not in res.stdout
    assert "resolved to `haiku`" in res.stdout


def test_smoke_A_renders_clean_with_evidence(repo_root):
    res = subprocess.run(
        [sys.executable, str(_coach_smoke_path(repo_root)), "--provider", "claude", "--smoke", "A"],
        capture_output=True, text=True,
    )
    assert res.returncode == 0, res.stderr
    assert "shared.md:351" in res.stdout        # seeded Squad-itself friction evidence
    assert "<MODEL_COACH>" not in res.stdout


def test_smoke_B_renders_clean_with_project_bug(repo_root):
    res = subprocess.run(
        [sys.executable, str(_coach_smoke_path(repo_root)), "--provider", "claude", "--smoke", "B"],
        capture_output=True, text=True,
    )
    assert res.returncode == 0, res.stderr
    assert "demo/src/app.js:42" in res.stdout    # seeded worked-project bug (must NOT be filed)
    assert "<MODEL_COACH>" not in res.stdout
