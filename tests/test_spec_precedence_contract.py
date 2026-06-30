"""Structural guards for the spec-vs-description precedence contract (#SQD-963).

A card carries two sources of human intent — the human's ``description`` (the original
request) and the Refiner's ``spec``. When a refine deliberately reverses the original
direction, a stale ``description`` can silently steer agents into the wrong shape. The
fix mirrors the Command Resolution **authored-once / referenced-many** pattern: ONE
canonical precedence rule lives in ``skills/squad/shared.md`` → **Spec Precedence**,
is enforced at the ``squad-run`` dispatch seam, and is merely REFERENCED (never
re-stated) by the six pipeline templates.

Load-bearing properties guarded here:

(a) shared.md authors the rule with ALL branches — spec authoritative when present,
    description authoritative when NO spec (the conditional CONSTRAINT), and a no-op
    when there is no conflict.
(b) squad-run/SKILL.md dispatch seam carries the orchestrator instruction (spec
    authoritative + description = original request that may predate the spec) and
    points at shared.md.
(c) each of the six templates references the rule at its consumption point WITHOUT
    inlining the rule body.

Hermetic: reads committed skill files only, no network. Stdlib (`re`) only.
"""
import re

# ---------------------------------------------------------------------------
# paths
# ---------------------------------------------------------------------------

SHARED = "skills/squad/shared.md"
SKILL = "skills/squad-run/SKILL.md"
TEMPLATES = [
    "skills/squad/templates/plan-agent.md",
    "skills/squad/templates/review-agent.md",
    "skills/squad/templates/worker-agent.md",
    "skills/squad/templates/tdd-tester.md",
    "skills/squad/templates/code-review-agent.md",
    "skills/squad/templates/test-runner.md",
]

# The reference marker every template must carry at its consumption point.
PRECEDENCE_REF = "Spec Precedence"

# A full rule sentence that lives ONLY in shared.md — it must NOT be inlined into any
# template (the negative "no rule-text duplication" guard).
RULE_BODY_PHRASE = "authoritative source of intent"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _read(repo_root, rel: str) -> str:
    return (repo_root / rel).read_text(encoding="utf-8")


def _spec_precedence_section(text: str) -> str:
    """Body of the ``### Spec Precedence`` subsection (up to the next ``## `` / ``### `` or EOF)."""
    m = re.search(
        r"^###\s+Spec Precedence\b.*?(?=^###\s|^##\s|\Z)",
        text,
        re.MULTILINE | re.DOTALL,
    )
    return m.group(0) if m else ""


# ---------------------------------------------------------------------------
# (a) shared.md authors the rule with every branch
# ---------------------------------------------------------------------------

def test_shared_has_spec_precedence_subsection(repo_root):
    section = _spec_precedence_section(_read(repo_root, SHARED))
    assert section, "shared.md must contain a '### Spec Precedence' subsection"


def test_shared_states_spec_authoritative_when_present(repo_root):
    section = _spec_precedence_section(_read(repo_root, SHARED))
    assert re.search(r"non-null\s+`?spec`?", section, re.IGNORECASE), (
        "shared.md Spec Precedence must name the non-null spec case"
    )
    assert "authoritative" in section.lower(), (
        "shared.md Spec Precedence must declare the spec authoritative when present"
    )


def test_shared_states_follow_spec_on_conflict(repo_root):
    section = _spec_precedence_section(_read(repo_root, SHARED))
    assert re.search(r"conflict", section, re.IGNORECASE) and re.search(
        r"follow the spec", section, re.IGNORECASE
    ), "shared.md Spec Precedence must say: on a conflict, follow the spec"


def test_shared_states_description_authoritative_when_no_spec(repo_root):
    """The conditional CONSTRAINT: with NO spec, the description is authoritative —
    the rule must never tell agents to ignore the description."""
    section = _spec_precedence_section(_read(repo_root, SHARED))
    assert re.search(r"no spec", section, re.IGNORECASE), (
        "shared.md Spec Precedence must name the no-spec branch"
    )
    assert re.search(
        r"`?description`?[^\n]*authoritative|authoritative[^\n]*`?description`?",
        section,
        re.IGNORECASE,
    ), "shared.md must say the description is authoritative when there is no spec"


def test_shared_states_no_conflict_is_a_noop(repo_root):
    section = _spec_precedence_section(_read(repo_root, SHARED))
    assert re.search(r"no-op|no op", section, re.IGNORECASE), (
        "shared.md Spec Precedence must state the no-conflict case is a no-op"
    )


def test_shared_carries_no_board_id(repo_root):
    """The authored rule is shipped prose — it must carry no SQD-NNN board id."""
    section = _spec_precedence_section(_read(repo_root, SHARED))
    assert not re.search(r"SQD-\d+", section), (
        "shared.md Spec Precedence subsection must not embed a board id"
    )


# ---------------------------------------------------------------------------
# (b) squad-run/SKILL.md enforces the rule at the dispatch seam
# ---------------------------------------------------------------------------

def test_skill_dispatch_seam_carries_precedence_instruction(repo_root):
    text = _read(repo_root, SKILL)
    assert PRECEDENCE_REF in text, (
        "squad-run/SKILL.md dispatch seam must reference the Spec Precedence rule"
    )
    assert "shared.md" in text, (
        "squad-run/SKILL.md must point to shared.md for the precedence rule"
    )
    assert re.search(r"authoritative", text, re.IGNORECASE) and re.search(
        r"predate the spec", text, re.IGNORECASE
    ), (
        "squad-run/SKILL.md must present the spec as authoritative and label the "
        "description as the original request that may predate the spec"
    )


# ---------------------------------------------------------------------------
# (c) each of the six templates references the rule WITHOUT inlining it
# ---------------------------------------------------------------------------

def test_each_template_references_the_rule(repo_root):
    for rel in TEMPLATES:
        text = _read(repo_root, rel)
        assert PRECEDENCE_REF in text, (
            f"{rel} must reference the Spec Precedence rule at its consumption point"
        )
        assert "shared.md" in text, (
            f"{rel} must point to shared.md for the precedence rule"
        )


def test_templates_do_not_inline_the_rule_body(repo_root):
    """No template may duplicate the rule body — the canonical text lives only in shared.md."""
    for rel in TEMPLATES:
        text = _read(repo_root, rel)
        assert RULE_BODY_PHRASE not in text, (
            f"{rel} inlines the rule body ({RULE_BODY_PHRASE!r}) — reference shared.md, "
            "don't duplicate the rule"
        )


# ---------------------------------------------------------------------------
# self-test — keep the suite non-vacuous
# ---------------------------------------------------------------------------

def test_section_extractor_is_non_vacuous():
    """A planted '### Spec Precedence' block is extracted; an absent one yields ''."""
    planted = "## X\n\n### Spec Precedence\n\nbody here\n\n## Y\n"
    assert "body here" in _spec_precedence_section(planted)
    assert _spec_precedence_section("## X\n\nno subsection\n") == ""
