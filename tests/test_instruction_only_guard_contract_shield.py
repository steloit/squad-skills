"""Shield extensions to the repo-level Vale guard contract test.

The Builder's test_instruction_only_guard_contract.py covers the top-level
wiring (Vale config exists, tokens present, CI wired). This file covers the gaps:

1. Style YAML is well-formed (yaml.safe_load parseable).
2. CI workflow triggers are complete (pull_request + push:[main] + workflow_dispatch).
3. BEHAVIORAL: a planted forbidden phrase in running prose IS flagged by real
   `vale`; the SAME phrase inside a fenced code block is NOT flagged (scope:paragraph
   guarantee). SKIP cleanly when vale is absent.
4. Excluded phrases (by construction, language-agnostic) in prose are NOT flagged
   by real `vale`. SKIP cleanly when vale is absent.

Does NOT duplicate the Builder's assertions (file existence, token set,
`errata-ai/vale-action`, `fail_on_error`).

Stdlib + yaml (available in test env via requirements.txt).
"""

import shutil
import subprocess
import textwrap

import pytest
import yaml

# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

VALE_AVAILABLE = shutil.which("vale") is not None


def _read(repo_root, rel: str) -> str:
    return (repo_root / rel).read_text(encoding="utf-8")


# ──────────────────────────────────────────────────────────────────────────────
# 1. YAML well-formedness
# ──────────────────────────────────────────────────────────────────────────────


def test_instruction_only_style_yaml_is_parseable(repo_root):
    """styles/Squad/InstructionOnly.yml parses without error via yaml.safe_load
    and the parsed structure matches the expected schema keys."""
    path = repo_root / "styles" / "Squad" / "InstructionOnly.yml"
    assert path.is_file(), "styles/Squad/InstructionOnly.yml missing"
    raw = path.read_text(encoding="utf-8")
    data = yaml.safe_load(raw)  # raises on malformed YAML
    assert isinstance(data, dict), "InstructionOnly.yml must parse to a mapping"
    # Required keys the existence-rule schema mandates
    for key in ("extends", "level", "tokens"):
        assert key in data, f"InstructionOnly.yml is missing required key: {key!r}"
    assert data["extends"] == "existence", "extends must be 'existence'"
    assert data["level"] == "error", "level must be 'error'"
    assert isinstance(data["tokens"], list), "tokens must be a YAML sequence"
    assert len(data["tokens"]) >= 4, "at least 4 tokens expected"
    # scope key must be present (paragraph)
    assert "scope" in data, "scope key missing — needed to skip code blocks"
    assert data["scope"] == "paragraph", "scope must be 'paragraph'"


# ──────────────────────────────────────────────────────────────────────────────
# 2. CI workflow triggers
# ──────────────────────────────────────────────────────────────────────────────


def test_vale_ci_has_all_required_triggers(repo_root):
    """The vale CI workflow fires on pull_request, push to main, AND
    workflow_dispatch (matches the one-concern-per-workflow convention in the
    repo and ensures manual re-runs are possible)."""
    txt = _read(repo_root, ".github/workflows/vale.yml")
    wf = yaml.safe_load(txt)
    on = wf.get("on") or wf.get(True)  # YAML parses bare `on` as bool True
    assert on is not None, "vale.yml missing 'on:' trigger block"
    trigger_keys = set(on.keys()) if isinstance(on, dict) else set()
    assert "pull_request" in trigger_keys, "vale CI must trigger on pull_request"
    assert "push" in trigger_keys, "vale CI must trigger on push"
    assert "workflow_dispatch" in trigger_keys, (
        "vale CI must trigger on workflow_dispatch (manual re-run)"
    )
    # push must restrict to main branch
    push_cfg = on.get("push", {})
    branches = push_cfg.get("branches", []) if isinstance(push_cfg, dict) else []
    assert "main" in branches, "push trigger must restrict to [main]"


# ──────────────────────────────────────────────────────────────────────────────
# 3 & 4. BEHAVIORAL: real vale subprocess tests (SKIP when vale absent)
# ──────────────────────────────────────────────────────────────────────────────


def _run_vale(tmp_path, repo_root, content: str) -> subprocess.CompletedProcess:
    """Write `content` to a tmp skills/test_fixture.md, run vale against it,
    return the CompletedProcess.

    Vale's glob patterns (e.g. [skills/**]) are resolved relative to cwd, not
    the absolute file path. We therefore run vale with cwd=tmp_path and pass
    the fixture as a relative path so the [skills/**] section fires correctly.
    StylesPath is absolute so vale can locate styles/ from any cwd.
    """
    # Create a fake skills/ subtree under tmp_path so the [skills/**] glob fires
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir(exist_ok=True)
    fixture = skills_dir / "test_fixture.md"
    fixture.write_text(content, encoding="utf-8")

    # Point vale at the repo's styles dir via a minimal .vale.ini in tmp_path.
    # StylesPath must be absolute because cwd is tmp_path, not the repo root.
    styles_abs = str((repo_root / "styles").resolve())
    ini = tmp_path / ".vale.ini"
    ini.write_text(
        textwrap.dedent(f"""\
        StylesPath = {styles_abs}
        MinAlertLevel = error

        [skills/**]
        Squad.InstructionOnly = error
        """),
        encoding="utf-8",
    )

    # cwd=tmp_path so vale resolves skills/** relative to tmp_path; pass the
    # fixture as a relative path so the glob section matches.
    result = subprocess.run(
        ["vale", "--config", ".vale.ini", "skills/test_fixture.md"],
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
    )
    return result


@pytest.mark.skipif(not VALE_AVAILABLE, reason="vale not installed — skip behavioral tests")
def test_vale_flags_forbidden_phrase_in_prose(tmp_path, repo_root):
    """A forbidden phrase ('future-proofs') in running prose IS flagged by vale
    at error level. This confirms the style is loaded and the scope fires."""
    content = textwrap.dedent("""\
        # Test Fixture

        This approach future-proofs the configuration against later changes.
        """)
    result = _run_vale(tmp_path, repo_root, content)
    combined = result.stdout + result.stderr
    # vale exits non-zero when errors are found; the output mentions the phrase
    assert result.returncode != 0 or "future-proofs" in combined.lower(), (
        "vale must flag 'future-proofs' in running prose\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )
    # More precise: stdout should contain the violation token
    assert "future-proofs" in result.stdout.lower() or result.returncode != 0, (
        "Expected 'future-proofs' in vale output for a prose violation"
    )


@pytest.mark.skipif(not VALE_AVAILABLE, reason="vale not installed — skip behavioral tests")
def test_vale_does_not_flag_forbidden_phrase_in_fenced_code_block(tmp_path, repo_root):
    """The SAME forbidden phrase inside a fenced code block must NOT be flagged
    (scope:paragraph guarantee — code blocks are excluded from the scan)."""
    content = textwrap.dedent("""\
        # Test Fixture

        Use the following config snippet:

        ```yaml
        # future-proofs the setup at zero ongoing cost
        setting: value
        ```

        The code above is illustrative only.
        """)
    result = _run_vale(tmp_path, repo_root, content)
    # vale must exit 0 (no errors) — the phrase is inside a fenced block
    assert result.returncode == 0, (
        "vale must NOT flag 'future-proofs' inside a fenced code block\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )


@pytest.mark.skipif(not VALE_AVAILABLE, reason="vale not installed — skip behavioral tests")
def test_vale_does_not_flag_excluded_phrases_in_prose(tmp_path, repo_root):
    """Excluded phrases ('by construction', 'language-agnostic') in running
    prose must NOT be flagged — they have legit hits in the skills tree and
    banning them would cause false positives."""
    content = textwrap.dedent("""\
        # Test Fixture

        The resolver is language-agnostic and works by construction with any
        supported runtime. Use the command-resolution ladder to detect the
        project's test runner.
        """)
    result = _run_vale(tmp_path, repo_root, content)
    assert result.returncode == 0, (
        "vale must NOT flag 'by construction' or 'language-agnostic' in prose "
        "(they are deliberately excluded from the token set)\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )


@pytest.mark.skipif(not VALE_AVAILABLE, reason="vale not installed — skip behavioral tests")
def test_vale_flags_multiple_tokens_in_one_file(tmp_path, repo_root):
    """Multiple forbidden phrases in the same file produce multiple violations —
    confirms the existence rule applies per-token, not just the first match."""
    content = textwrap.dedent("""\
        # Test Fixture

        This mechanism future-proofs the agent interface.

        The approach operates at zero ongoing cost to the runtime environment.

        We deliberately chose this pattern over alternatives.
        """)
    result = _run_vale(tmp_path, repo_root, content)
    # Expect at least 2 distinct errors (returncode != 0 and multiple matches)
    assert result.returncode != 0, (
        "vale must report errors when multiple forbidden phrases appear in prose\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )
    # Count violation lines (lines containing 'error')
    error_lines = [l for l in result.stdout.splitlines() if "error" in l.lower()]
    assert len(error_lines) >= 2, (
        f"Expected >= 2 violation lines for 3 forbidden phrases; got {len(error_lines)}\n"
        f"stdout: {result.stdout!r}"
    )
