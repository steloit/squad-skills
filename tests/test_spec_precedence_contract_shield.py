"""Gap-coverage tests for the spec-vs-description precedence contract.

Companion to ``test_spec_precedence_contract.py`` — covers gaps rather than
duplicating it. Post-re-architecture the rule is injected from _shared.md into
every rendered prompt, and Ranger's exclusion is enforced by the engine
(``cmd_dispatch`` renders ``spec: ""`` for Ranger and projects neither field).

Gaps covered here:

(a) each of the five spec-consuming agents receives the no-spec branch in its
    OWN rendered prompt (per-agent test nodes for failure isolation) — the
    modern equivalent of the old per-template inline-clause requirement.
(d) the engine passes an EMPTY spec for Ranger end-to-end: a full
    ``cmd_dispatch`` for a task in ``test`` renders a prompt with no
    ``## Refined Spec`` block even though the rule text is injected —
    replacing the old ``SPEC_MD=""`` SKILL.md seam comment.
(f) list hygiene self-tests: the spec-consuming set is exactly the five
    non-Ranger pipeline agents.

Deleted (structurally obsolete):
- the SKILL.md "do not inject a per-prompt precedence guard" marker and the
  ``SPEC_MD=""`` seam-comment tests — prompt assembly is engine-owned now;
  the behaviors are asserted directly against cmd_dispatch/_render.
- the test-runner "does not apply / neither the spec nor the description /
  never say follow-the-spec" prose tests — the shared rules are now uniformly
  injected (test-runner's rendered prompt legitimately carries the rule text),
  and non-applicability is structural (no spec/description input), which the
  companion file asserts.
- the shared.md "never ignore it" phrasing test — the exact sentence was
  intentionally rewritten; the mandatory branch itself ("With no spec, the
  Original Request is authoritative") is asserted per rendered prompt here.

Hermetic: ``_req`` stubbed for the dispatch test; no network.
"""
import json

import pytest

TEST_RUNNER = "skills/squad/templates/test-runner.md"

SPEC_CONSUMING_TEMPLATES = {
    "Planner": "plan-agent.md",
    "Critic": "review-agent.md",
    "Builder": "worker-agent.md",
    "Shield": "tdd-tester.md",
    "Inspector": "code-review-agent.md",
}

NO_SPEC_BRANCH = "With no spec, the Original Request is authoritative"


# ---------------------------------------------------------------------------
# (a) per-agent rendered prompts carry the no-spec branch
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("agent,template", sorted(SPEC_CONSUMING_TEMPLATES.items()))
def test_rendered_prompt_carries_no_spec_branch(pipeline_mod, monkeypatch, agent, template):
    monkeypatch.setenv("SQUAD_MODEL_PROVIDER", "claude")
    rendered = pipeline_mod._render(template, {})
    assert NO_SPEC_BRANCH in rendered, (
        f"{template}: {agent}'s own rendered prompt must carry the no-spec "
        "branch — the agent must not need to cross-reference another file"
    )


# ---------------------------------------------------------------------------
# (d) the engine dispatches Ranger with an empty spec, end to end
# ---------------------------------------------------------------------------

def test_dispatch_renders_empty_spec_for_ranger(pipeline_mod, monkeypatch, capsys):
    """A full dispatch for a task in `test` must render Ranger's prompt with NO
    '## Refined Spec' block, even if the task has a spec on the board."""
    monkeypatch.setenv("SQUAD_MODEL_PROVIDER", "claude")
    monkeypatch.setattr(pipeline_mod.api, "resolve_project", lambda: "proj")

    def handler(method, path, body):
        if method == "GET" and "fields=status,level" in path:
            return 0, {"status": "test", "level": 3}
        if method == "GET" and path.startswith("/projects/"):
            return 0, {"brief": "Brief text"}
        if method == "GET":
            # Even if the board returned a spec, Ranger must not see it.
            return 0, {"title": "T", "implementation_notes": "notes",
                       "spec": {"goal": "should never render"}}
        return 0, {"success": True}

    def fake_req(method, path, body=None):
        return handler(method, path, body)

    monkeypatch.setattr(pipeline_mod, "_req", fake_req)

    from types import SimpleNamespace
    pipeline_mod.cmd_dispatch(SimpleNamespace(id="5", agent=None))

    out = capsys.readouterr().out
    meta_line, _, prompt = out.partition("-----PROMPT-----")
    meta = json.loads(meta_line.strip().splitlines()[-1])
    assert meta["agent"] == "Ranger"
    # A rendered spec payload would appear as a '## Refined Spec' HEADING line
    # (the _shared.md rule text only mentions it inline, in backticks).
    import re
    assert not re.search(r"^## Refined Spec", prompt, re.MULTILINE), (
        "Ranger's dispatched prompt must carry no spec payload — the "
        "precedence rule is structurally non-applicable to the test runner"
    )
    assert "should never render" not in prompt


# ---------------------------------------------------------------------------
# (f) list hygiene self-tests
# ---------------------------------------------------------------------------

def test_test_runner_excluded_from_spec_consuming_list():
    assert "test-runner.md" not in SPEC_CONSUMING_TEMPLATES.values(), (
        "test-runner.md must stay excluded — Ranger consumes neither the spec "
        "nor the description"
    )


def test_spec_consuming_set_is_exactly_the_five_non_ranger_agents():
    assert set(SPEC_CONSUMING_TEMPLATES) == {
        "Planner", "Critic", "Builder", "Shield", "Inspector"}
    assert len(SPEC_CONSUMING_TEMPLATES) == 5
