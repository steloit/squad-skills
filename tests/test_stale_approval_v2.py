"""Stale-approval recheck survives the v2 rewrite (compressed, mechanism unchanged).

A Reviewer approval covers the diff as approved; the L3 test stage runs after it,
so squad-run snapshots the whole working tree at impl_review→test (APPROVAL_TREE)
and re-compares before the done-commit. If the tree changed, the card re-enters
the EXISTING impl_review gate under the EXISTING impl_review_count circuit breaker.
"""
import re

SKILL = "skills/squad-run/SKILL.md"


def _text(repo_root):
    return (repo_root / SKILL).read_text()


def test_snapshot_captured_at_l3_impl_review_to_test(repo_root):
    text = _text(repo_root)
    assert "APPROVAL_TREE=$(GIT_INDEX_FILE=\"$TMPIDX\" git write-tree)" in text, (
        "the approval snapshot must be a git write-tree content hash"
    )
    assert 'if [ "$LEVEL" = "3" ]; then' in text, "the snapshot is L3-only"
    assert "L2 approved→done never captures" in text or "must NOT capture" in text, (
        "the L2-never-captures rule must survive"
    )


def test_precommit_recheck_compares_by_content_equality(repo_root):
    text = _text(repo_root)
    assert "PRECOMMIT_TREE=$(GIT_INDEX_FILE=\"$TMPIDX\" git write-tree)" in text, (
        "the pre-done recheck re-captures with the same primitive"
    )
    assert '[ "$PRECOMMIT_TREE" = "$APPROVAL_TREE" ]' in text, (
        "staleness is content equality of the two tree hashes"
    )
    assert re.search(r"NOT by\s+test-vs-source file classification", text), (
        "the compare is content-based, never file-classification-based"
    )


def test_stale_path_reenters_existing_gate_under_existing_breaker(repo_root):
    text = _text(repo_root)
    stale = text.split("the approval is STALE")[1][:1200]
    assert "impl_review" in stale, "a stale approval re-enters the EXISTING impl_review gate"
    assert "impl_review_count > 3" in stale, (
        "the re-review respects the existing circuit breaker (no infinite loop)"
    )
    assert "fresh" in stale.lower() and "correlation_id" in stale, (
        "the re-review is a new step occurrence with a fresh correlation id"
    )


def test_snapshot_is_non_destructive(repo_root):
    text = _text(repo_root)
    assert "temp index" in text or "throwaway" in text, (
        "the snapshot uses a throwaway index — never the real index/worktree/stash"
    )
    assert 'TMPIDX=$(mktemp) && rm -f "$TMPIDX"' in text
