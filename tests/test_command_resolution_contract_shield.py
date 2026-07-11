"""Gap-coverage tests for the cross-language command-resolution contract.

Companion to ``test_command_resolution_contract.py`` — covers gaps rather than
duplicating it. Post-re-architecture the ladder is the _shared.md "Command
resolution" ground rule (injected into every prompt), and the deterministic
format step is ``pipeline.py normalize``.

Gaps covered here:

(f) demotion — the deterministic normalize step stays labelled best-effort
    (squad-run/SKILL.md + the engine's own contract prose), so it is never
    mistaken for the primary cross-language gate mechanism (that is the
    agent-layer ladder).
(g) detect-by-language is the LAST-RESORT rung — it is else-chained after the
    declared-command rungs in the rule text.
(j) rung 2 covers JS repos too: npm scripts are named alongside make/just/
    Taskfile.
(m) format → test order: worker-agent and tdd-tester both run the formatter
    BEFORE the resolved test command.
(n) non-vacuous blocklist self-test: 'vitest' stays in the blocklist.
(new) the engine's own FORMATTERS ladder spans multiple language ecosystems —
    the code-level mirror of the never-assume-a-toolchain rule.

Deleted (structurally obsolete): the SKILL.md demotion-blockquote wording
tests ('NOT the primary cross-language mechanism', the shared.md pointer), the
shared.md numbered-rung / all-five-context-files / do-not-hardcode-blockquote
tests — that prose was intentionally compressed; the surviving essence is
asserted against _shared.md and the engine.

Hermetic: reads committed skill files; no network.
"""
import re

SHARED_RULES = "skills/squad/templates/_shared.md"
SKILL_MD = "skills/squad-run/SKILL.md"
WORKER = "skills/squad/templates/worker-agent.md"
TDD = "skills/squad/templates/tdd-tester.md"

HARDCODED_GATE_CMDS = [
    "pnpm test",
    "vitest",
    "npm run lint",
    "npm run test",
    "npm test",
    "yarn test",
]


def _read(repo_root, rel):
    return (repo_root / rel).read_text(encoding="utf-8")


def _rule_line(text):
    return next((ln for ln in text.splitlines() if "Command resolution" in ln), "")


def _your_job(text):
    m = re.search(r"^##\s+Your Job\b.*?(?=^##\s|\Z)", text, re.MULTILINE | re.DOTALL)
    return m.group(0) if m else ""


# ---------------------------------------------------------------------------
# (f) the deterministic format step stays a demoted, best-effort net
# ---------------------------------------------------------------------------

def test_skill_labels_normalize_best_effort_not_the_gate(repo_root):
    text = _read(repo_root, SKILL_MD)
    m = re.search(r"pipe normalize[^\n]*", text)
    assert m, "SKILL.md must invoke pipe normalize in the impl step"
    assert "best-effort" in m.group(0), (
        "the normalize invocation must be labelled best-effort — it is a "
        "safety net, not the primary cross-language mechanism"
    )


def test_engine_documents_normalize_as_best_effort_never_blocking(pipeline_mod):
    doc = pipeline_mod.__doc__
    assert re.search(r"[Bb]est-effort", doc) and "never blocks" in doc, (
        "pipeline.py's contract prose must state normalize is best-effort and "
        "never blocks the pipeline"
    )


# ---------------------------------------------------------------------------
# (g) detect-by-language is the else-chained last resort
# ---------------------------------------------------------------------------

def test_detect_by_language_is_last_resort_fallback(repo_root):
    rule = _rule_line(_read(repo_root, SHARED_RULES))
    m = re.search(r"else detect by language", rule)
    assert m, (
        "_shared.md must else-chain detect-by-language AFTER the declared-"
        "command rungs — detection is the last resort, never the primary path"
    )
    assert rule.find("first") < rule.find("else detect by language"), (
        "the declared-context rung must be marked first"
    )


# ---------------------------------------------------------------------------
# (j) rung 2 includes npm scripts (JS repos covered at the task-runner rung)
# ---------------------------------------------------------------------------

def test_task_runner_rung_includes_npm_scripts(repo_root):
    rule = _rule_line(_read(repo_root, SHARED_RULES))
    assert "npm scripts" in rule, (
        "_shared.md rung 2 must include npm scripts alongside make/just/Taskfile"
    )


# ---------------------------------------------------------------------------
# (m) formatter runs BEFORE the resolved test command
# ---------------------------------------------------------------------------

def test_tdd_tester_formats_before_testing(repo_root):
    job = _your_job(_read(repo_root, TDD))
    assert job, "tdd-tester.md must have a '## Your Job' section"
    fmt_at = job.lower().find("formatter")
    test_at = job.lower().find("test command")
    assert fmt_at != -1 and test_at != -1, (
        "tdd-tester.md ## Your Job must name the formatter and the test command"
    )
    assert fmt_at < test_at, (
        "tdd-tester.md must run the formatter BEFORE the resolved test command"
    )


def test_worker_agent_formats_before_testing(repo_root):
    job = _your_job(_read(repo_root, WORKER))
    assert job, "worker-agent.md must have a '## Your Job' section"
    fmt_at = job.lower().find("formatter")
    test_at = job.lower().find("test command")
    assert fmt_at != -1 and test_at != -1
    assert fmt_at < test_at, (
        "worker-agent.md must run the formatter BEFORE the resolved test command"
    )


# ---------------------------------------------------------------------------
# (n) non-vacuous blocklist self-test
# ---------------------------------------------------------------------------

def test_gate_blocklist_self_test_vitest_is_present():
    assert "vitest" in HARDCODED_GATE_CMDS, (
        "'vitest' must stay in the single-stack blocklist"
    )


# ---------------------------------------------------------------------------
# (new) the engine's FORMATTERS ladder mirrors the cross-language rule in code
# ---------------------------------------------------------------------------

def test_engine_formatter_ladder_spans_multiple_ecosystems(pipeline_mod):
    """The never-assume-a-toolchain rule has a code-level mirror: the engine's
    formatter ladder must span JS, Python, Go and Rust ecosystems."""
    import inspect
    src = inspect.getsource(pipeline_mod)
    ladder = src[src.index("FORMATTERS = ["):src.index("def _have")]
    ecosystems = {
        "js": ("biome", "prettier", "package.json"),
        "python": ("ruff", "black"),
        "go": ("gofmt",),
        "rust": ("rustfmt",),
    }
    missing = [name for name, needles in ecosystems.items()
               if not any(n in ladder for n in needles)]
    assert not missing, (
        f"the FORMATTERS ladder must cover these ecosystems too: {missing}"
    )
