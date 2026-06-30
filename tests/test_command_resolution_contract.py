"""Structural guards for the cross-language command-resolution contract (#SQD-970).

The squad-run pipeline must run a repo's REAL build/lint/test/format commands across ANY
language, not a JS/Py/Go/Rust-hardcoded set.  The mechanism is a tool-agnostic
**command-resolution ladder**, authored once in ``skills/squad/shared.md`` →
**Command Resolution** and referenced by every agent-driven gate step:

1. your loaded project context — AGENTS.md / CLAUDE.md / GEMINI.md / .cursor/rules /
   .github/copilot-instructions.md (AGENTS.md canonical, the rest equivalents),
2. the repo task runner (make / just / Taskfile / mise / npm scripts),
3. auto-detect by language (the fallback; MAY offer to scaffold AGENTS.md).

Load-bearing properties guarded here:

(a) shared.md documents the ladder (≥3 context files as equivalents, AGENTS.md canonical,
    task runner, "detect by language" fallback, the AGENTS.md scaffold + symlink note).
(b) each gate template (test-runner / worker-agent / tdd-tester) references the ladder and
    names ≥3 context files as equivalents (no single hardcoded context filename).
(c) NO single-stack gate command (e.g. ``pnpm test`` / ``vitest`` / ``npm run lint``) is
    presented as THE test/lint/build command in the templates — scoped to GATE commands so
    the existing ``biome`` *formatter example* (required by the format-normalization
    contract) is still allowed.
(d)  worker-agent.md ``## Your Job`` runs the resolved TEST command (the #969 L1 fold).
(d') tdd-tester.md  ``## Your Job`` runs the resolved TEST command too (Critic suggestion).
(e) no shipped skill carries a ``SQUAD_*_CMD`` command-override var.

Hermetic: reads committed skill files only, no network. Stdlib (`re`) only.
"""
import re

# ---------------------------------------------------------------------------
# paths + constants
# ---------------------------------------------------------------------------

SHARED = "skills/squad/shared.md"
TEST_RUNNER = "skills/squad/templates/test-runner.md"
WORKER = "skills/squad/templates/worker-agent.md"
TDD = "skills/squad/templates/tdd-tester.md"
GATE_TEMPLATES = [TEST_RUNNER, WORKER, TDD]

# The per-tool project-context files the ladder treats as equivalents (AGENTS.md canonical).
CONTEXT_FILES = [
    "AGENTS.md",
    "CLAUDE.md",
    "GEMINI.md",
    ".cursor/rules",
    ".github/copilot-instructions.md",
]

# Single-stack commands that must NOT be presented as THE gate command (test/lint/build).
# Scoped to gate commands ONLY: the `biome` formatter example (and the repo `format` script)
# are intentionally NOT here — they are formatter examples, allowed by the format contract.
HARDCODED_GATE_CMDS = [
    "pnpm test",
    "vitest",
    "npm run lint",
    "npm run test",
    "npm test",
    "yarn test",
]

# A SQUAD_<UPPER>_CMD command-override var — explicitly OUT of scope (the `*` doc form in
# shared.md does not match this).
SQUAD_CMD_VAR = re.compile(r"SQUAD_[A-Z]+_CMD")


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
    """Body of the template's ``## Your Job`` section."""
    m = re.search(r"^##\s+Your Job\b.*?(?=^##\s|\Z)", text, re.MULTILINE | re.DOTALL)
    return m.group(0) if m else ""


def _count_context_files(text: str) -> int:
    return sum(1 for f in CONTEXT_FILES if f in text)


# ---------------------------------------------------------------------------
# (a) shared.md documents the ladder
# ---------------------------------------------------------------------------

def test_shared_has_command_resolution_section(repo_root):
    section = _command_resolution_section(_read(repo_root, SHARED))
    assert section, "shared.md must contain a '## Command Resolution' section"


def test_shared_names_three_context_files_as_equivalents(repo_root):
    """The ladder must name ≥3 per-tool context files as equivalents (not one hardcoded file)."""
    section = _command_resolution_section(_read(repo_root, SHARED))
    found = [f for f in CONTEXT_FILES if f in section]
    assert len(found) >= 3, (
        f"shared.md Command Resolution must name ≥3 context files as equivalents (found: {found})"
    )


def test_shared_names_agents_md_canonical(repo_root):
    """AGENTS.md must be named the CANONICAL declaration (the others are equivalents)."""
    section = _command_resolution_section(_read(repo_root, SHARED))
    assert "AGENTS.md" in section, "shared.md Command Resolution must name AGENTS.md"
    assert re.search(r"AGENTS\.md[^\n]*canonical|canonical[^\n]*AGENTS\.md", section, re.IGNORECASE), (
        "shared.md must name AGENTS.md as the canonical/portable declaration"
    )


def test_shared_names_task_runner_rung(repo_root):
    """Rung 2 — the repo task runner — must be documented (make / just / Taskfile / mise)."""
    section = _command_resolution_section(_read(repo_root, SHARED))
    runners = [r for r in ("make", "just", "Taskfile", "mise") if r in section]
    assert len(runners) >= 2, (
        f"shared.md Command Resolution must name the repo task runner rung (found: {runners})"
    )


def test_shared_documents_detect_by_language_fallback(repo_root):
    """Rung 3 — auto-detect by language — must be documented as the fallback."""
    section = _command_resolution_section(_read(repo_root, SHARED))
    assert re.search(r"detect[^\n]*by language|by language[^\n]*detect", section, re.IGNORECASE), (
        "shared.md Command Resolution must document the 'detect by language' fallback"
    )


def test_shared_documents_two_non_js_stacks(repo_root):
    """AC: at least two NON-JS declared-command examples (e.g. a Go ``make test``, a Python
    ``just test``) appear, proving the ladder is not JS-only."""
    section = _command_resolution_section(_read(repo_root, SHARED))
    assert "make test" in section and "just test" in section, (
        "shared.md must show ≥2 non-JS declared-command examples (e.g. 'make test', 'just test')"
    )


def test_shared_documents_agents_scaffold_and_symlink(repo_root):
    """Rung 3 must document the AGENTS.md 'Commands' scaffold offer + the
    ``ln -s AGENTS.md CLAUDE.md`` symlink note."""
    text = _read(repo_root, SHARED)
    assert "ln -s AGENTS.md CLAUDE.md" in text, (
        "shared.md must document the 'ln -s AGENTS.md CLAUDE.md' symlink note"
    )
    section = _command_resolution_section(text)
    assert re.search(r"scaffold[^\n]*AGENTS\.md|AGENTS\.md[^\n]*scaffold|scaffold an `AGENTS\.md`", section, re.IGNORECASE), (
        "shared.md Command Resolution must document the AGENTS.md scaffold offer"
    )


# ---------------------------------------------------------------------------
# (b) each gate template references the ladder + names ≥3 context files
# ---------------------------------------------------------------------------

def test_templates_reference_command_resolution_ladder(repo_root):
    for rel in GATE_TEMPLATES:
        text = _read(repo_root, rel)
        assert "Command Resolution" in text, (
            f"{rel} must reference 'Command Resolution' (the shared ladder)"
        )
        assert "shared.md" in text, (
            f"{rel} must point to shared.md for the command-resolution ladder"
        )


def test_templates_name_three_context_files(repo_root):
    """Each template names ≥3 context files as equivalents — so no single context filename
    is hardcoded as THE source."""
    for rel in GATE_TEMPLATES:
        text = _read(repo_root, rel)
        found = [f for f in CONTEXT_FILES if f in text]
        assert len(found) >= 3, (
            f"{rel} must name ≥3 context files as equivalents (found: {found})"
        )


# ---------------------------------------------------------------------------
# (c) no single-stack GATE command in the templates (biome formatter example allowed)
# ---------------------------------------------------------------------------

def test_templates_have_no_hardcoded_gate_command(repo_root):
    """No template may present a single-stack command (pnpm test / vitest / npm run lint …)
    as THE test/lint/build gate. Scoped to GATE commands — the `biome`/`format` formatter
    examples (required by test_format_normalization_contract) are intentionally NOT checked."""
    for rel in GATE_TEMPLATES:
        text = _read(repo_root, rel)
        hits = [cmd for cmd in HARDCODED_GATE_CMDS if cmd in text]
        assert not hits, (
            f"{rel} hardcodes a single-stack gate command {hits} — resolve via the ladder instead"
        )


def test_gate_command_blocklist_detects_a_planted_command(repo_root):
    """Self-test: the blocklist is non-vacuous (it would catch a planted 'pnpm test')."""
    assert any(cmd in "run pnpm test now" for cmd in HARDCODED_GATE_CMDS)


# ---------------------------------------------------------------------------
# (d) / (d') Builder AND Shield run the resolved TEST command
# ---------------------------------------------------------------------------

def test_worker_agent_runs_resolved_test_command(repo_root):
    """worker-agent.md ## Your Job runs the resolved TEST command (the #969 L1 backstop)."""
    your_job = _your_job(_read(repo_root, WORKER))
    assert your_job, "worker-agent.md must have a '## Your Job' section"
    assert re.search(r"resolved\b.{0,16}test.{0,16}command", your_job, re.IGNORECASE | re.DOTALL), (
        "worker-agent.md ## Your Job must run the resolved TEST command before recording results"
    )


def test_tdd_tester_runs_resolved_test_command(repo_root):
    """tdd-tester.md ## Your Job runs the resolved TEST command too (not just the formatter)."""
    your_job = _your_job(_read(repo_root, TDD))
    assert your_job, "tdd-tester.md must have a '## Your Job' section"
    assert re.search(r"resolved\b.{0,16}test.{0,16}command", your_job, re.IGNORECASE | re.DOTALL), (
        "tdd-tester.md ## Your Job must run the resolved TEST command before recording results"
    )


# ---------------------------------------------------------------------------
# (e) no SQUAD_*_CMD command-override var in shipped skills
# ---------------------------------------------------------------------------

def test_no_squad_cmd_vars_in_shipped_skills(repo_root):
    """`.squadrc` SQUAD_*_CMD command-override vars are out of scope — no shipped skill may
    contain a SQUAD_<UPPER>_CMD var (the doc form `SQUAD_*_CMD` with an asterisk does not match)."""
    hits = []
    for path in sorted((repo_root / "skills").rglob("*")):
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, ValueError):
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if SQUAD_CMD_VAR.search(line):
                hits.append(f"{path}:{i}: {line.strip()}")
    assert not hits, "SQUAD_*_CMD command-override vars found in shipped skills/**:\n" + "\n".join(hits)


def test_squad_cmd_regex_matches_a_real_var_but_not_the_doc_form():
    """Self-test: the regex catches a real SQUAD_TEST_CMD var but NOT the `SQUAD_*_CMD` doc form."""
    assert SQUAD_CMD_VAR.search("export SQUAD_TEST_CMD=...")
    assert not SQUAD_CMD_VAR.search("there is no `SQUAD_*_CMD` variable")
