"""Gap-coverage tests for the spec-vs-description precedence contract (SQD-963).

These tests EXTEND ``test_spec_precedence_contract.py`` (10 assertions by Builder) — added by
Shield (sonnet) in the same TDD pass.  Do NOT duplicate the Builder's 10 assertions; cover the
identified gaps:

(a) The five spec-consuming templates each carry their OWN inline "With no spec, the Original
    Request is authoritative" clause at the consumption point — so an agent reading only its own
    prompt file is not left without the no-spec branch.  test-runner.md is excluded (non-applicable).

(b) squad-run/SKILL.md explicitly says "do not inject a per-prompt precedence guard" — the seam
    replaces the old ad-hoc pattern with the standing documented rule; this phrase is the key
    migration marker that proves the old workaround is gone.

(c) test-runner.md names the non-applicability reason: Ranger consumes neither the spec nor the
    description — the note is explanatory, not a misleading "follow the spec" directive.

(d) squad-run/SKILL.md explicitly passes ``SPEC_MD=""`` for Ranger — the seam documents that the
    test-runner agent's dispatch omits the spec payload, consistent with non-applicability.

(e) shared.md's no-spec branch carries the "never ignore it" enforcement phrase — pinning the
    concrete instruction against a future edit that softens the mandatory language to advisory.

(f) Non-vacuous self-test: the ``_spec_consuming_templates`` list excludes test-runner.md (the
    non-applicable template), so the per-template assertions are not vacuously satisfied by
    test-runner.md carrying the reference for a different reason.

Hermetic: reads committed skill files only, no network. Stdlib (``re``, ``pathlib``) only.
"""
import re

# ---------------------------------------------------------------------------
# paths
# ---------------------------------------------------------------------------

SHARED = "skills/squad/shared.md"
SKILL = "skills/squad-run/SKILL.md"
TEST_RUNNER = "skills/squad/templates/test-runner.md"

# The five templates that *consume* both spec and description (test-runner is excluded —
# Ranger reads neither; its note is a non-applicability reference, not a consumption rule).
SPEC_CONSUMING_TEMPLATES = [
    "skills/squad/templates/plan-agent.md",
    "skills/squad/templates/review-agent.md",
    "skills/squad/templates/worker-agent.md",
    "skills/squad/templates/tdd-tester.md",
    "skills/squad/templates/code-review-agent.md",
]


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _read(repo_root, rel: str) -> str:
    return (repo_root / rel).read_text(encoding="utf-8")


def _spec_precedence_section(text: str) -> str:
    """Body of the ``### Spec Precedence`` subsection (up to the next heading or EOF)."""
    m = re.search(
        r"^###\s+Spec Precedence\b.*?(?=^###\s|^##\s|\Z)",
        text,
        re.MULTILINE | re.DOTALL,
    )
    return m.group(0) if m else ""


# ---------------------------------------------------------------------------
# (a) Each spec-consuming template carries the no-spec branch at its own consumption point
# ---------------------------------------------------------------------------

def test_spec_consuming_templates_each_state_description_authoritative_when_no_spec(repo_root):
    """Every spec-consuming template must say 'With no spec, the Original Request is authoritative'
    (or equivalent) at its ## Original Request consumption point — so agents receive the no-spec
    branch directly in their own prompt without having to cross-reference shared.md at read time."""
    for rel in SPEC_CONSUMING_TEMPLATES:
        text = _read(repo_root, rel)
        assert re.search(
            r"[Ww]ith no spec[,\s]+[Tt]he [Oo]riginal [Rr]equest is authoritative"
            r"|[Ww]ith no spec[^.\n]*authoritative"
            r"|no spec[^\n]*description.*authoritative"
            r"|description.*authoritative.*no spec",
            text,
        ), (
            f"{rel} must carry an inline no-spec clause at its ## Original Request block "
            "(e.g. 'With no spec, the Original Request is authoritative') so the agent "
            "is not left without the fallback branch in its own prompt"
        )


def test_test_runner_excluded_from_spec_consuming_list():
    """test-runner.md must NOT be in SPEC_CONSUMING_TEMPLATES — it is the non-applicable
    template (Ranger consumes neither spec nor description)."""
    assert TEST_RUNNER not in SPEC_CONSUMING_TEMPLATES, (
        "test-runner.md must be excluded from SPEC_CONSUMING_TEMPLATES — it is the non-applicable "
        "template and its precedence note is a non-applicability reference, not a consumption rule"
    )


# ---------------------------------------------------------------------------
# (b) SKILL.md explicitly prohibits the old ad-hoc per-prompt guard
# ---------------------------------------------------------------------------

def test_skill_dispatch_seam_prohibits_per_prompt_guard(repo_root):
    """squad-run/SKILL.md dispatch seam must explicitly say 'do not inject a per-prompt
    precedence guard' — this is the key migration marker proving the old workaround is replaced
    by the standing documented rule."""
    text = _read(repo_root, SKILL)
    assert re.search(
        r"do not inject a per-prompt precedence guard"
        r"|do not inject.*per-prompt"
        r"|per-prompt.*precedence guard",
        text,
        re.IGNORECASE,
    ), (
        "squad-run/SKILL.md must explicitly say 'do not inject a per-prompt precedence guard' "
        "at the dispatch seam — this phrase proves the old ad-hoc workaround is replaced by the "
        "standing rule and prevents regression to the inject-everywhere pattern"
    )


# ---------------------------------------------------------------------------
# (c) test-runner.md non-applicability note is explanatory, not a "follow the spec" directive
# ---------------------------------------------------------------------------

def test_test_runner_names_non_applicability_reason(repo_root):
    """test-runner.md must explain WHY the rule does not apply: Ranger consumes neither the
    spec nor the description.  An unexplained 'does not apply' would be less clear."""
    text = _read(repo_root, TEST_RUNNER)
    assert re.search(
        r"neither the spec nor the description"
        r"|consumes neither.*spec.*description"
        r"|neither.*spec.*description",
        text,
        re.IGNORECASE,
    ), (
        "test-runner.md must explain that Ranger consumes neither the spec nor the description "
        "— the reason the precedence rule is non-applicable"
    )


def test_test_runner_does_not_say_follow_the_spec(repo_root):
    """test-runner.md must NOT instruct the agent to 'follow the spec' — Ranger does not
    consume the spec at all.  A 'follow the spec' directive would be misleading."""
    text = _read(repo_root, TEST_RUNNER)
    assert not re.search(r"follow the spec", text, re.IGNORECASE), (
        "test-runner.md must NOT contain 'follow the spec' — Ranger is non-applicable to the "
        "precedence rule and should not receive a spec-consumption directive"
    )


def test_test_runner_non_applicability_says_does_not_apply(repo_root):
    """test-runner.md must say the precedence rule 'does not apply' to its inputs — so the
    non-applicability is explicit, not just implied by the absence of a follow-the-spec line."""
    text = _read(repo_root, TEST_RUNNER)
    assert re.search(r"does not apply", text, re.IGNORECASE), (
        "test-runner.md must explicitly say the precedence rule 'does not apply' to its inputs"
    )


# ---------------------------------------------------------------------------
# (d) SKILL.md explicitly passes SPEC_MD="" for Ranger
# ---------------------------------------------------------------------------

def test_skill_passes_empty_spec_for_ranger(repo_root):
    """squad-run/SKILL.md must document that SPEC_MD=\"\" is passed for Ranger — the seam
    explicitly omits the spec payload for the test-runner dispatch, consistent with
    non-applicability."""
    text = _read(repo_root, SKILL)
    assert re.search(
        r'SPEC_MD=""\s*for\s*Ranger|pass\s*SPEC_MD=""\s*for\s*Ranger',
        text,
        re.IGNORECASE,
    ), (
        "squad-run/SKILL.md must document that SPEC_MD=\"\" is passed for Ranger — the seam "
        "comment proves Ranger's dispatch intentionally omits the spec payload"
    )


# ---------------------------------------------------------------------------
# (e) shared.md's no-spec branch carries "never ignore it" (mandatory, not advisory)
# ---------------------------------------------------------------------------

def test_shared_no_spec_branch_uses_never_ignore_it(repo_root):
    """shared.md Spec Precedence no-spec branch must say 'never ignore it' — the mandatory
    enforcement language.  Softening this to advisory (e.g. 'prefer the description') would
    allow an agent to silently ignore the description when no spec is present."""
    section = _spec_precedence_section(_read(repo_root, SHARED))
    assert section, "shared.md must contain a '### Spec Precedence' subsection"
    assert re.search(r"never ignore it", section, re.IGNORECASE), (
        "shared.md Spec Precedence no-spec branch must carry 'never ignore it' — the mandatory "
        "enforcement phrase; softening to advisory would break the CONSTRAINT that the rule "
        "must never tell agents to ignore the description when no spec exists"
    )


# ---------------------------------------------------------------------------
# (f) Non-vacuous self-test: SPEC_CONSUMING_TEMPLATES has exactly 5 entries (test-runner excluded)
# ---------------------------------------------------------------------------

def test_spec_consuming_templates_list_has_exactly_five_entries():
    """SPEC_CONSUMING_TEMPLATES must contain exactly 5 entries — one per spec-consuming pipeline
    agent (Planner/Critic/Builder/Shield/Inspector) — confirming test-runner.md is excluded and
    no template was accidentally dropped from the list."""
    assert len(SPEC_CONSUMING_TEMPLATES) == 5, (
        f"SPEC_CONSUMING_TEMPLATES must have exactly 5 entries (one per spec-consuming agent), "
        f"got {len(SPEC_CONSUMING_TEMPLATES)}: {SPEC_CONSUMING_TEMPLATES}"
    )
