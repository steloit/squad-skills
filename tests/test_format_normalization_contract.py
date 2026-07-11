"""Contract guards for the impl-step format-normalization step.

The contract survived the skills-efficiency re-architecture but the mechanism
moved: the orchestration prose that used to live in squad-run/SKILL.md is now
the deterministic engine command ``pipeline.py normalize`` (the ``FORMATTERS``
ladder + ``cmd_normalize`` in ``skills/squad/scripts/pipeline.py``), invoked by
the orchestrator per squad-run/SKILL.md's impl-step ordering line.

Load-bearing properties (mechanism-appropriate re-assertions of the old
SKILL.md prose contract):

1. Seam ordering  — squad-run/SKILL.md's impl step runs ``pipe normalize`` AFTER
   Builder+Shield record and BEFORE ``advance`` (the impl→impl_review move).
2. Format-only    — every command the FORMATTERS ladder can build is a
   formatter write/format-mode command; no lint / ``--fix`` / ``check`` command
   anywhere in the ladder (genuine lint errors still reach the Ranger gate).
3. Tool-agnostic  — the ladder resolves across multiple tools and ecosystems
   (repo ``format`` script first, then biome/ruff/black/gofmt/rustfmt/prettier),
   never hard-coded to one stack.
4. Skip-clean     — no changed files → clean no-op with no board write; no
   resolvable formatter → a logged Orchestrator activity note and a clean skip;
   a failing formatter is logged and never raises (best-effort, never blocks).
5. Bounded set    — only the changed files (tracked diff + untracked) are passed
   to the formatter, and they are re-staged afterwards — never the whole repo.
6. Backstops      — worker-agent.md and tdd-tester.md still instruct Builder and
   Shield to run the resolved formatter themselves and verify it exits clean
   before recording results (the L1 / self-format backstop).

Deleted from the old suite (structurally obsolete):
- All assertions on the removed "Impl-Step Format Normalization" prose section
  of SKILL.md (pre-impl_review label, eslint-disable/biome-ignore wording,
  L1-exclusion wording) — the behavior is engine code now and is unit-tested
  here directly; the seam-ordering line in SKILL.md is still asserted.

Hermetic: ``_req`` is always stubbed (no network); git operations run in
tmp_path repos.
"""
import json
import re
import subprocess
import sys
from types import SimpleNamespace


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _stub_req(monkeypatch, pipeline_mod, handler=None):
    calls = []

    def fake_req(method, path, body=None):
        calls.append((method, path, body))
        if handler:
            return handler(method, path, body)
        return 0, {}

    monkeypatch.setattr(pipeline_mod, "_req", fake_req)
    return calls


def _init_repo(path):
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=path, check=True)
    subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=path, check=True)


def _commit_all(path, msg="init"):
    subprocess.run(["git", "add", "-A"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-q", "-m", msg], cwd=path, check=True, capture_output=True)


def _built_commands(pipeline_mod, tmp_path, monkeypatch):
    """Build every command the ladder can produce, in an empty dir (so builders
    that inspect lockfiles fall back deterministically)."""
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.chdir(empty)
    return [build() for _probe, build in pipeline_mod.FORMATTERS]


# ---------------------------------------------------------------------------
# 1. Seam ordering in squad-run/SKILL.md: normalize BEFORE advance
# ---------------------------------------------------------------------------

def test_skill_impl_step_runs_normalize_before_advance(repo_root):
    """The impl-step ordering line must run `pipe normalize` after Builder+Shield
    record and before `advance` — the load-bearing seam."""
    text = (repo_root / "skills/squad-run/SKILL.md").read_text()
    line = next((ln for ln in text.splitlines() if "Impl step ordering" in ln), None)
    assert line, "squad-run/SKILL.md must carry the 'Impl step ordering' instruction"
    norm_at = line.find("pipe normalize")
    advance_at = line.find("advance")
    shield_at = line.find("shield")
    assert norm_at != -1, "impl-step ordering must invoke `pipe normalize`"
    assert advance_at != -1, "impl-step ordering must end with advance"
    assert shield_at != -1 and shield_at < norm_at, (
        "normalize must run AFTER the Shield sub-step"
    )
    assert norm_at < advance_at, (
        "`pipe normalize` must precede `advance` (normalization happens before "
        "the impl→impl_review move)"
    )


def test_skill_labels_normalize_best_effort(repo_root):
    text = (repo_root / "skills/squad-run/SKILL.md").read_text()
    assert "best-effort" in text and "normalize" in text, (
        "squad-run/SKILL.md must label the normalize step best-effort"
    )


# ---------------------------------------------------------------------------
# 2. Format-only, lint-transparent — the ladder builds formatter commands only
# ---------------------------------------------------------------------------

def test_ladder_commands_are_format_mode_only(pipeline_mod, tmp_path, monkeypatch):
    """No ladder command may run lint, `--fix`, or a combined check mode — the
    step must never mask genuine lint/type errors (they still reach Ranger)."""
    for cmd in _built_commands(pipeline_mod, tmp_path, monkeypatch):
        joined = " ".join(cmd)
        assert "lint" not in joined, f"ladder built a lint command: {cmd}"
        assert "--fix" not in cmd, f"ladder built a --fix command: {cmd}"
        assert "check" not in cmd, (
            f"ladder built a check-mode command (applies lint fixes): {cmd}"
        )


def test_biome_rung_uses_format_write_not_check_write(pipeline_mod, tmp_path, monkeypatch):
    """The biome rung must be `biome format --write` (format-only), never
    `biome check --write` (which also applies lint fixes)."""
    cmds = _built_commands(pipeline_mod, tmp_path, monkeypatch)
    biome = [c for c in cmds if c and c[0] == "biome"]
    assert biome, "the FORMATTERS ladder must include a biome rung"
    assert biome[0] == ["biome", "format", "--write"], (
        f"biome rung must be format-only: got {biome[0]}"
    )


# ---------------------------------------------------------------------------
# 3. Tool-agnostic ladder, repo format script first
# ---------------------------------------------------------------------------

def test_ladder_is_tool_agnostic(pipeline_mod, tmp_path, monkeypatch):
    """The ladder must cover multiple distinct tools/ecosystems, not one stack."""
    cmds = _built_commands(pipeline_mod, tmp_path, monkeypatch)
    tools = {c[0] for c in cmds}
    named = {"biome", "ruff", "black", "gofmt", "rustfmt", "prettier"}
    assert len(tools & named) >= 3, (
        f"FORMATTERS must name >=3 distinct formatter tools (found: {sorted(tools)})"
    )
    assert len(pipeline_mod.FORMATTERS) >= 4, "the ladder must have multiple rungs"


def test_repo_format_script_is_first_rung(pipeline_mod, tmp_path, monkeypatch):
    """The repo's own `format` script (package.json) must be the FIRST rung, and
    the lockfile decides the runner (pnpm-lock.yaml → pnpm run format)."""
    repo = tmp_path / "jsrepo"
    repo.mkdir()
    (repo / "package.json").write_text('{"scripts": {"format": "biome format --write ."}}')
    (repo / "pnpm-lock.yaml").write_text("")
    monkeypatch.chdir(repo)
    probe, build = pipeline_mod.FORMATTERS[0]
    assert probe(), "first rung must probe package.json for a 'format' script"
    assert build() == ["pnpm", "run", "format"]


def test_makefile_and_justfile_format_targets_are_rungs(pipeline_mod, tmp_path, monkeypatch):
    """Task-runner format targets (make/just) must be on the ladder before raw
    tool detection."""
    cmds = _built_commands(pipeline_mod, tmp_path, monkeypatch)
    assert ["make", "format"] in cmds, "ladder must include `make format`"
    assert ["just", "format"] in cmds, "ladder must include `just format`"


# ---------------------------------------------------------------------------
# 4. Skip-clean behaviors of cmd_normalize
# ---------------------------------------------------------------------------

def test_normalize_is_clean_noop_with_no_changed_files(pipeline_mod, tmp_path, monkeypatch, capsys):
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    (repo / "a.txt").write_text("hello\n")
    _commit_all(repo)
    monkeypatch.chdir(repo)
    calls = _stub_req(monkeypatch, pipeline_mod)

    pipeline_mod.cmd_normalize(SimpleNamespace(id="1"))

    out = json.loads(capsys.readouterr().out)
    assert out == {"normalized": False, "reason": "no changed files"}
    assert calls == [], "a clean no-op must issue no board writes"


def test_normalize_skips_cleanly_and_logs_when_no_formatter(pipeline_mod, tmp_path, monkeypatch, capsys):
    """With changed files but no resolvable formatter: post a skipped note
    (actor Orchestrator, model system) and never raise."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    (repo / "a.txt").write_text("hello\n")
    _commit_all(repo)
    (repo / "a.txt").write_text("changed\n")
    monkeypatch.chdir(repo)
    monkeypatch.setattr(pipeline_mod, "FORMATTERS", [])
    calls = _stub_req(monkeypatch, pipeline_mod)

    pipeline_mod.cmd_normalize(SimpleNamespace(id="9"))

    out = json.loads(capsys.readouterr().out)
    assert out["normalized"] is False
    assert "no formatter resolved" in out["reason"]
    posts = [c for c in calls if c[0] == "POST"]
    assert len(posts) == 1 and posts[0][1] == "/task/9/activity"
    body = posts[0][2]
    assert body["actor"] == "Orchestrator" and body["model"] == "system"
    assert "no formatter resolved" in body["message"] and "skipped" in body["message"]


def test_normalize_never_raises_on_formatter_failure(pipeline_mod, tmp_path, monkeypatch, capsys):
    """A formatter exiting non-zero is logged (best-effort note) and normalize
    still completes — it never blocks the pipeline."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    (repo / "a.txt").write_text("hello\n")
    _commit_all(repo)
    (repo / "a.txt").write_text("changed\n")
    monkeypatch.chdir(repo)
    failing = [(lambda: True, lambda: [sys.executable, "-c", "import sys; sys.exit(3)"])]
    monkeypatch.setattr(pipeline_mod, "FORMATTERS", failing)
    calls = _stub_req(monkeypatch, pipeline_mod)

    pipeline_mod.cmd_normalize(SimpleNamespace(id="9"))  # must not raise

    out = json.loads(capsys.readouterr().out)
    assert out["normalized"] is True and out["formatter_exit"] == 3
    posts = [c for c in calls if c[0] == "POST"]
    assert len(posts) == 1
    assert "non-zero" in posts[0][2]["message"]
    assert posts[0][2]["actor"] == "Orchestrator"


# ---------------------------------------------------------------------------
# 5. Bounded changed-file set (tracked diff + untracked) + re-stage
# ---------------------------------------------------------------------------

def test_normalize_passes_bounded_changed_set_and_restages(pipeline_mod, tmp_path, monkeypatch, capsys):
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    (repo / "a.txt").write_text("hello\n")
    (repo / "untouched.txt").write_text("same\n")
    _commit_all(repo)
    (repo / "a.txt").write_text("changed\n")     # tracked, modified
    (repo / "b.txt").write_text("new\n")         # untracked

    argv_out = tmp_path / "argv.txt"
    recorder = tmp_path / "recorder.py"
    recorder.write_text(
        "import sys, pathlib\n"
        f"pathlib.Path({str(argv_out)!r}).write_text('\\n'.join(sys.argv[1:]))\n"
    )
    monkeypatch.chdir(repo)
    monkeypatch.setattr(
        pipeline_mod, "FORMATTERS",
        [(lambda: True, lambda: [sys.executable, str(recorder)])],
    )
    _stub_req(monkeypatch, pipeline_mod)

    pipeline_mod.cmd_normalize(SimpleNamespace(id="9"))

    out = json.loads(capsys.readouterr().out)
    assert out["normalized"] is True and out["files"] == 2
    passed = set(argv_out.read_text().splitlines())
    assert passed == {"a.txt", "b.txt"}, (
        "the formatter must receive exactly the changed files (tracked diff + "
        f"untracked), never the whole repo: got {passed}"
    )
    status = subprocess.run(["git", "status", "--porcelain"], cwd=repo,
                            capture_output=True, text=True).stdout
    assert "M  a.txt" in status and "A  b.txt" in status, (
        "normalize must re-stage the changed files after formatting"
    )


# ---------------------------------------------------------------------------
# 6. Template backstops: Builder + Shield self-format before recording
# ---------------------------------------------------------------------------

def _your_job(text):
    m = re.search(r"^##\s+Your Job\b.*?(?=^##\s|\Z)", text, re.MULTILINE | re.DOTALL)
    return m.group(0) if m else ""


def test_worker_agent_self_format_backstop(repo_root):
    """worker-agent.md ## Your Job must instruct Builder to run the resolved
    formatter on touched files + the test command, both clean before recording
    (the L1 backstop — L1 has no orchestrator normalize seam before done)."""
    job = _your_job((repo_root / "skills/squad/templates/worker-agent.md").read_text())
    assert job, "worker-agent.md must have a '## Your Job' section"
    assert "formatter" in job.lower(), "Builder must run the formatter itself"
    assert "test" in job.lower(), "Builder must run the test command too"
    assert "clean" in job.lower() and "record" in job.lower(), (
        "worker-agent.md must require a clean exit before recording results"
    )


def test_tdd_tester_self_format_backstop(repo_root):
    job = _your_job((repo_root / "skills/squad/templates/tdd-tester.md").read_text())
    assert job, "tdd-tester.md must have a '## Your Job' section"
    assert "formatter" in job.lower(), "Shield must run the formatter itself"
    assert "clean" in job.lower() and "record" in job.lower(), (
        "tdd-tester.md must require a clean exit before recording results"
    )


def test_both_backstops_resolve_commands_not_hardcode(repo_root):
    """Both templates must resolve the formatter via the Command-resolution rule
    (injected shared rules), not name a single tool as THE formatter."""
    for rel in ("skills/squad/templates/worker-agent.md",
                "skills/squad/templates/tdd-tester.md"):
        text = (repo_root / rel).read_text()
        assert "Command resolution" in text, (
            f"{rel} must point the formatter run at the Command resolution rule"
        )
