"""Contract guards for the spec-vs-description precedence rule.

The contract survived the skills-efficiency re-architecture but the mechanism
moved: the canonical rule is now the "Spec precedence" ground rule in
``skills/squad/templates/_shared.md``, INJECTED into every pipeline agent
prompt by ``pipeline.py::_render`` (``<shared_rules>``), and the spec payload
itself is rendered deterministically by ``pipeline.py::_spec_md`` as the
``## Refined Spec`` block the rule keys on. Ranger's non-applicability is now
structural: ``cmd_dispatch`` projects neither ``spec`` nor ``description`` for
Ranger and renders an empty spec.

Load-bearing properties:

(a) _shared.md authors the rule with both branches — the spec is authoritative
    when a ``## Refined Spec`` section is present (the description may PREDATE
    it; on conflict follow the spec), and with NO spec the Original Request is
    authoritative (the rule never tells agents to ignore the description).
(b) every pipeline template injects ``<shared_rules>``, so the rule reaches
    every rendered prompt (verified behaviorally via _render).
(c) _spec_md renders the Refiner spec JSON as the ``## Refined Spec`` markdown
    block (goal / requirements / Q&A, unanswered-safe) and renders nothing for
    a null spec — so the rule's presence trigger is exactly the spec's.
(d) Ranger consumes neither the spec nor the description: the engine's field
    projection excludes both, and the template carries neither placeholder.
(e) the authored rule carries no board id.

Deleted from the old suite (structurally obsolete):
- shared.md "### Spec Precedence" section assertions (no-op-branch wording,
  "never ignore it" phrasing, "authoritative source of intent" body) and the
  squad-run/SKILL.md dispatch-seam prose — the prose was intentionally
  compressed into the _shared.md rule and the rendering moved into the engine;
  the surviving branches are asserted against the new rule text and the
  injected prompts.

Hermetic: reads committed skill files + renders templates locally; no network.
"""
import re

SHARED_RULES = "skills/squad/templates/_shared.md"
TEMPLATES = [
    "skills/squad/templates/plan-agent.md",
    "skills/squad/templates/review-agent.md",
    "skills/squad/templates/worker-agent.md",
    "skills/squad/templates/tdd-tester.md",
    "skills/squad/templates/code-review-agent.md",
    "skills/squad/templates/test-runner.md",
]
TEST_RUNNER = "skills/squad/templates/test-runner.md"

NO_SPEC_BRANCH = "With no spec, the Original Request is authoritative"


def _read(repo_root, rel):
    return (repo_root / rel).read_text(encoding="utf-8")


def _rule_line(text):
    return next((ln for ln in text.splitlines() if "Spec precedence" in ln), "")


# ---------------------------------------------------------------------------
# (a) _shared.md authors both branches
# ---------------------------------------------------------------------------

def test_shared_rules_author_spec_precedence(repo_root):
    rule = _rule_line(_read(repo_root, SHARED_RULES))
    assert rule, "_shared.md must author the Spec precedence rule"
    assert "## Refined Spec" in rule, (
        "the rule must key on the '## Refined Spec' section (the block "
        "_spec_md renders)"
    )
    assert "authoritative" in rule, (
        "the rule must declare the spec authoritative when present"
    )
    assert re.search(r"may predate", rule), (
        "the rule must label the Original Request as possibly PREDATING the spec"
    )
    assert re.search(r"on any conflict, follow the spec", rule), (
        "the rule must say: on a conflict, follow the spec"
    )


def test_shared_rules_keep_description_authoritative_without_spec(repo_root):
    """The conditional CONSTRAINT: with NO spec, the description is
    authoritative — the rule must never tell agents to ignore it."""
    rule = _rule_line(_read(repo_root, SHARED_RULES))
    assert NO_SPEC_BRANCH in rule, (
        "_shared.md must carry the no-spec branch: with no spec the Original "
        "Request is authoritative"
    )


def test_shared_rules_carry_no_board_id(repo_root):
    assert not re.search(r"SQD-\d+", _read(repo_root, SHARED_RULES)), (
        "_shared.md must not embed a board id (instruction-only)"
    )


# ---------------------------------------------------------------------------
# (b) the rule reaches every rendered prompt via <shared_rules>
# ---------------------------------------------------------------------------

def test_all_templates_carry_shared_rules_placeholder(repo_root):
    for rel in TEMPLATES:
        assert "<shared_rules>" in _read(repo_root, rel), (
            f"{rel} must inject <shared_rules> so the precedence rule reaches "
            "its rendered prompt"
        )


def test_rendered_prompt_carries_both_branches(pipeline_mod, monkeypatch):
    monkeypatch.setenv("SQUAD_MODEL_PROVIDER", "claude")
    rendered = pipeline_mod._render("plan-agent.md", {})
    assert "Spec precedence" in rendered
    assert "on any conflict, follow the spec" in rendered
    assert NO_SPEC_BRANCH in rendered, (
        "an agent reading only its own rendered prompt must receive the "
        "no-spec branch"
    )
    assert "<shared_rules>" not in rendered


# ---------------------------------------------------------------------------
# (c) _spec_md renders the '## Refined Spec' block the rule keys on
# ---------------------------------------------------------------------------

def test_spec_md_renders_refined_spec_block(pipeline_mod):
    spec = {
        "goal": "Ship the widget",
        "requirements": ["req one", "req two"],
        "qa": [
            {"question": "Scope?", "answer": "Only the widget"},
            {"question": "Deadline?", "answer": None},
        ],
    }
    md = pipeline_mod._spec_md(spec)
    assert md.startswith("## Refined Spec"), (
        "_spec_md must render the '## Refined Spec' heading — the exact marker "
        "the precedence rule keys on"
    )
    assert "**Goal:** Ship the widget" in md
    assert "- req one" in md and "- req two" in md
    assert "Q: Scope?" in md and "A: Only the widget" in md
    assert "(unanswered)" in md, "an unanswered Q&A item must render safely"


def test_spec_md_renders_nothing_for_null_spec(pipeline_mod):
    """No spec → no '## Refined Spec' block → the description stays
    authoritative per the rule's no-spec branch."""
    assert pipeline_mod._spec_md(None) == ""
    assert pipeline_mod._spec_md({}) == ""


# ---------------------------------------------------------------------------
# (d) Ranger consumes neither the spec nor the description (structural)
# ---------------------------------------------------------------------------

def test_ranger_projection_excludes_spec_and_description(pipeline_mod):
    fields = pipeline_mod.AGENT_FIELDS["Ranger"].split(",")
    assert "spec" not in fields and "description" not in fields, (
        "Ranger's field projection must exclude spec and description — the "
        "precedence rule is structurally non-applicable to the test runner"
    )


def test_test_runner_template_has_no_spec_or_description_placeholder(repo_root):
    text = _read(repo_root, TEST_RUNNER)
    assert "<spec>" not in text and "<description>" not in text, (
        "test-runner.md must consume neither the spec nor the description"
    )


def test_spec_consuming_templates_carry_the_spec_placeholder(repo_root):
    """The five spec-consuming templates must actually carry <spec>, so the
    injected rule has an object to act on."""
    for rel in TEMPLATES:
        if rel == TEST_RUNNER:
            continue
        text = _read(repo_root, rel)
        assert "<spec>" in text and "<description>" in text, (
            f"{rel} must consume both the spec and the Original Request"
        )
