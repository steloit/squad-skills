"""Structural guards for the impl-step format-normalization contract.

The squad-run orchestrator gains a deterministic **Format Normalization** step that runs
AFTER Builder+Shield complete and BEFORE the impl→impl_review status move.  The step
normalizes auto-fixable formatting in the changed-file set so format-only violations
never reach the Inspector or Ranger gate.

Three properties form the load-bearing contract:

1. **Seam ordering** — the format-normalize section precedes the
   ``{"status": "impl_review"}`` commit-move PATCH in squad-run/SKILL.md.

2. **Format-only, lint-transparent** — the step runs the formatter's write/format mode
   only; it never runs lint --fix/rule-disable; genuine lint/type errors still reach
   the Ranger gate unchanged.

3. **Tool-agnostic + skip-clean** — formatter resolution covers multiple tools (not
   hard-coded to one); when no formatter is resolvable the step skips with a logged note
   and never hard-fails the pipeline.

Backstop assertions:

4. **Shield self-format** — tdd-tester.md ``## Your Job`` instructs Shield to run the
   project formatter on every file it modified and verify clean before recording results.

5. **Builder self-format** — worker-agent.md ``## Your Job`` carries the same instruction
   for Builder (the L1 backstop path that has no impl_review seam).

Hermetic: reads committed skill files only, no network.
"""
import re


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _read(repo_root, rel: str) -> str:
    return (repo_root / rel).read_text()


def _section(text: str, heading: str) -> str:
    """Return the body of the first ``#### <heading>`` section (up to next ``####`` or EOF)."""
    m = re.search(
        r"^####\s+" + re.escape(heading) + r"\b.*?(?=^####\s|\Z)",
        text,
        re.MULTILINE | re.DOTALL,
    )
    return m.group(0) if m else ""


# ---------------------------------------------------------------------------
# 1. Seam ordering: format-normalization section BEFORE impl_review PATCH
# ---------------------------------------------------------------------------


def test_format_normalization_section_present(repo_root):
    """squad-run/SKILL.md must contain the Impl-Step Format Normalization sub-section."""
    text = _read(repo_root, "skills/squad-run/SKILL.md")
    assert re.search(r"Impl-Step Format Normalization", text), (
        "squad-run/SKILL.md must contain an 'Impl-Step Format Normalization' sub-section"
    )


def test_format_normalization_precedes_impl_review_commit(repo_root):
    """The format-normalization section must appear BEFORE the impl→impl_review commit PATCH
    (``\"status\": \"impl_review\"``).  The ordering is the load-bearing seam: normalization
    happens AFTER Builder+Shield return, BEFORE the status move."""
    text = _read(repo_root, "skills/squad-run/SKILL.md")

    norm_m = re.search(r"Impl-Step Format Normalization", text)
    assert norm_m, "squad-run/SKILL.md must contain the 'Impl-Step Format Normalization' section"

    # The deterministic commit-move PATCH that transitions to impl_review.
    # We look specifically for the JSON that sets status to impl_review (the commit move),
    # not incidental references to the column name.
    commit_m = re.search(r'"status":\s*"impl_review"', text)
    assert commit_m, (
        "squad-run/SKILL.md must contain the impl→impl_review commit-move PATCH "
        '(``"status": "impl_review"``)'
    )

    assert norm_m.start() < commit_m.start(), (
        "The Format Normalization section must appear BEFORE the "
        '``"status": "impl_review"`` commit-move PATCH (seam ordering is load-bearing)'
    )


def test_format_normalization_section_references_pre_impl_review(repo_root):
    """The section header or its opening prose must label itself as 'pre-impl_review' (or
    equivalent) so the placement intent survives future edits."""
    text = _read(repo_root, "skills/squad-run/SKILL.md")
    norm_section = _section(text, "Impl-Step Format Normalization (deterministic, pre-impl_review)")
    if not norm_section:
        # Fallback: search the full text for the pre-impl_review label near the section header.
        norm_section = text
    assert re.search(r"pre-impl_review|before.*impl_review|BEFORE.*impl_review", norm_section, re.IGNORECASE), (
        "The format-normalization section must state it runs before (pre) the impl_review move"
    )


# ---------------------------------------------------------------------------
# 2. Format-only, lint-transparent
# ---------------------------------------------------------------------------


def test_format_normalization_is_format_only_not_lint(repo_root):
    """The normalization section must explicitly state it runs format/write mode ONLY and
    does NOT run lint, pass lint --fix, or auto-disable lint rules."""
    text = _read(repo_root, "skills/squad-run/SKILL.md")
    # Must say it does not run lint in some form.
    assert re.search(
        r"does not run lint|not.*run lint|format.only|format/write mode only",
        text,
        re.IGNORECASE,
    ), (
        "squad-run/SKILL.md must state the normalization step does NOT run lint "
        "(format/write mode only)"
    )


def test_format_normalization_no_lint_fix_or_rule_disable(repo_root):
    """The section must explicitly state it never passes a lint --fix/--write that
    auto-disables rules, and never inserts eslint-disable or biome-ignore."""
    text = _read(repo_root, "skills/squad-run/SKILL.md")
    assert re.search(r"eslint-disable|biome-ignore", text), (
        "squad-run/SKILL.md must mention eslint-disable / biome-ignore to state they are never inserted"
    )
    # The section must use 'biome format --write' (format-only) NOT 'biome check --write'
    # (which would also apply lint fixes).
    assert "biome format --write" in text, (
        "squad-run/SKILL.md must use 'biome format --write' (format-only), "
        "not 'biome check --write' (which applies lint fixes)"
    )
    assert re.search(r"NOT.*biome check --write|biome check --write.*which.*lint", text), (
        "squad-run/SKILL.md must clarify that 'biome check --write' is NOT used "
        "(it applies lint fixes, not just formatting)"
    )


def test_genuine_lint_errors_still_reach_ranger(repo_root):
    """The section must state that genuine lint ERRORS and type errors are left untouched
    and still fail the Ranger gate — the format step does not mask real signal."""
    text = _read(repo_root, "skills/squad-run/SKILL.md")
    assert re.search(
        r"genuine lint (ERRORS?|errors?)|lint ERRORS? and type errors|lint errors? are left untouched",
        text,
        re.IGNORECASE,
    ), (
        "squad-run/SKILL.md must state that genuine lint ERRORS are NOT masked "
        "and still fail the Ranger gate"
    )
    assert re.search(
        r"still fail the Ranger gate|Ranger gate.*unchanged|Inspector and Ranger keep",
        text,
        re.IGNORECASE,
    ), (
        "squad-run/SKILL.md must state that Inspector/Ranger still run full lint "
        "(the format step only guarantees they never see a format-only failure)"
    )


# ---------------------------------------------------------------------------
# 3. Tool-agnostic + skip-clean (no hard-fail when formatter missing)
# ---------------------------------------------------------------------------


def test_format_normalization_is_tool_agnostic(repo_root):
    """The step must resolve the formatter from multiple candidates (not hard-coded to one tool).
    Expected ladder: repo format script, biome, ruff/black, gofmt, rustfmt, prettier."""
    text = _read(repo_root, "skills/squad-run/SKILL.md")
    # At least three distinct formatter tools must be named in the normalization section.
    formatters = ["biome", "ruff", "black", "gofmt", "rustfmt", "prettier"]
    found = [f for f in formatters if f in text]
    assert len(found) >= 3, (
        f"squad-run/SKILL.md must name at least 3 distinct formatters for tool-agnostic resolution "
        f"(found: {found})"
    )


def test_format_normalization_covers_repo_format_script(repo_root):
    """The resolution ladder must check for the repo's own 'format' script in package.json
    (or Makefile/justfile) before falling back to direct tool detection."""
    text = _read(repo_root, "skills/squad-run/SKILL.md")
    assert re.search(r'["\']format["\'].*package\.json|package\.json.*["\']format["\']', text), (
        "squad-run/SKILL.md must check for the repo's own 'format' script in package.json "
        "as the first resolution step"
    )


def test_format_normalization_skips_cleanly_when_no_formatter(repo_root):
    """When no formatter is resolvable the step must skip CLEANLY (never hard-fail)
    and log an Orchestrator activity note."""
    text = _read(repo_root, "skills/squad-run/SKILL.md")
    assert re.search(
        r"no formatter resolved|no resolvable formatter|no.*formatter.*skip",
        text,
        re.IGNORECASE,
    ), (
        "squad-run/SKILL.md must state the skip behaviour when no formatter is resolved"
    )
    # The skip must log an Orchestrator activity note (not silently swallow).
    assert re.search(r"format-normalize.*no formatter resolved.*skipped", text, re.IGNORECASE), (
        "squad-run/SKILL.md must log an Orchestrator activity note when skipping "
        "(format-normalize: no formatter resolved — skipped)"
    )
    # Must not hard-fail: best-effort / || true / never hard-fail.
    assert re.search(r"never hard-fail|best-effort|never hard.fail", text, re.IGNORECASE), (
        "squad-run/SKILL.md must state the step never hard-fails (best-effort)"
    )


def test_format_normalization_uses_bounded_changed_file_set(repo_root):
    """The step must compute a bounded file set from git diff + untracked files and pass
    it to the formatter — never reformatting the whole repo."""
    text = _read(repo_root, "skills/squad-run/SKILL.md")
    assert "git diff --name-only" in text, (
        "squad-run/SKILL.md must use 'git diff --name-only' to compute the bounded changed-file set"
    )
    assert re.search(r"git ls-files.*--others|--others.*exclude-standard", text), (
        "squad-run/SKILL.md must include 'git ls-files --others --exclude-standard' "
        "to capture new untracked files in the changed set"
    )


def test_format_normalization_l1_explicitly_excluded(repo_root):
    """The section must explicitly state that L1 (Builder-only, no Shield, no impl_review
    seam) is NOT covered by the deterministic step — L1 relies on the Builder template backstop."""
    text = _read(repo_root, "skills/squad-run/SKILL.md")
    assert re.search(r"L1.*no.*impl_review|L1.*not.*covered|L1 has no.*impl_review", text, re.IGNORECASE), (
        "squad-run/SKILL.md must state L1 is excluded from the deterministic step "
        "(L1 has no impl_review seam)"
    )
    assert re.search(r"L2/L3|L2 and L3|Level scope.*L2", text, re.IGNORECASE), (
        "squad-run/SKILL.md must scope the deterministic step to L2/L3 only"
    )


# ---------------------------------------------------------------------------
# 4 & 5. Template backstops: Shield (tdd-tester.md) + Builder (worker-agent.md)
# ---------------------------------------------------------------------------


def test_tdd_tester_contains_self_format_step(repo_root):
    """tdd-tester.md's '## Your Job' section must include an instruction for Shield to run
    the project's formatter on every file it added/modified and verify it exits clean
    before recording results."""
    text = _read(repo_root, "skills/squad/templates/tdd-tester.md")
    assert re.search(r"formatter", text, re.IGNORECASE), (
        "skills/squad/templates/tdd-tester.md must contain a self-format step "
        "(run the project formatter on modified files)"
    )
    assert re.search(
        r"formatter.*every file.*added or modified|run.*formatter.*modified|"
        r"format.*script.*or.*biome.*ruff",
        text,
        re.IGNORECASE,
    ), (
        "tdd-tester.md self-format step must instruct running the formatter on "
        "every file added or modified"
    )
    # "verify it exits clean before recording results" — the completion gate.
    assert re.search(r"verify.*exits? clean|exits? clean before recording|clean before recording", text, re.IGNORECASE), (
        "tdd-tester.md must instruct verifying the formatter exits clean "
        "BEFORE recording results"
    )


def test_tdd_tester_self_format_in_your_job_section(repo_root):
    """The self-format step must be inside the '## Your Job' numbered list (not buried in a note),
    so it is part of the actionable workflow Shield follows."""
    text = _read(repo_root, "skills/squad/templates/tdd-tester.md")
    # Find the ## Your Job section.
    your_job_m = re.search(r"^##\s+Your Job\b.*?(?=^##\s|\Z)", text, re.MULTILINE | re.DOTALL)
    assert your_job_m, "tdd-tester.md must have a '## Your Job' section"
    your_job = your_job_m.group(0)
    assert re.search(r"formatter", your_job, re.IGNORECASE), (
        "tdd-tester.md: the self-format instruction must be inside the '## Your Job' section"
    )


def test_worker_agent_contains_self_format_step(repo_root):
    """worker-agent.md's '## Your Job' section must include an instruction for Builder to run
    the project's formatter on every file it added/modified and verify it exits clean
    before recording results (the L1 backstop)."""
    text = _read(repo_root, "skills/squad/templates/worker-agent.md")
    assert re.search(r"formatter", text, re.IGNORECASE), (
        "skills/squad/templates/worker-agent.md must contain a self-format step "
        "(run the project formatter on modified files)"
    )
    assert re.search(
        r"formatter.*every file.*added or modified|run.*formatter.*modified|"
        r"format.*script.*or.*biome.*ruff",
        text,
        re.IGNORECASE,
    ), (
        "worker-agent.md self-format step must instruct running the formatter on "
        "every file added or modified"
    )
    assert re.search(r"verify.*exits? clean|exits? clean before recording|clean before recording", text, re.IGNORECASE), (
        "worker-agent.md must instruct verifying the formatter exits clean "
        "BEFORE recording results"
    )


def test_worker_agent_self_format_in_your_job_section(repo_root):
    """The self-format step must be inside the '## Your Job' numbered list in worker-agent.md."""
    text = _read(repo_root, "skills/squad/templates/worker-agent.md")
    your_job_m = re.search(r"^##\s+Your Job\b.*?(?=^##\s|\Z)", text, re.MULTILINE | re.DOTALL)
    assert your_job_m, "worker-agent.md must have a '## Your Job' section"
    your_job = your_job_m.group(0)
    assert re.search(r"formatter", your_job, re.IGNORECASE), (
        "worker-agent.md: the self-format instruction must be inside the '## Your Job' section"
    )


# ---------------------------------------------------------------------------
# Regression: both templates must be consistent (same essential instruction)
# ---------------------------------------------------------------------------


def test_both_templates_carry_matching_formatter_instruction(repo_root):
    """tdd-tester.md and worker-agent.md must both name the same multi-tool resolution
    pattern (format script, biome, ruff/black, gofmt/rustfmt equivalent) — so neither
    template drifts to a tool-specific instruction while the other stays generic."""
    tester = _read(repo_root, "skills/squad/templates/tdd-tester.md")
    worker = _read(repo_root, "skills/squad/templates/worker-agent.md")
    # Both must reference the repo's own 'format' script as a first-resort option.
    assert re.search(r"format.*script|format.*`format`", tester, re.IGNORECASE), (
        "tdd-tester.md must reference the repo's own 'format' script in the formatter instruction"
    )
    assert re.search(r"format.*script|format.*`format`", worker, re.IGNORECASE), (
        "worker-agent.md must reference the repo's own 'format' script in the formatter instruction"
    )
    # Both must name biome as one concrete example.
    assert "biome" in tester, "tdd-tester.md formatter instruction must name biome as an example"
    assert "biome" in worker, "worker-agent.md formatter instruction must name biome as an example"
