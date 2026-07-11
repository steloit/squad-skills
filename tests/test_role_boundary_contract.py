"""Contract guards for the Role Boundary (stay-in-your-lane / report-don't-fix) rule.

The contract survived the skills-efficiency re-architecture but the authoring
location moved: the canonical rule now lives in
``skills/squad/templates/_shared.md`` ("Role boundary" ground rule) and is
INJECTED into every pipeline agent prompt by ``pipeline.py::_render`` at the
templates' ``<shared_rules>`` placeholder. Each template additionally states
its own lane in its Identity line.

Load-bearing properties:

(a) _shared.md authors the rule: own-artifact-only; a review/verify agent
    records a verdict and edits nothing it evaluates; problems outside the lane
    go into the verdict/notes and the orchestrator routes the fix; agents never
    change task status (the orchestrator owns every move).
(b) the Squad-friction rule (report-don't-fix toward the TOOLING) stays a
    DISTINCT ground rule from the role-boundary lane (the worked repo) — both
    bullets exist separately in _shared.md.
(c) all six pipeline templates carry the ``<shared_rules>`` placeholder (so the
    rule reaches every rendered prompt), and _render actually injects it.
(d) per-template lane statements: Planner plans only; Critic/Inspector record a
    verdict and never edit what they evaluate; Shield writes test files only,
    never production source; Ranger fails and edits no files; Builder's lane IS
    the production source (the carve-out).
(e) the canonical rule body is authored once — no template inlines it.
(f) no board id ships in the authored rule.

Deleted from the old suite (structurally obsolete):
- The shared.md "## Role Boundary" section assertions (Axis-A/Axis-B labels,
  "domain field" contrast, Agent Context Flow) — that prose section was
  intentionally removed in the hub-split; the surviving distinction (role lane
  vs Squad-tool friction) is asserted against the two _shared.md bullets, and
  the injection is verified behaviorally.

Hermetic: reads committed skill files + renders templates locally; no network.
"""
import re

SHARED_RULES = "skills/squad/templates/_shared.md"

TEMPLATES = {
    "Planner": "skills/squad/templates/plan-agent.md",
    "Critic": "skills/squad/templates/review-agent.md",
    "Builder": "skills/squad/templates/worker-agent.md",
    "Shield": "skills/squad/templates/tdd-tester.md",
    "Inspector": "skills/squad/templates/code-review-agent.md",
    "Ranger": "skills/squad/templates/test-runner.md",
}

# A canonical rule-body phrase authored ONLY in _shared.md — templates must not
# inline it (they receive it via <shared_rules> injection at render time).
RULE_BODY_PHRASE = "write only your own output artifact"


def _read(repo_root, rel):
    return (repo_root / rel).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# (a) _shared.md authors the rule with every clause
# ---------------------------------------------------------------------------

def test_shared_rules_author_role_boundary(repo_root):
    text = _read(repo_root, SHARED_RULES)
    assert "Role boundary" in text, "_shared.md must author the Role boundary rule"
    assert RULE_BODY_PHRASE in text, (
        "_shared.md must state each agent writes only its own output artifact"
    )
    assert re.search(r"record a verdict and edit nothing they evaluate", text), (
        "_shared.md must say review/verify agents record a verdict + edit nothing"
    )
    assert re.search(r"orchestrator routes the fix", text), (
        "_shared.md must say the orchestrator routes fixes for out-of-lane problems"
    )


def test_shared_rules_forbid_agent_status_moves(repo_root):
    """Part of the lane: agents never move the card — the orchestrator owns
    every status transition."""
    text = _read(repo_root, SHARED_RULES)
    assert "Never change task status" in text, (
        "_shared.md must forbid agents changing task status"
    )
    assert re.search(r"orchestrator owns every move", text), (
        "_shared.md must state the orchestrator owns every move"
    )


# ---------------------------------------------------------------------------
# (b) role lane (worked repo) stays distinct from Squad-tool friction
# ---------------------------------------------------------------------------

def test_shared_rules_keep_friction_a_distinct_rule(repo_root):
    """The old Axis-A/Axis-B prose is gone, but the distinction survives as two
    separate ground rules: Role boundary (your lane in the worked repo) and
    Squad friction (the tooling — report, don't fix)."""
    text = _read(repo_root, SHARED_RULES)
    assert "Squad friction" in text, "_shared.md must carry the Squad-friction rule"
    friction_bullet = next(
        (ln for ln in text.splitlines() if "Squad friction" in ln), "")
    assert re.search(r"report, don.t fix", friction_bullet), (
        "the friction rule must be report-don't-fix"
    )
    assert re.search(r"not the repo you work \*?on\*?", friction_bullet), (
        "the friction rule must scope itself to the tooling, not the worked repo"
    )
    role_bullet = next(
        (ln for ln in text.splitlines() if "Role boundary" in ln), "")
    assert role_bullet and role_bullet != friction_bullet, (
        "Role boundary and Squad friction must be two distinct rules"
    )


# ---------------------------------------------------------------------------
# (c) every template injects the shared rules; _render actually injects them
# ---------------------------------------------------------------------------

def test_all_six_templates_carry_shared_rules_placeholder(repo_root):
    for name, rel in TEMPLATES.items():
        text = _read(repo_root, rel)
        assert text.count("<shared_rules>") == 1, (
            f"{rel} must carry exactly one <shared_rules> placeholder so the "
            f"Role boundary rule reaches {name}'s rendered prompt"
        )


def test_render_injects_role_boundary_into_prompts(pipeline_mod, monkeypatch):
    """Behavioral proof: a rendered agent prompt carries the canonical rule and
    no leftover placeholder."""
    monkeypatch.setenv("SQUAD_MODEL_PROVIDER", "claude")
    rendered = pipeline_mod._render("code-review-agent.md", {})
    assert RULE_BODY_PHRASE in rendered, (
        "the rendered prompt must contain the injected Role boundary rule body"
    )
    assert "<shared_rules>" not in rendered, (
        "_render must fully replace the <shared_rules> placeholder"
    )


# ---------------------------------------------------------------------------
# (d) per-template lane statements
# ---------------------------------------------------------------------------

def test_planner_lane_plan_only(repo_root):
    text = _read(repo_root, TEMPLATES["Planner"])
    assert re.search(r"do not implement or edit code", text), (
        "plan-agent.md must state Planner produces the plan only, never code"
    )


def test_critic_lane_verdict_only_edits_nothing(repo_root):
    text = _read(repo_root, TEMPLATES["Critic"])
    assert re.search(r"never edit the plan or the code", text), (
        "review-agent.md must state Critic records a verdict and edits nothing "
        "it evaluates"
    )


def test_inspector_lane_verdict_only_edits_nothing(repo_root):
    text = _read(repo_root, TEMPLATES["Inspector"])
    assert re.search(r"never edit the code you review", text), (
        "code-review-agent.md must state Inspector never edits the code it reviews"
    )


def test_shield_lane_tests_only_never_production_source(repo_root):
    text = _read(repo_root, TEMPLATES["Shield"])
    assert re.search(r"test files only", text), (
        "tdd-tester.md must scope Shield's lane to test files only"
    )
    assert re.search(r"never modify production source", text), (
        "tdd-tester.md must forbid touching production source to make a test pass"
    )


def test_ranger_lane_fail_and_edit_no_files(repo_root):
    text = _read(repo_root, TEMPLATES["Ranger"])
    assert re.search(r"edit no files", text), (
        "test-runner.md must state Ranger edits no files"
    )
    assert "fail" in text and re.search(r"Report, don.t fix", text), (
        "test-runner.md must instruct recording fail with evidence — report, don't fix"
    )


def test_builder_lane_is_production_source(repo_root):
    """The carve-out: Builder's lane IS the production source — the verdict-lane
    restriction does not apply to the authoring agent."""
    text = _read(repo_root, TEMPLATES["Builder"])
    assert re.search(r"lane:\s*the production source", text, re.IGNORECASE), (
        "worker-agent.md must name the production source as Builder's own lane"
    )


# ---------------------------------------------------------------------------
# (e) authored once — no template inlines the canonical rule body
# ---------------------------------------------------------------------------

def test_templates_do_not_inline_the_rule_body(repo_root):
    for name, rel in TEMPLATES.items():
        text = _read(repo_root, rel)
        assert RULE_BODY_PHRASE not in text, (
            f"{rel} inlines the canonical rule body — it must arrive via "
            "<shared_rules> injection, authored once in _shared.md"
        )


def test_rule_body_phrase_is_actually_authored(repo_root):
    """Non-vacuity guard for the negative test above: the phrase exists in
    _shared.md, so its absence from templates is meaningful."""
    assert RULE_BODY_PHRASE in _read(repo_root, SHARED_RULES)


# ---------------------------------------------------------------------------
# (f) instruction-only guard
# ---------------------------------------------------------------------------

def test_shared_rules_carry_no_board_id(repo_root):
    assert not re.search(r"SQD-\d+", _read(repo_root, SHARED_RULES)), (
        "_shared.md must not embed a board id (instruction-only)"
    )
