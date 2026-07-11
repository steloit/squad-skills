"""Gap-coverage tests for the Role Boundary contract.

Companion to ``test_role_boundary_contract.py`` — covers gaps rather than
duplicating it. Post-re-architecture the rule is authored once in
``skills/squad/templates/_shared.md`` and injected into every pipeline prompt
via the ``<shared_rules>`` placeholder (``pipeline.py::_render``); the old
shared.md "## Role Boundary" section (Axis-A/Axis-B labels, domain-field
contrast, per-template pointer lines) no longer exists.

Gaps covered here:

(a) Builder's carve-out does not erase Builder's PRE-EXISTING surgical-changes
    scope discipline — worker-agent.md still carries it.
(b) The rendered prompt of EVERY pipeline agent (per-agent test nodes, for
    failure isolation) contains the injected verdict-lane rule — the review /
    verify agents get the "edit nothing they evaluate" clause in their own
    prompt, not only in a file they'd have to cross-reference.
(c) Reject routing is named per reviewing template: Critic routes back to
    Planner, Inspector routes back to Builder, Shield reports production bugs
    for the orchestrator to route back to Builder.
(d) coach.md is NOT a pipeline lane agent: it carries no <shared_rules>
    placeholder (it is dispatched via render_agent_prompt.py, outside the
    pipeline lanes) — the injection set stays exactly the six pipeline
    templates.
(e) Non-vacuity: the injection placeholder set repo-wide is exactly the six
    pipeline templates (no template silently added/dropped).

Deleted (structurally obsolete): the Axis-A/Axis-B concrete-contrast wording
tests, the "domain field"/Agent Context Flow contrast tests, and the pointer-
only per-template tests — that prose was intentionally removed; the surviving
distinction (role lane vs Squad-tool friction) is covered in the companion
file, and pointers are replaced by real injection, verified here per template.

Hermetic: reads committed skill files + renders templates locally; no network.
"""
import re

import pytest

SHARED_RULES = "skills/squad/templates/_shared.md"
COACH = "skills/squad/templates/coach.md"

PIPELINE_TEMPLATES = {
    "Planner": "plan-agent.md",
    "Critic": "review-agent.md",
    "Builder": "worker-agent.md",
    "Shield": "tdd-tester.md",
    "Inspector": "code-review-agent.md",
    "Ranger": "test-runner.md",
}

VERDICT_LANE_CLAUSE = "record a verdict and edit nothing they evaluate"


def _read(repo_root, rel):
    return (repo_root / rel).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# (a) the carve-out preserves Builder's surgical-changes scope discipline
# ---------------------------------------------------------------------------

def test_builder_keeps_surgical_scope_discipline(repo_root):
    """Builder's lane being the production source must not read as 'Builder is
    unconstrained' — the surgical-changes discipline still applies."""
    text = _read(repo_root, "skills/squad/templates/worker-agent.md")
    assert re.search(r"Surgical changes", text), (
        "worker-agent.md must keep the surgical-changes scope discipline"
    )
    assert re.search(r"Every changed line traces to the plan", text), (
        "worker-agent.md must keep the changed-line-traces-to-plan constraint"
    )


# ---------------------------------------------------------------------------
# (b) per-agent rendered-prompt injection (one test node per template)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("agent,template", sorted(PIPELINE_TEMPLATES.items()))
def test_rendered_prompt_carries_verdict_lane_clause(pipeline_mod, monkeypatch, agent, template):
    monkeypatch.setenv("SQUAD_MODEL_PROVIDER", "claude")
    rendered = pipeline_mod._render(template, {})
    assert VERDICT_LANE_CLAUSE in rendered, (
        f"{template}: {agent}'s rendered prompt must carry the injected "
        "verdict-lane clause (review/verify agents edit nothing they evaluate)"
    )
    assert "<shared_rules>" not in rendered


# ---------------------------------------------------------------------------
# (c) reject routing named per reviewing template
# ---------------------------------------------------------------------------

def test_critic_routes_back_to_planner(repo_root):
    text = _read(repo_root, "skills/squad/templates/review-agent.md")
    assert re.search(r"orchestrator routes back to Planner", text), (
        "review-agent.md must say the orchestrator routes changes_requested "
        "back to Planner (Critic never fixes the plan itself)"
    )


def test_inspector_routes_back_to_builder(repo_root):
    text = _read(repo_root, "skills/squad/templates/code-review-agent.md")
    assert re.search(r"orchestrator routes back to Builder", text), (
        "code-review-agent.md must say the orchestrator routes defects back to "
        "Builder (Inspector never fixes the code itself)"
    )


def test_shield_reports_production_bugs_for_routing(repo_root):
    text = _read(repo_root, "skills/squad/templates/tdd-tester.md")
    assert re.search(r"orchestrator routes the fix back to Builder", text), (
        "tdd-tester.md must say broken production code is reported and routed "
        "back to Builder, never fixed by Shield"
    )


# ---------------------------------------------------------------------------
# (d) coach.md is not a pipeline lane agent — no shared-rules injection
# ---------------------------------------------------------------------------

def test_coach_template_has_no_shared_rules_placeholder(repo_root):
    text = _read(repo_root, COACH)
    assert "<shared_rules>" not in text, (
        "coach.md must not inject the pipeline ground rules — the Coach is a "
        "run judge dispatched outside the pipeline lanes and already embodies "
        "the report-don't-fix rule"
    )


# ---------------------------------------------------------------------------
# (e) the injection set is exactly the six pipeline templates, repo-wide
# ---------------------------------------------------------------------------

def test_exactly_six_templates_inject_shared_rules_repo_wide(repo_root):
    templates_dir = repo_root / "skills/squad/templates"
    injecting = {
        p.name for p in sorted(templates_dir.glob("*.md"))
        if p.name != "_shared.md" and "<shared_rules>" in p.read_text(encoding="utf-8")
    }
    assert injecting == set(PIPELINE_TEMPLATES.values()), (
        "expected exactly the six pipeline templates to inject <shared_rules>; "
        f"got {sorted(injecting)}"
    )
