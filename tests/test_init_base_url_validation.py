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
