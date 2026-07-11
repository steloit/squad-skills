"""Contract guards for the cross-language command-resolution ladder.

The contract survived the skills-efficiency re-architecture but the authoring
location moved: the canonical ladder now lives in
``skills/squad/templates/_shared.md`` ("Command resolution" ground rule) and is
INJECTED into every pipeline agent prompt by ``pipeline.py::_render`` at the
``<shared_rules>`` placeholder. The ladder:

1. commands declared in the agent's loaded project context (AGENTS.md /
   CLAUDE.md / equivalents), else
2. the repo's task runner (make / just / Taskfile / npm scripts / scripts/), else
3. detect by language — and never assume a specific toolchain.

Load-bearing properties:

(a) _shared.md authors the ladder with all three rungs, in that order, and the
    "Never assume a specific toolchain" prohibition.
(b) the gate templates (worker-agent / tdd-tester / test-runner) instruct
    running the RESOLVED repo commands via the injected rule, and the rendered
    prompts actually carry the ladder.
(c) no single-stack gate command (pnpm test / vitest / npm run lint / …) is
    presented as THE test/lint/build command — in the raw templates AND in the
    fully rendered prompts.
(d) test-runner.md resolves lint AND build AND test (all three gates).
(e) no shipped skill carries a SQUAD_*_CMD command-override var.

Deleted from the old suite (structurally obsolete): the shared.md
"## Command Resolution" section assertions (AGENTS.md-canonical wording, the
scaffold + `ln -s` symlink note, `make test`/`just test` examples, numbered
rungs 1–4, the all-five context-file list, the closing "do not hardcode"
blockquote) — that long-form prose was intentionally compressed into the one
_shared.md ground rule; the surviving essence (ladder order, multi-runner
rung 2, detect-by-language fallback, never-assume-a-toolchain) is asserted
against the new rule and the rendered prompts.

Hermetic: reads committed skill files + renders templates locally; no network.
"""
import re

SHARED_RULES = "skills/squad/templates/_shared.md"
TEST_RUNNER = "skills/squad/templates/test-runner.md"
WORKER = "skills/squad/templates/worker-agent.md"
TDD = "skills/squad/templates/tdd-tester.md"
GATE_TEMPLATES = [TEST_RUNNER, WORKER, TDD]

# Single-stack commands that must NOT be presented as THE gate command.
HARDCODED_GATE_CMDS = [
    "pnpm test",
    "vitest",
    "npm run lint",
    "npm run test",
    "npm test",
    "yarn test",
]

# A SQUAD_<UPPER>_CMD command-override var — explicitly out of scope.
SQUAD_CMD_VAR = re.compile(r"SQUAD_[A-Z]+_CMD")


def _read(repo_root, rel):
    return (repo_root / rel).read_text(encoding="utf-8")


def _rule_line(text):
    """The Command-resolution ground-rule bullet in _shared.md."""
    return next((ln for ln in text.splitlines() if "Command resolution" in ln), "")


def _your_job(text):
    m = re.search(r"^##\s+Your Job\b.*?(?=^##\s|\Z)", text, re.MULTILINE | re.DOTALL)
    return m.group(0) if m else ""


# ---------------------------------------------------------------------------
# (a) _shared.md authors the ladder
# ---------------------------------------------------------------------------

def test_shared_rules_author_the_ladder(repo_root):
    rule = _rule_line(_read(repo_root, SHARED_RULES))
    assert rule, "_shared.md must author the Command resolution rule"
    assert "AGENTS.md" in rule and "CLAUDE.md" in rule, (
        "rung 1 must name the loaded project-context files"
    )
    assert "equivalents" in rule, (
        "rung 1 must treat other per-tool context files as equivalents "
        "(no single hardcoded context filename)"
    )
    runners = [r for r in ("make", "just", "Taskfile", "npm scripts") if r in rule]
    assert len(runners) >= 3, (
        f"rung 2 must name multiple task runners (found: {runners})"
    )
    assert re.search(r"detect by language", rule), (
        "rung 3 must be the detect-by-language fallback"
    )
    assert re.search(r"Never assume a specific toolchain", rule), (
        "the rule must carry the never-assume-a-toolchain prohibition"
    )


def test_ladder_order_context_then_runner_then_detect(repo_root):
    """The rungs must appear in first-match-wins order: project context, then
    task runner, then detect by language."""
    rule = _rule_line(_read(repo_root, SHARED_RULES))
    ctx = rule.find("project context")
    runner = rule.find("task runner")
    detect = rule.find("detect by language")
    assert -1 not in (ctx, runner, detect), "all three rungs must be present"
    assert ctx < runner < detect, (
        "the ladder must be ordered: loaded project context → task runner → "
        "detect by language"
    )


def test_shared_rules_cover_all_gate_commands(repo_root):
    """The ladder must cover build/lint/test/format — not just tests."""
    rule = _rule_line(_read(repo_root, SHARED_RULES))
    assert re.search(r"build/lint/test/format", rule), (
        "_shared.md Command resolution must cover build, lint, test AND format"
    )


# ---------------------------------------------------------------------------
# (b) gate templates use the resolved commands, and rendering injects the rule
# ---------------------------------------------------------------------------

def test_gate_templates_invoke_the_resolution_rule(repo_root):
    for rel in GATE_TEMPLATES:
        text = _read(repo_root, rel)
        assert "Command resolution" in text, (
            f"{rel} must point its command runs at the Command resolution rule"
        )


def test_worker_and_tdd_run_resolved_formatter_and_tests(repo_root):
    for rel in (WORKER, TDD):
        job = _your_job(_read(repo_root, rel))
        assert job, f"{rel} must have a '## Your Job' section"
        assert re.search(r"[Rr]esolve the repo.s real commands", job), (
            f"{rel} ## Your Job must resolve the repo's REAL commands via the ladder"
        )
        assert "formatter" in job and "test" in job, (
            f"{rel} ## Your Job must run the resolved formatter AND test command"
        )


def test_rendered_prompts_carry_the_ladder(pipeline_mod, monkeypatch):
    """Behavioral proof: rendering a gate template injects the ladder."""
    monkeypatch.setenv("SQUAD_MODEL_PROVIDER", "claude")
    for template in ("worker-agent.md", "tdd-tester.md", "test-runner.md"):
        rendered = pipeline_mod._render(template, {})
        assert "Command resolution" in rendered
        assert "detect by language" in rendered, (
            f"{template}: the rendered prompt must carry the full ladder"
        )
        assert "<shared_rules>" not in rendered


# ---------------------------------------------------------------------------
# (c) no single-stack gate command — raw templates AND rendered prompts
# ---------------------------------------------------------------------------

def test_templates_have_no_hardcoded_gate_command(repo_root):
    for rel in GATE_TEMPLATES:
        text = _read(repo_root, rel)
        hits = [cmd for cmd in HARDCODED_GATE_CMDS if cmd in text]
        assert not hits, (
            f"{rel} hardcodes a single-stack gate command {hits} — resolve via "
            "the ladder instead"
        )


def test_rendered_prompts_have_no_hardcoded_gate_command(pipeline_mod, monkeypatch):
    monkeypatch.setenv("SQUAD_MODEL_PROVIDER", "claude")
    for template in ("worker-agent.md", "tdd-tester.md", "test-runner.md"):
        rendered = pipeline_mod._render(template, {})
        hits = [cmd for cmd in HARDCODED_GATE_CMDS if cmd in rendered]
        assert not hits, (
            f"{template}: rendered prompt carries a single-stack gate command {hits}"
        )


def test_gate_command_blocklist_detects_a_planted_command():
    """Self-test: the blocklist is non-vacuous."""
    assert any(cmd in "run pnpm test now" for cmd in HARDCODED_GATE_CMDS)


# ---------------------------------------------------------------------------
# (d) test-runner resolves lint AND build AND test
# ---------------------------------------------------------------------------

def test_test_runner_resolves_lint_build_and_test(repo_root):
    job = _your_job(_read(repo_root, TEST_RUNNER))
    assert job, "test-runner.md must have a '## Your Job' section"
    assert re.search(r"real lint/build/test commands", job), (
        "test-runner.md ## Your Job must resolve the repo's real lint, build "
        "AND test commands (all three gates, not just tests)"
    )


# ---------------------------------------------------------------------------
# (e) no SQUAD_*_CMD command-override var in shipped skills
# ---------------------------------------------------------------------------

def test_no_squad_cmd_vars_in_shipped_skills(repo_root):
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
    assert not hits, "SQUAD_*_CMD command-override vars found:\n" + "\n".join(hits)


def test_squad_cmd_regex_matches_a_real_var_but_not_the_doc_form():
    assert SQUAD_CMD_VAR.search("export SQUAD_TEST_CMD=...")
    assert not SQUAD_CMD_VAR.search("there is no `SQUAD_*_CMD` variable")
