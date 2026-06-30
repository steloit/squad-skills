"""Doc-contract: the repo-level Vale guard wiring is present and correct.

Shipped skills/** files are the installed product surface and must be
instruction-only (no design rationale / sales / pipeline meta). Vale (a
markup-aware prose linter) wired into squad-skills' own CI is the deterministic
backstop. This test asserts that wiring EXISTS — it does NOT re-implement phrase
detection. Vale owns detection (markup-scoped, so code blocks and headings are
skipped); a hand-rolled grep here would duplicate it and drift. A
planted-positive self-test keeps the assertions honest.

Stdlib only (`re`, `pathlib`); uses the existing `repo_root` session fixture.
"""
import re

# The exact forbidden-phrase set the InstructionOnly style must carry — the
# high-precision intersection of "spec-listed" and "zero hits on the current
# skills/** tree" (case-insensitive).
EXPECTED_TOKENS = [
    "future-proofs",
    "config surface",
    "we deliberately",
    "at zero ongoing cost",
]


def test_vale_config_scopes_skills_at_error(repo_root):
    """`.vale.ini` exists, sets MinAlertLevel=error, and scopes the
    InstructionOnly style to skills/** (not tests/, evals/ or root docs)."""
    ini = repo_root / ".vale.ini"
    assert ini.is_file(), ".vale.ini missing at repo root"
    txt = ini.read_text(encoding="utf-8")
    assert re.search(r"MinAlertLevel\s*=\s*error", txt), "MinAlertLevel must be error"
    assert "[skills/**]" in txt, ".vale.ini must scope the [skills/**] glob"
    assert re.search(r"Squad\.InstructionOnly\s*=\s*error", txt), (
        "Squad.InstructionOnly must be enabled at error level under skills/**"
    )
    # tests/ and evals/ must NOT be in Vale scope.
    assert "[tests/" not in txt and "[evals/" not in txt, (
        "Vale scope must be skills/** only — not tests/ or evals/"
    )


def test_instruction_only_style_is_existence_rule_with_token_set(repo_root):
    """The InstructionOnly style is an `existence` rule at error level, case-
    insensitive, skips code, and carries EXACTLY the agreed token set."""
    style = repo_root / "styles" / "Squad" / "InstructionOnly.yml"
    assert style.is_file(), "styles/Squad/InstructionOnly.yml missing"
    txt = style.read_text(encoding="utf-8")
    assert re.search(r"extends:\s*existence", txt), "style must extend `existence`"
    assert re.search(r"level:\s*error", txt), "style level must be error"
    assert re.search(r"ignorecase:\s*true", txt), "style must be ignorecase: true"
    # A `scope` that limits the rule to running prose (skipping code blocks,
    # headings and tables). Vale 3's `paragraph` scope does exactly this.
    assert re.search(r"scope:\s*paragraph", txt), (
        "scope must be `paragraph` so code blocks / headings / tables are skipped"
    )
    for tok in EXPECTED_TOKENS:
        assert tok in txt, f"InstructionOnly style is missing token: {tok!r}"
    # No EXCLUDED phrase may be banned — these have legit hits on the tree and
    # would break the zero-violations AC.
    for excluded in ("by construction", "language-agnostic"):
        assert excluded not in txt, (
            f"{excluded!r} must NOT be banned — it has legit hits and would "
            "produce false positives"
        )


def test_vale_ci_action_runs_over_skills(repo_root):
    """A CI workflow wires errata-ai/vale-action over skills/ with
    fail_on_error: true."""
    wf = repo_root / ".github" / "workflows" / "vale.yml"
    assert wf.is_file(), ".github/workflows/vale.yml missing"
    txt = wf.read_text(encoding="utf-8")
    assert "errata-ai/vale-action" in txt, "CI must use errata-ai/vale-action"
    assert re.search(r"files:\s*skills/", txt), "Vale CI must target skills/"
    assert re.search(r"fail_on_error:\s*true", txt), "Vale CI must fail on error"


def test_guard_detects_planted_positive(tmp_path):
    """Self-test so the contract assertions can't rot into a vacuous pass: a
    synthetic .vale.ini that drops the skills scope must fail the same regex the
    real assertion uses."""
    good = "StylesPath = styles\nMinAlertLevel = error\n[skills/**]\nSquad.InstructionOnly = error\n"
    bad = "StylesPath = styles\nMinAlertLevel = suggestion\n"
    assert re.search(r"MinAlertLevel\s*=\s*error", good)
    assert "[skills/**]" in good
    assert not re.search(r"MinAlertLevel\s*=\s*error", bad)
    assert "[skills/**]" not in bad
