"""Deterministic tests for squad/scripts/render_agent_prompt.py.

Provider resolution + placeholder rendering against the real models.json.
"""
import json
import subprocess
import sys


# ── parse_set ────────────────────────────────────────────────────────────────
def test_parse_set_ok(render_mod):
    assert render_mod.parse_set(["A=1", "B=x=y"]) == {"A": "1", "B": "x=y"}


def test_parse_set_rejects_missing_equals(render_mod):
    try:
        render_mod.parse_set(["noequals"])
    except ValueError:
        return
    raise AssertionError("expected ValueError for KEY without =")


# ── resolve_provider precedence ──────────────────────────────────────────────
def test_resolve_provider_cli_wins(render_mod):
    assert render_mod.resolve_provider("codex") == "codex"


def test_resolve_provider_env(render_mod, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)  # no .claude/.codex dirs here
    for v in ("SQUAD_MODEL_PROVIDER", "CODEX_THREAD_ID", "CODEX_CI", "CLAUDE_PROJECT_DIR", "CLAUDECODE"):
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setenv("SQUAD_MODEL_PROVIDER", "claude")
    assert render_mod.resolve_provider(None) == "claude"


def test_resolve_provider_codex_env_signal(render_mod, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    for v in ("SQUAD_MODEL_PROVIDER", "CODEX_THREAD_ID", "CODEX_CI", "CLAUDE_PROJECT_DIR", "CLAUDECODE"):
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setenv("CODEX_THREAD_ID", "abc")
    assert render_mod.resolve_provider(None) == "codex"


def test_resolve_provider_dir_signal(render_mod, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    for v in ("SQUAD_MODEL_PROVIDER", "CODEX_THREAD_ID", "CODEX_CI", "CLAUDE_PROJECT_DIR", "CLAUDECODE"):
        monkeypatch.delenv(v, raising=False)
    (tmp_path / ".claude").mkdir()
    assert render_mod.resolve_provider(None) == "claude"


def test_resolve_provider_none_when_no_signal(render_mod, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    for v in ("SQUAD_MODEL_PROVIDER", "CODEX_THREAD_ID", "CODEX_CI", "CLAUDE_PROJECT_DIR", "CLAUDECODE"):
        monkeypatch.delenv(v, raising=False)
    assert render_mod.resolve_provider(None) == ""


# ── End-to-end render against the real models.json ───────────────────────────
def test_render_replaces_placeholders(repo_root, tmp_path):
    models = repo_root / "skills" / "squad" / "models.json"
    cfg = json.loads(models.read_text())
    provider = cfg.get("default_provider", "claude")
    expected_worker = cfg["providers"][provider]["worker"]

    template = tmp_path / "tpl.md"
    template.write_text("worker=<MODEL_WORKER> set=<FOO>\n")
    script = repo_root / "skills" / "squad" / "scripts" / "render_agent_prompt.py"

    out = subprocess.run(
        [sys.executable, str(script), "--template", str(template),
         "--models", str(models), "--provider", provider, "--set", "FOO=bar"],
        capture_output=True, text=True, check=True,
    ).stdout
    assert f"worker={expected_worker}" in out
    assert "set=bar" in out
    assert "<MODEL_WORKER>" not in out


def test_render_strict_fails_on_unresolved(repo_root, tmp_path):
    models = repo_root / "skills" / "squad" / "models.json"
    template = tmp_path / "tpl.md"
    template.write_text("unknown=<NOPE>\n")
    script = repo_root / "skills" / "squad" / "scripts" / "render_agent_prompt.py"
    res = subprocess.run(
        [sys.executable, str(script), "--template", str(template),
         "--models", str(models), "--provider", "claude", "--strict"],
        capture_output=True, text=True,
    )
    assert res.returncode == 2
    assert "unresolved placeholders" in res.stderr
