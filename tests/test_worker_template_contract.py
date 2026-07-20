"""Worker template contract: one template, three column-scoped Focus sections.

The Worker carries the task end-to-end across three dispatches (plan, impl, test);
each dispatch executes exactly one `## Focus:` section. These tests pin the lane
rules that used to live in three separate templates:
  - plan: produce the plan only, done_when discipline, no code edits
  - impl: implement AND write tests in one dispatch; commands via the
    Command Resolution ladder (never a hardcoded toolchain)
  - test: mechanical run, edit no files, record via /test-result
"""
import re

TPL = "skills/squad/templates/worker.md"


def _text(repo_root):
    return (repo_root / TPL).read_text()


def test_has_exactly_three_focus_sections(repo_root):
    sections = re.findall(r"^## Focus: (\w+)$", _text(repo_root), re.MULTILINE)
    assert sections == ["plan", "impl", "test"], f"unexpected focus sections: {sections}"


def test_identity_and_placeholders(repo_root):
    text = _text(repo_root)
    assert "You are **Worker**" in text
    assert "<MODEL_WORKER>" in text
    assert "<FOCUS>" in text
    assert "<correlation_id>" in text
    assert "> **Worker** \\`<MODEL_WORKER>\\` · <TIMESTAMP>" in text, "signature rule missing"
    assert "<review_feedback>" in text, "the merged review-feedback placeholder is missing"


def test_spec_precedence_note_present(repo_root):
    text = _text(repo_root)
    assert "Spec Precedence" in text
    assert "<spec>" in text and "<description>" in text


def test_plan_focus_owns_plan_only_and_done_when_discipline(repo_root):
    text = _text(repo_root)
    plan = text.split("## Focus: plan")[1].split("## Focus: impl")[0]
    assert "edits **no code**" in plan or "edits no code" in plan
    assert "done_when" in plan
    assert "/squad-refine" in plan, "underspecified requirements must route to /squad-refine"
    assert "Do NOT set status" in text, "status stays orchestrator-owned"


def test_impl_focus_requires_tests_and_ladder_resolved_commands(repo_root):
    text = _text(repo_root)
    impl = text.split("## Focus: impl")[1].split("## Focus: test")[0]
    assert "write tests" in impl.lower() or "write or update test code" in impl.lower(), (
        "the impl dispatch must own test authoring (the old TDD-tester lane)"
    )
    assert "Command Resolution" in impl, "commands come from the resolution ladder"
    assert "formatter" in impl, "the impl dispatch runs the project formatter before finishing"
    # Portability: tool names may appear only as examples, never as THE command.
    for hardcoded in ("pnpm test", "vitest run", "cargo test", "go test ./..."):
        assert hardcoded not in impl, f"impl focus hardcodes a toolchain: {hardcoded}"


def test_test_focus_is_record_only_and_posts_test_result(repo_root):
    text = _text(repo_root)
    test_sec = text.split("## Focus: test")[1]
    assert "edit no files" in test_sec, "the test dispatch reports, never fixes"
    assert "/test-result" in test_sec, "the verdict goes through POST /test-result"
    assert '"tester": "Worker"' in test_sec
    assert '"pass"' in test_sec and '"fail"' in test_sec.replace('`"fail"`', '"fail"'), (
        "the pass/fail verdict literals must be stated"
    )


def test_no_status_moves_anywhere(repo_root):
    """The Worker records results; the orchestrator owns every status transition."""
    text = _text(repo_root)
    assert '\\"status\\":' not in text.replace('\\"status\\": \\"pass\\"', ""), (
        "worker.md must never PATCH a status field"
    )
    assert "orchestrator advances the card" in text
