"""squad-init must never persist a non-URL --base-url to the global ~/.squad/config.

Regression guard for the config-poisoning bug: a mispassed filesystem path (or any
non-http(s) string) handed to --base-url was written verbatim to ~/.squad/config as
SQUAD_BASE_URL, silently breaking board access for EVERY project on the machine
(api.py then built '<path>/api/orgs/...' and crashed). The skill must reject a
non-http(s) --base-url before touching env or the global config.

Hermetic: runs init.py in a clean temp cwd with a redirected HOME so the real
~/.squad/config is never touched.
"""
import os
import subprocess
import sys


INIT = "skills/squad-init/scripts/init.py"


def _run(repo_root, args, cwd, home):
    env = dict(os.environ, HOME=str(home), SQUAD_ORG="steloit")
    env.pop("SQUAD_BASE_URL", None)
    return subprocess.run([sys.executable, str(repo_root / INIT), *args],
                          cwd=str(cwd), env=env, capture_output=True, text=True, timeout=30)


def test_non_url_base_url_is_rejected_and_config_untouched(repo_root, tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    home = tmp_path / "home"
    home.mkdir()

    proc = _run(repo_root, ["--project", "p", "--org", "steloit",
                            "--base-url", "/private/tmp/evil"], work, home)

    assert proc.returncode == 2, f"expected exit 2, got {proc.returncode}: {proc.stderr}"
    assert "must be an http(s) URL" in proc.stderr
    cfg = home / ".squad" / "config"
    assert not cfg.exists() or "SQUAD_BASE_URL=/private" not in cfg.read_text(), (
        "a non-URL --base-url must NOT be persisted to ~/.squad/config"
    )


def test_bare_hostname_without_scheme_is_rejected(repo_root, tmp_path):
    work = tmp_path / "work"; work.mkdir()
    home = tmp_path / "home"; home.mkdir()
    proc = _run(repo_root, ["--project", "p", "--org", "steloit",
                            "--base-url", "board.example.com"], work, home)
    assert proc.returncode == 2, f"a scheme-less host must be rejected: {proc.stderr}"
    cfg = home / ".squad" / "config"
    assert not cfg.exists() or "board.example.com" not in cfg.read_text()


def test_refuses_to_register_a_skill_directory(repo_root, tmp_path):
    """The core cwd bug: an agent that cd's into the skill dir (which holds SKILL.md)
    must NOT get .squadrc written there — init.py refuses a skill directory."""
    skill = tmp_path / "skill"; skill.mkdir()
    (skill / "SKILL.md").write_text("---\nname: x\n---\n")
    home = tmp_path / "home"; home.mkdir()
    proc = _run(repo_root, ["--project", "p", "--org", "steloit"], skill, home)
    assert proc.returncode == 2, f"a skill dir must be refused: {proc.stderr}"
    assert "skill directory" in proc.stderr
    assert not (skill / ".squadrc").exists(), "must NOT write .squadrc into a skill directory"


def test_dir_targets_an_explicit_repo_not_cwd(repo_root, tmp_path):
    """--dir writes .squadrc to the TARGET repo, not the process cwd (which may be a skill dir)."""
    cwd = tmp_path / "skill"; cwd.mkdir()
    (cwd / "SKILL.md").write_text("---\nname: x\n---\n")   # cwd is a skill dir (would be refused)
    target = tmp_path / "repo"; target.mkdir()
    home = tmp_path / "home"; home.mkdir()
    # No auth in the redirected HOME → board registration is skipped, but .squadrc still writes.
    proc = _run(repo_root, ["--dir", str(target), "--project", "myproj", "--org", "steloit"],
                cwd, home)
    assert proc.returncode == 0, f"--dir target should succeed: {proc.stderr}"
    rc = target / ".squadrc"
    assert rc.is_file() and "SQUAD_PROJECT=myproj" in rc.read_text()
    assert not (cwd / ".squadrc").exists(), "must not touch the cwd skill dir"
