"""Structural guards for the Role Boundary (stay-in-your-lane / report-don't-fix) contract (SQD-871).

The pipeline had a cross-cutting gap: only the Coach template forbade editing outside
its lane, while the verify / review / test-author agents (Ranger, Inspector, Shield)
carried no edit boundary and could touch production source. The fix mirrors the
Command Resolution / Spec Precedence **authored-once / referenced-many** pattern: ONE
canonical Role Boundary principle lives in ``skills/squad/shared.md`` → **Role
Boundary**, and the three high-risk templates merely REFERENCE it (never re-state it).

Load-bearing properties guarded here:

(a) shared.md authors the principle with ALL four clauses — own-artifact-only; a
    review / verify agent records a verdict + edits nothing; a test-author writes
    tests, not production source; report → orchestrator routes back → Builder fixes.
(b) the section explicitly DISTINGUISHES the Role Boundary (Axis-B, the worked-repo
    role lane) from the Squad-tool friction rule (Axis-A, the tooling), naming both.
(c) the section carries no board id (instruction-only guard).
(d) each of the three templates (Ranger / Shield / Inspector) references the rule and
    points at shared.md, WITHOUT inlining the canonical rule body.

Hermetic: reads committed skill files only, no network. Stdlib (`re`) only.
"""
import re

# ---------------------------------------------------------------------------
# paths
# ---------------------------------------------------------------------------

SHARED = "skills/squad/shared.md"
TEMPLATES = [
    "skills/squad/templates/test-runner.md",       # Ranger
    "skills/squad/templates/tdd-tester.md",         # Shield
    "skills/squad/templates/code-review-agent.md",  # Inspector
]

# The reference marker every template must carry at its consumption point.
ROLE_BOUNDARY_REF = "Role Boundary"

# A canonical rule-body phrase authored ONLY in shared.md — it must NOT be inlined into
# any template (the negative "no rule-text duplication" guard).
RULE_BODY_PHRASE = "writes only its own artifact"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _read(repo_root, rel: str) -> str:
    return (repo_root / rel).read_text(encoding="utf-8")


def _role_boundary_section(text: str) -> str:
    """Body of the ``## Role Boundary`` section (up to the next ``## `` heading or EOF)."""
    m = re.search(
        r"^##\s+Role Boundary\b.*?(?=^##\s|\Z)",
        text,
        re.MULTILINE | re.DOTALL,
    )
    return m.group(0) if m else ""


# ---------------------------------------------------------------------------
# (a) shared.md authors the principle with every clause
# ---------------------------------------------------------------------------

def test_shared_has_role_boundary_section(repo_root):
    section = _role_boundary_section(_read(repo_root, SHARED))
    assert section, "shared.md must contain a '## Role Boundary' section"


def test_shared_states_own_artifact_only(repo_root):
    """Clause 1: each agent writes only its own artifact / file."""
    section = _role_boundary_section(_read(repo_root, SHARED))
    assert RULE_BODY_PHRASE in section, (
        "shared.md Role Boundary must state each agent writes only its own artifact"
    )


def test_shared_states_verify_agent_records_verdict_edits_nothing(repo_root):
    """Clause 2: a review / verify agent records a verdict and edits nothing it evaluates."""
    section = _role_boundary_section(_read(repo_root, SHARED))
    assert re.search(r"records a verdict and edits nothing", section, re.IGNORECASE), (
        "shared.md Role Boundary must say a review/verify agent records a verdict + edits nothing"
    )


def test_shared_states_tests_not_production_source(repo_root):
    """Clause 3: a test-author (Shield) writes tests, not production source."""
    section = _role_boundary_section(_read(repo_root, SHARED))
    assert re.search(r"tests,?\s+not\s+production\s+source", section, re.IGNORECASE), (
        "shared.md Role Boundary must say the test-author writes tests, not production source"
    )


def test_shared_states_report_route_back_builder_fixes(repo_root):
    """Clause 4: report (fail / changes_requested) → orchestrator routes back → Builder owns the fix."""
    section = _role_boundary_section(_read(repo_root, SHARED))
    assert re.search(r"\bfail\b", section) and re.search(r"changes_requested", section), (
        "shared.md Role Boundary must name the fail / changes_requested verdicts"
    )
    assert re.search(r"route", section, re.IGNORECASE), (
        "shared.md Role Boundary must say the orchestrator routes the card back"
    )
    assert re.search(r"Builder owns the fix", section), (
        "shared.md Role Boundary must say Builder owns the fix on route-back"
    )


def test_shared_carves_out_builder_lane(repo_root):
    """Builder's production-source lane is explicitly NOT constrained by this principle."""
    section = _role_boundary_section(_read(repo_root, SHARED))
    assert re.search(r"Builder", section) and re.search(
        r"not a boundary violation", section, re.IGNORECASE
    ), "shared.md Role Boundary must carve out Builder's production-source lane"


# ---------------------------------------------------------------------------
# (b) the section distinguishes Axis-A (friction) from Axis-B (Role Boundary)
# ---------------------------------------------------------------------------

def test_shared_distinguishes_friction_from_role_boundary(repo_root):
    section = _role_boundary_section(_read(repo_root, SHARED))
    assert "Axis-A" in section and "Axis-B" in section, (
        "shared.md Role Boundary must label the two axes (Axis-A / Axis-B)"
    )
    assert re.search(r"friction", section, re.IGNORECASE), (
        "shared.md Role Boundary must name the Squad-tool friction rule as the distinct axis"
    )
    assert "Squad Friction Reports" in section, (
        "shared.md Role Boundary must point at the Squad Friction Reports rule it is distinct from"
    )


def test_shared_distinguishes_from_domain_field_ownership(repo_root):
    """Critic's note: keep the 'artifact / file' lane distinct from Agent Context Flow's
    'domain field' board-field ownership so they don't read as the same rule."""
    section = _role_boundary_section(_read(repo_root, SHARED))
    assert "domain field" in section, (
        "shared.md Role Boundary must distinguish itself from the 'domain field' ownership rule"
    )


# ---------------------------------------------------------------------------
# (c) instruction-only guard — no board id in the authored section
# ---------------------------------------------------------------------------

def test_shared_role_boundary_carries_no_board_id(repo_root):
    """The authored rule is shipped prose — it must carry no SQD-NNN board id."""
    section = _role_boundary_section(_read(repo_root, SHARED))
    assert not re.search(r"SQD-\d+", section), (
        "shared.md Role Boundary section must not embed a board id"
    )


# ---------------------------------------------------------------------------
# (d) each of the three templates references the rule WITHOUT inlining it
# ---------------------------------------------------------------------------

def test_each_template_references_the_rule(repo_root):
    for rel in TEMPLATES:
        text = _read(repo_root, rel)
        assert ROLE_BOUNDARY_REF in text, (
            f"{rel} must reference the Role Boundary rule at its consumption point"
        )
        assert "shared.md" in text, (
            f"{rel} must point to shared.md for the Role Boundary rule"
        )


def test_templates_do_not_inline_the_rule_body(repo_root):
    """No template may duplicate the canonical rule body — it lives only in shared.md."""
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
    """A planted '## Role Boundary' block is extracted; an absent one yields ''."""
    planted = "## X\n\n## Role Boundary\n\nbody here\n\n## Y\n"
    assert "body here" in _role_boundary_section(planted)
    assert _role_boundary_section("## X\n\nno section\n") == ""
