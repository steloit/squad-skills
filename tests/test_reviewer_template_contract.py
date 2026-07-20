"""Reviewer template contract: one template, two review-column Focus sections.

The Reviewer validates the Worker's output and provides feedback; it records
verdicts and never edits what it evaluates. Each dispatch executes exactly one
`## Focus:` section: plan_review → POST /plan-review, impl_review → POST /review.
"""
import re

TPL = "skills/squad/templates/reviewer.md"


def _text(repo_root):
    return (repo_root / TPL).read_text()


def test_has_exactly_two_focus_sections(repo_root):
    sections = re.findall(r"^## Focus: (\w+)$", _text(repo_root), re.MULTILINE)
    assert sections == ["plan_review", "impl_review"], f"unexpected focus sections: {sections}"


def test_identity_and_placeholders(repo_root):
    text = _text(repo_root)
    assert "You are **Reviewer**" in text
    assert "<MODEL_REVIEWER>" in text
    assert "<FOCUS>" in text
    assert "<correlation_id>" in text
    assert "> **Reviewer** \\`<MODEL_REVIEWER>\\` · <TIMESTAMP>" in text, "signature rule missing"


def test_record_only_role_boundary(repo_root):
    text = _text(repo_root)
    assert "never edit what you evaluate" in text, (
        "the Reviewer records a verdict and edits nothing — the load-bearing lane rule"
    )
    assert "Role Boundary" in text


def test_each_focus_posts_its_own_verdict_endpoint(repo_root):
    text = _text(repo_root)
    plan_review = text.split("## Focus: plan_review")[1].split("## Focus: impl_review")[0]
    impl_review = text.split("## Focus: impl_review")[1]
    assert "/plan-review" in plan_review and "/review" not in plan_review.replace("/plan-review", ""), (
        "plan_review focus records via POST /plan-review only"
    )
    assert re.search(r"POST /task/<ID>/review\b", impl_review), (
        "impl_review focus records via POST /review"
    )
    assert "/plan-review" not in impl_review, (
        "impl_review focus must not reference the plan-review endpoint"
    )


def test_verdict_literals_and_rubrics(repo_root):
    text = _text(repo_root)
    assert '`"approved"` or `"changes_requested"`' in text
    # The two rubrics survive the merge: 3 plan dimensions, 7 impl dimensions.
    for dim in ("Clarity", "Done-When Quality", "Reversibility"):
        assert dim in text, f"plan_review rubric missing dimension {dim}"
    for dim in ("Code Quality", "Error Handling", "Type Safety", "Security",
                "Performance", "Test Coverage", "Completion"):
        assert dim in text, f"impl_review rubric missing dimension {dim}"


def test_no_status_moves(repo_root):
    text = _text(repo_root)
    assert "You do not move the card" in text
    assert "PATCH /task" not in text, "reviewer.md must not PATCH the task at all"
