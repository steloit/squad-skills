"""Gap-coverage tests for the Role Boundary (stay-in-your-lane / report-don't-fix) contract
(SQD-871).

These tests EXTEND ``test_role_boundary_contract.py`` (12 assertions by Builder) — added by
Shield (sonnet) in the same TDD pass.  Do NOT duplicate the Builder's 12 assertions; cover the
identified gaps, mirroring ``test_spec_precedence_contract_shield.py``'s companion pattern:

Send-back update: the spec's two MAY (optional) templates — Planner (plan-agent.md) and Critic
(review-agent.md) — were subsequently added by Builder for complete systemic pipeline coverage.
(g) below covers their pointer-only references individually, and (h) locks the full pipeline
picture: exactly the five templates (Ranger/Shield/Inspector/Planner/Critic) reference the rule
repo-wide, while coach.md and worker-agent.md still carry none — so the contract stays accurate
as "3 required + 2 now-included optional", not silently drifting to some other count.

(a) The carve-out preserves Builder's pre-existing **surgical-changes** scope discipline — the
    carve-out must not read as "Builder is now unconstrained", only "this NEW principle adds no
    limit"; the existing scope discipline must still be named as still applying.

(b) The Axis-A vs Axis-B distinction is a CONCRETE contrast, not just both labels appearing
    somewhere in the section: "do not conflate them" / "never fold one into the other" must be
    present, and Axis-B must be tied explicitly to the *worked* repo (not just labelled).

(c) Each of the three high-risk templates (Ranger / Shield / Inspector) is checked
    INDIVIDUALLY (own test function, own failure message) for the pointer-only reference —
    the Builder's version loops all three inside one test node, which loses per-template
    failure isolation.

(d) coach.md and worker-agent.md are asserted UNCHANGED with respect to Role Boundary — they
    must carry no reference (the spec says Coach already embodies the rule and needs no change,
    Builder's own authoring lane needs no boundary).

(e) The "artifact / file" lane is honored as distinct from the pre-existing "domain field"
    board-field-ownership concept: the literal "don't read them as the same rule" contrast
    phrase must be present, AND the "domain field" phrase this section points at must be a real,
    independently-defined concept elsewhere in shared.md (Agent Context Flow) — not a phrase
    invented only inside the Role Boundary section for the test to match.

(f) Non-vacuous self-tests for this file's own helpers (a differently-planted section extractor
    case, and a sanity check that the individual per-template list matches the Builder's).

Hermetic: reads committed skill files only, no network. Stdlib (``re``) only.
"""
import re

# ---------------------------------------------------------------------------
# paths
# ---------------------------------------------------------------------------

SHARED = "skills/squad/shared.md"

RANGER_TEMPLATE = "skills/squad/templates/test-runner.md"
SHIELD_TEMPLATE = "skills/squad/templates/tdd-tester.md"
INSPECTOR_TEMPLATE = "skills/squad/templates/code-review-agent.md"

# The two spec-optional ("MAY") templates, added by Builder in the send-back.
PLANNER_TEMPLATE = "skills/squad/templates/plan-agent.md"
CRITIC_TEMPLATE = "skills/squad/templates/review-agent.md"

# Templates the spec explicitly says must NOT change / reference the rule.
COACH_TEMPLATE = "skills/squad/templates/coach.md"
BUILDER_TEMPLATE = "skills/squad/templates/worker-agent.md"

# All templates in the skill (used for the repo-wide, order-independent count check below).
ALL_TEMPLATES = {
    RANGER_TEMPLATE,
    SHIELD_TEMPLATE,
    INSPECTOR_TEMPLATE,
    PLANNER_TEMPLATE,
    CRITIC_TEMPLATE,
    COACH_TEMPLATE,
    BUILDER_TEMPLATE,
}

RULE_BODY_PHRASE = "writes only its own artifact"


# ---------------------------------------------------------------------------
# helpers (kept local — this file does not import the Builder's test module)
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


def _assert_pointer_only(repo_root, rel: str):
    """Shared body for the per-template pointer-only checks (called individually per
    template below so each gets its own failing test node / message)."""
    text = _read(repo_root, rel)
    assert re.search(r"shared\.md.{0,15}→.{0,20}Role Boundary", text, re.DOTALL), (
        f"{rel} must carry a concrete '...shared.md` → **Role Boundary**' pointer, not just "
        "the words 'Role Boundary' and 'shared.md' anywhere in the file"
    )
    assert RULE_BODY_PHRASE not in text, (
        f"{rel} must not inline the canonical rule body ({RULE_BODY_PHRASE!r}) — pointer only"
    )


# ---------------------------------------------------------------------------
# (a) the Builder carve-out preserves Builder's PRE-EXISTING surgical-changes scope discipline
# ---------------------------------------------------------------------------

def test_builder_carveout_preserves_surgical_scope_discipline(repo_root):
    """The carve-out must say Builder's existing surgical-changes discipline STILL applies —
    not merely that Builder authoring source isn't a violation. Otherwise the carve-out could
    misread as removing Builder's scope discipline instead of just not adding a NEW limit."""
    section = _role_boundary_section(_read(repo_root, SHARED))
    assert re.search(r"surgical", section, re.IGNORECASE), (
        "shared.md Role Boundary carve-out must reference Builder's surgical-changes scope "
        "discipline by name"
    )
    assert re.search(r"scope discipline still applies", section, re.IGNORECASE), (
        "shared.md Role Boundary carve-out must say Builder's scope discipline STILL applies "
        "(this principle adds no new limit, it doesn't remove the existing one)"
    )
    assert re.search(r"adds no new limit", section, re.IGNORECASE), (
        "shared.md Role Boundary carve-out must explicitly say it adds NO NEW limit on the "
        "Builder lane, distinguishing 'no new constraint' from 'no constraint at all'"
    )


# ---------------------------------------------------------------------------
# (b) the Axis-A / Axis-B contrast is concrete, not just both labels present
# ---------------------------------------------------------------------------

def test_axis_distinction_has_concrete_contrast_language(repo_root):
    """Beyond both labels appearing, the section must carry the explicit contrast markers that
    make this a genuine distinction rather than two unrelated mentions of 'Axis-A'/'Axis-B'."""
    section = _role_boundary_section(_read(repo_root, SHARED))
    assert re.search(r"do not conflate them", section, re.IGNORECASE), (
        "shared.md Role Boundary must explicitly instruct not to conflate the two axes"
    )
    assert re.search(r"never fold one into the other", section, re.IGNORECASE), (
        "shared.md Role Boundary must explicitly say an agent never folds one axis into the "
        "other — the concrete anti-conflation instruction, not just adjacent mentions"
    )


def test_axis_b_is_concretely_tied_to_the_worked_repo(repo_root):
    """Axis-B must name the *worked* repo directly in its own bullet — proving the contrast
    is concrete (Axis-B = the repo under work) and not just a bare label next to Axis-A."""
    section = _role_boundary_section(_read(repo_root, SHARED))
    m = re.search(r"Axis-B[^\n]*\n(?:[^\n]*\n){0,2}", section)
    assert m, "shared.md Role Boundary must have an Axis-B bullet"
    axis_b_block = m.group(0)
    assert re.search(r"role lane", axis_b_block, re.IGNORECASE), (
        "Axis-B's own bullet must name the 'role lane' concept directly"
    )
    assert re.search(r"worked.{0,5}repo", axis_b_block, re.IGNORECASE), (
        "Axis-B's own bullet must tie the role lane concretely to the *worked* repo, not just "
        "an abstract label paired with Axis-A"
    )


def test_axis_a_is_concretely_tied_to_squad_tooling_not_the_worked_repo(repo_root):
    """Axis-A's own bullet must name the tooling/product (never the worked repo) — the mirror
    check to (b) above, so the contrast is symmetric and concrete on both sides."""
    section = _role_boundary_section(_read(repo_root, SHARED))
    m = re.search(r"Axis-A[^\n]*\n(?:[^\n]*\n){0,2}", section)
    assert m, "shared.md Role Boundary must have an Axis-A bullet"
    axis_a_block = m.group(0)
    assert re.search(r"tooling", axis_a_block, re.IGNORECASE), (
        "Axis-A's own bullet must name the Squad tooling directly"
    )
    assert "Squad Friction Reports" in axis_a_block, (
        "Axis-A's own bullet must point at Squad Friction Reports, not just the section overall"
    )


# ---------------------------------------------------------------------------
# (c) per-template pointer-only checks, isolated one test node per template
# ---------------------------------------------------------------------------

def test_ranger_template_pointer_only(repo_root):
    _assert_pointer_only(repo_root, RANGER_TEMPLATE)


def test_shield_template_pointer_only(repo_root):
    _assert_pointer_only(repo_root, SHIELD_TEMPLATE)


def test_inspector_template_pointer_only(repo_root):
    _assert_pointer_only(repo_root, INSPECTOR_TEMPLATE)


# ---------------------------------------------------------------------------
# (g) the two spec-optional ("MAY") templates, added in the send-back: Planner / Critic
# ---------------------------------------------------------------------------

def test_planner_template_pointer_only(repo_root):
    """plan-agent.md (Planner) — spec-optional, now included: pointer-only, own lane (the
    plan, not code)."""
    _assert_pointer_only(repo_root, PLANNER_TEMPLATE)


def test_critic_template_pointer_only(repo_root):
    """review-agent.md (Critic) — spec-optional, now included: pointer-only, own lane (a plan
    verdict, not an edit)."""
    _assert_pointer_only(repo_root, CRITIC_TEMPLATE)


# ---------------------------------------------------------------------------
# (h) repo-wide: exactly the five templates reference the rule, no silent drift
# ---------------------------------------------------------------------------

def test_exactly_five_templates_reference_role_boundary_repo_wide(repo_root):
    """Send-back locks in the completed picture: Ranger/Shield/Inspector (required) plus
    Planner/Critic (spec-optional, now added) reference the rule — five total, not three and
    not more — while coach.md and worker-agent.md still carry none. Guards against a future
    change silently adding or dropping a reference without updating this contract."""
    referencing = {
        rel for rel in ALL_TEMPLATES if "Role Boundary" in _read(repo_root, rel)
    }
    assert referencing == {
        RANGER_TEMPLATE,
        SHIELD_TEMPLATE,
        INSPECTOR_TEMPLATE,
        PLANNER_TEMPLATE,
        CRITIC_TEMPLATE,
    }, (
        "expected exactly Ranger/Shield/Inspector/Planner/Critic to reference Role Boundary "
        f"repo-wide; got {sorted(referencing)}"
    )
    assert len(referencing) == 5


# ---------------------------------------------------------------------------
# (d) coach.md and worker-agent.md are unchanged w.r.t. Role Boundary
# ---------------------------------------------------------------------------

def test_coach_template_has_no_role_boundary_reference(repo_root):
    """coach.md must carry NO Role Boundary reference — the spec says Coach already embodies
    the rule and needs no change; a reference here would mean scope crept beyond the 3
    required templates."""
    text = _read(repo_root, COACH_TEMPLATE)
    assert "Role Boundary" not in text, (
        "coach.md must not reference Role Boundary — Coach already embodies the rule and the "
        "spec explicitly says it needs no change"
    )


def test_builder_template_has_no_role_boundary_reference(repo_root):
    """worker-agent.md (Builder) must carry NO Role Boundary reference — Builder's authoring
    lane is the one the principle explicitly does NOT constrain, so its own template should
    not need (and must not gain) a pointer."""
    text = _read(repo_root, BUILDER_TEMPLATE)
    assert "Role Boundary" not in text, (
        "worker-agent.md must not reference Role Boundary — Builder's production-source "
        "authoring lane is unconstrained by this principle"
    )


# ---------------------------------------------------------------------------
# (e) the artifact/file lane is honored as distinct from the pre-existing domain-field concept
# ---------------------------------------------------------------------------

def test_domain_field_contrast_uses_dont_read_as_same_rule_phrase(repo_root):
    """The distinguishing paragraph must use the explicit 'don't read them as the same rule'
    (or equivalent) contrast phrase — not just co-mention 'domain field' in passing."""
    section = _role_boundary_section(_read(repo_root, SHARED))
    assert re.search(
        r"don.t read them as the same rule|different axis,?\s*different surface",
        section,
        re.IGNORECASE,
    ), (
        "shared.md Role Boundary must explicitly say the artifact/file lane and the domain-field "
        "ownership rule are not to be read as the same rule (e.g. 'different axis, different "
        "surface; don't read them as the same rule')"
    )


def test_domain_field_is_a_real_pre_existing_concept_not_invented_here(repo_root):
    """'domain field' must be an independently-defined concept elsewhere in shared.md (in its
    own Agent Context Flow section) — proving the Role Boundary section is pointing at a real,
    pre-existing rule rather than fabricating both sides of the contrast in one place."""
    full_text = _read(repo_root, SHARED)
    assert re.search(r"^##\s+Agent Context Flow", full_text, re.MULTILINE), (
        "shared.md must have its own 'Agent Context Flow' section — the domain-field ownership "
        "rule the Role Boundary section distinguishes itself from"
    )
    section = _role_boundary_section(full_text)
    outside_section = full_text.replace(section, "", 1)
    assert re.search(r"own domain field", outside_section, re.IGNORECASE), (
        "'domain field' must be defined/used OUTSIDE the Role Boundary section too (in Agent "
        "Context Flow) — otherwise the distinction is fabricated only inside the new section"
    )


# ---------------------------------------------------------------------------
# (f) non-vacuous self-tests for this file's own helpers
# ---------------------------------------------------------------------------

def test_section_extractor_stops_at_next_heading_not_end_of_file():
    """A differently-shaped planted case than the Builder's self-test: the section must stop
    at the NEXT heading even when there is trailing content after it, and must not swallow
    that trailing content."""
    planted = (
        "## Before\nirrelevant\n\n"
        "## Role Boundary\n\nAxis-A and Axis-B live here.\n\n"
        "## After\nthis must not leak into the extracted section\n"
    )
    section = _role_boundary_section(planted)
    assert "Axis-A and Axis-B live here." in section
    assert "must not leak" not in section


def test_individual_template_set_matches_the_three_required_templates():
    """Sanity check: the three individually-tested templates are exactly Ranger/Shield/
    Inspector (test-runner/tdd-tester/code-review-agent) — no template silently dropped or
    swapped between the per-template test functions above."""
    individually_tested = {RANGER_TEMPLATE, SHIELD_TEMPLATE, INSPECTOR_TEMPLATE}
    assert individually_tested == {
        "skills/squad/templates/test-runner.md",
        "skills/squad/templates/tdd-tester.md",
        "skills/squad/templates/code-review-agent.md",
    }
    assert len(individually_tested) == 3
