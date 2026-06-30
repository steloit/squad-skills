"""Gap-coverage tests for the cross-language command-resolution contract (#SQD-970).

These tests EXTEND ``test_command_resolution_contract.py`` (16 assertions by Builder) — added by
Shield (sonnet) in the same TDD pass.  Do NOT duplicate the Builder's 16 assertions; cover the
gaps identified during review:

(f) squad-run/SKILL.md Impl-Step Format Normalization demotion blockquote explicitly labels the
    step as a 'best-effort safety net — NOT the primary cross-language mechanism' and points to
    shared.md → Command Resolution as the authoritative agent-layer path.

(g) shared.md Command Resolution closes with a 'Do not hardcode a single stack' blockquote — the
    prohibition that makes the 'no single-stack gate command' constraint self-documenting.

(h) test-runner.md ## Your Job names lint AND build AND test (not just test) in the
    command-resolution instruction — all three gate commands are resolved, not just tests.

(i) test-runner.md ## Your Job states that detect-by-language is used 'only if nothing is
    declared' — making explicit that detection is the last-resort fallback, not the primary path.

(j) shared.md Command Resolution rung 2 (repo task runner) names npm scripts / package.json as a
    valid option alongside make / just / Taskfile / mise — so JS repos are covered at rung 2.

(k) shared.md Command Resolution uses a numbered ladder (rungs 1, 2, 3, 4 in order) so the
    'first rung that yields a command wins' ordering is unambiguous.

(l) shared.md Command Resolution lists ALL 5 canonical context-file equivalents
    (AGENTS.md / CLAUDE.md / GEMINI.md / .cursor/rules / .github/copilot-instructions.md) in
    the same section — not just the ≥3 minimum.

(m) tdd-tester.md ## Your Job instructs running the formatter BEFORE the resolved test command
    (format → test order) — formatter is the closer safety net, run first.

(n) Non-vacuous self-test: 'vitest' is in the HARDCODED_GATE_CMDS blocklist used by the Builder's
    test (c) — confirming the blocklist catches a real JS-only command.

Hermetic: reads committed skill files only, no network. Stdlib (``re``, ``pathlib``) only.
"""
import re
import pathlib

# ---------------------------------------------------------------------------
# paths
# ---------------------------------------------------------------------------

SHARED = "skills/squad/shared.md"
TEST_RUNNER = "skills/squad/templates/test-runner.md"
WORKER = "skills/squad/templates/worker-agent.md"
TDD = "skills/squad/templates/tdd-tester.md"
SKILL_MD = "skills/squad-run/SKILL.md"

ALL_CONTEXT_FILES = [
    "AGENTS.md",
    "CLAUDE.md",
    "GEMINI.md",
    ".cursor/rules",
    ".github/copilot-instructions.md",
]

# The same blocklist as in test_command_resolution_contract.py — reproduced here so
# the self-test (n) can verify vitest is present without a cross-module import.
HARDCODED_GATE_CMDS = [
    "pnpm test",
    "vitest",
    "npm run lint",
    "npm run test",
    "npm test",
    "yarn test",
]


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _read(repo_root, rel: str) -> str:
    return (repo_root / rel).read_text(encoding="utf-8")


def _command_resolution_section(text: str) -> str:
    """Body of the ``## Command Resolution`` section (up to the next ``## `` or EOF)."""
    m = re.search(r"^##\s+Command Resolution\b.*?(?=^##\s|\Z)", text, re.MULTILINE | re.DOTALL)
    return m.group(0) if m else ""


def _your_job(text: str) -> str:
    """Body of the template's ``## Your Job`` section (up to the next ``## `` or EOF)."""
    m = re.search(r"^##\s+Your Job\b.*?(?=^##\s|\Z)", text, re.MULTILINE | re.DOTALL)
    return m.group(0) if m else ""


# ---------------------------------------------------------------------------
# (f) 717-demotion blockquote in squad-run/SKILL.md
# ---------------------------------------------------------------------------

def test_skill_md_format_step_not_primary_cross_language(repo_root):
    """The demotion blockquote added to Impl-Step Format Normalization must explicitly say the
    step is NOT the primary cross-language mechanism — so it is not mistaken for the gate."""
    text = _read(repo_root, SKILL_MD)
    assert re.search(r"NOT the primary cross.language mechanism", text), (
        "squad-run/SKILL.md Impl-Step Format Normalization must contain 'NOT the primary "
        "cross-language mechanism' (the 717-demotion blockquote)"
    )


def test_skill_md_format_step_labelled_best_effort_safety_net(repo_root):
    """The demotion blockquote must describe the entire format step as a 'best-effort safety
    net' (not merely say 'best-effort' in the skip path) so the framing is unambiguous."""
    text = _read(repo_root, SKILL_MD)
    assert re.search(r"best-effort safety net", text, re.IGNORECASE), (
        "squad-run/SKILL.md must contain the phrase 'best-effort safety net' — the demotion "
        "blockquote labels the WHOLE step as a net, not just the no-formatter skip path"
    )


def test_skill_md_format_normalization_references_shared_command_resolution(repo_root):
    """The demotion blockquote must point to shared.md → Command Resolution as the authoritative
    agent-layer path — so the reader knows WHERE the real resolution is documented."""
    text = _read(repo_root, SKILL_MD)
    assert re.search(r"shared\.md.*Command Resolution|Command Resolution.*shared\.md", text), (
        "squad-run/SKILL.md Impl-Step Format Normalization must reference "
        "'shared.md → Command Resolution' as the authoritative path"
    )


# ---------------------------------------------------------------------------
# (g) 'do not hardcode a single stack' blockquote in shared.md
# ---------------------------------------------------------------------------

def test_shared_command_resolution_has_do_not_hardcode_warning(repo_root):
    """shared.md Command Resolution must close with a 'do not hardcode a single stack'
    blockquote — making the prohibition self-documenting alongside the ladder."""
    section = _command_resolution_section(_read(repo_root, SHARED))
    assert section, "shared.md must have a '## Command Resolution' section"
    assert re.search(r"[Dd]o not hardcode a single stack", section), (
        "shared.md Command Resolution must include a 'Do not hardcode a single stack' warning "
        "(the closing blockquote that pairs with the no-single-stack-gate-command constraint)"
    )


# ---------------------------------------------------------------------------
# (h) test-runner.md ## Your Job: resolves lint AND build AND test
# ---------------------------------------------------------------------------

def test_test_runner_job_resolves_lint_build_and_test(repo_root):
    """test-runner.md ## Your Job must name lint, build, AND test in the command-resolution
    instruction — Ranger runs all three gate commands, not just tests."""
    your_job = _your_job(_read(repo_root, TEST_RUNNER))
    assert your_job, "test-runner.md must have a '## Your Job' section"
    assert re.search(r"\blint\b", your_job, re.IGNORECASE), (
        "test-runner.md ## Your Job must mention 'lint' in the command-resolution instruction"
    )
    assert re.search(r"\bbuild\b", your_job, re.IGNORECASE), (
        "test-runner.md ## Your Job must mention 'build' in the command-resolution instruction"
    )
    assert re.search(r"\btest\b", your_job, re.IGNORECASE), (
        "test-runner.md ## Your Job must mention 'test' in the command-resolution instruction"
    )


# ---------------------------------------------------------------------------
# (i) test-runner.md ## Your Job: detect-by-language is conditional
# ---------------------------------------------------------------------------

def test_test_runner_job_detect_is_conditional_fallback(repo_root):
    """test-runner.md ## Your Job must state that detect-by-language is used ONLY when nothing
    is declared — making clear it is the last-resort fallback, not the primary path."""
    your_job = _your_job(_read(repo_root, TEST_RUNNER))
    assert your_job, "test-runner.md must have a '## Your Job' section"
    assert re.search(
        r"detect by language only if nothing is declared|"
        r"detect[^\n]*(only if|only when)[^\n]*nothing.*declared|"
        r"nothing is declared",
        your_job, re.IGNORECASE
    ), (
        "test-runner.md ## Your Job must state that detect-by-language is used 'only if nothing "
        "is declared' — so agents know detection is last-resort, not primary"
    )


# ---------------------------------------------------------------------------
# (j) shared.md rung 2 includes npm scripts / package.json
# ---------------------------------------------------------------------------

def test_shared_task_runner_rung_includes_npm_scripts(repo_root):
    """Rung 2 (repo task runner) in shared.md must name npm scripts / package.json as a valid
    option — not only make/just/Taskfile/mise — so JS repos are covered at rung 2."""
    section = _command_resolution_section(_read(repo_root, SHARED))
    assert re.search(r"npm scripts?|package\.json", section, re.IGNORECASE), (
        "shared.md Command Resolution rung 2 must include 'npm scripts' / 'package.json' "
        "alongside make/just/Taskfile/mise — JS repos use package.json task runners"
    )


# ---------------------------------------------------------------------------
# (k) shared.md ladder is explicitly numbered 1–4
# ---------------------------------------------------------------------------

def test_shared_command_resolution_ladder_is_numbered(repo_root):
    """The Command Resolution ladder must use numbered rungs (1. / 2. / 3.) so the
    'first rung that yields a command wins' ordering is unambiguous to readers."""
    section = _command_resolution_section(_read(repo_root, SHARED))
    assert section, "shared.md must have a '## Command Resolution' section"
    for rung in ("1.", "2.", "3."):
        assert rung in section, (
            f"shared.md Command Resolution must contain numbered rung '{rung}' — "
            "the ordering (first match wins) must be explicit and unambiguous"
        )


# ---------------------------------------------------------------------------
# (l) shared.md names ALL 5 context-file equivalents (not just ≥3)
# ---------------------------------------------------------------------------

def test_shared_names_all_five_context_file_equivalents(repo_root):
    """shared.md Command Resolution must list ALL 5 canonical context-file equivalents
    (AGENTS.md / CLAUDE.md / GEMINI.md / .cursor/rules / .github/copilot-instructions.md)
    in the same section — the ≥3 minimum is not enough; all equivalents must be named."""
    section = _command_resolution_section(_read(repo_root, SHARED))
    missing = [f for f in ALL_CONTEXT_FILES if f not in section]
    assert not missing, (
        f"shared.md Command Resolution is missing these context-file equivalents: {missing}. "
        "All 5 must be listed so the ladder is complete."
    )


# ---------------------------------------------------------------------------
# (m) tdd-tester.md ## Your Job: formatter runs BEFORE test command
# ---------------------------------------------------------------------------

def test_tdd_tester_job_formats_before_testing(repo_root):
    """tdd-tester.md ## Your Job must instruct running the formatter BEFORE the resolved test
    command — format is the closer safety net and must run first so test results are clean."""
    your_job = _your_job(_read(repo_root, TDD))
    assert your_job, "tdd-tester.md must have a '## Your Job' section"

    fmt_m = re.search(
        r"formatter|format script|biome|ruff|black|gofmt|rustfmt",
        your_job, re.IGNORECASE
    )
    test_m = re.search(
        r"resolved\b.{0,20}test.{0,20}command",
        your_job, re.IGNORECASE | re.DOTALL
    )
    assert fmt_m, "tdd-tester.md ## Your Job must mention the formatter"
    assert test_m, "tdd-tester.md ## Your Job must mention the resolved test command"
    assert fmt_m.start() < test_m.start(), (
        "tdd-tester.md ## Your Job must run the formatter BEFORE the resolved test command "
        "(format → test order; formatter is the safety net, run first)"
    )


# ---------------------------------------------------------------------------
# (n) self-test: 'vitest' is in the gate-command blocklist
# ---------------------------------------------------------------------------

def test_gate_blocklist_self_test_vitest_is_present():
    """Non-vacuous self-test: 'vitest' (JS-only gate command) must be in the blocklist so the
    Builder's test (c) would catch it if it appeared in a template as THE test command."""
    assert "vitest" in HARDCODED_GATE_CMDS, (
        "'vitest' must be present in HARDCODED_GATE_CMDS — it is a single-stack (JS-only) "
        "command that must never appear as THE gate command in the templates"
    )
