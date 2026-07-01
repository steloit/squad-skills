"""Gap-coverage tests for the stale-approval recheck contract (SQD-872).

These tests EXTEND ``test_stale_approval_recheck_contract.py`` (19 assertions by Builder) — added
by Shield (sonnet) in the same TDD pass.  Do NOT duplicate the Builder's 19 assertions; cover the
gaps identified during review:

(A) Seam B (Done Transition) also uses the non-destructive temp-index primitive — GIT_INDEX_FILE
    and ``git write-tree`` must appear inside the Done Transition section, not just in Seam A.

(B) Seam B also uses ``git add -A`` (tracked + untracked) — the Builder only asserts this in
    Seam A; the Seam B recheck must stage the whole tree identically.

(C) Seam B's ``mktemp + rm -f`` ordering (remove BEFORE the git read) must hold in Seam B too —
    the Builder verifies it in Seam A only, but the same corrupt-index pitfall applies at recheck.

(D) Seam A has an ``rm -f "$TMPIDX"`` AFTER ``git write-tree`` (cleanup), not just the pre-use
    removal — the Builder asserts the pre-use ordering but not the post-use cleanup.

(E) Seam B has the same post-write-tree ``rm -f "$TMPIDX"`` cleanup — must appear after the
    ``PRECOMMIT_TREE=`` assignment in Seam B as well.

(F) No new pipeline column or status string is introduced — the Seam B stale branch text must
    explicitly state it is NOT a new column/status, ruling out the introduction of e.g. a
    ``stale_review`` status.

(G) The ``changes_requested`` re-review path in Seam B routes back to ``impl`` — the EXISTING
    reject loop, not a new status — so the stale path reuses the standard impl_review→impl table.

(H) The cross-reference in test-runner.md is about a TREE CHANGE re-firing impl_review — it must
    mention that the tree (working-tree change / tree modification) triggers the re-fire, not just
    that the gate fires in the abstract.

(I) Non-vacuous self-test for Shield's own section extractor: an injected Seam B with known text
    produces a non-empty extraction, and an absent section yields empty.

Hermetic: reads committed skill files only, no network. Stdlib (``re``) only.
"""
import re

SKILL = "skills/squad-run/SKILL.md"
TEST_RUNNER = "skills/squad/templates/test-runner.md"


# ---------------------------------------------------------------------------
# helpers (mirrors Builder's helpers — no import to avoid coupling)
# ---------------------------------------------------------------------------

def _read(repo_root, rel: str) -> str:
    return (repo_root / rel).read_text(encoding="utf-8")


def _section(text: str, heading_regex: str) -> str:
    """Body from a heading up to the next same-or-higher-level heading or EOF."""
    m = re.search(
        heading_regex + r".*?\n(?:.*?(?=^#{2,6}\s)|.*\Z)",
        text,
        re.MULTILINE | re.DOTALL,
    )
    return m.group(0) if m else ""


def _approval_snapshot_section(text: str) -> str:
    return _section(text, r"^#####\s+L3 Approval Snapshot \(Inspector → test\)")


def _done_transition_section(text: str) -> str:
    return _section(text, r"^####\s+→ Done Transition\b")


# ---------------------------------------------------------------------------
# (A) Seam B: non-destructive temp-index primitive present in Done Transition
# ---------------------------------------------------------------------------

def test_seam_b_uses_git_index_file_primitive(repo_root):
    """The Done Transition recheck must use ``GIT_INDEX_FILE`` — the same throwaway temp-index
    primitive as Seam A — NOT a plain ``git diff`` or stash-based approach."""
    section = _done_transition_section(_read(repo_root, SKILL))
    assert "GIT_INDEX_FILE" in section, (
        "Done Transition must use GIT_INDEX_FILE for the non-destructive recheck primitive "
        "(same primitive as Seam A — verified in Seam B independently of Seam A)"
    )


def test_seam_b_uses_git_write_tree(repo_root):
    """The Done Transition recheck must compute the tree SHA via ``git write-tree`` — the
    primitive must be verbatim-consistent with Seam A, not a different hash mechanism."""
    section = _done_transition_section(_read(repo_root, SKILL))
    assert "git write-tree" in section, (
        "Done Transition must compute the content hash via `git write-tree` "
        "(same as the Seam A approval snapshot — verified in Seam B independently)"
    )


# ---------------------------------------------------------------------------
# (B) Seam B: git add -A stages tracked + untracked in the recheck primitive
# ---------------------------------------------------------------------------

def test_seam_b_includes_untracked_via_add_all(repo_root):
    """The Done Transition recheck must use ``git add -A`` so that a new untracked file added by
    Ranger (the primary threat model) changes the tree hash and triggers re-review."""
    section = _done_transition_section(_read(repo_root, SKILL))
    assert re.search(r"git add (-A|--all)\b", section), (
        "Done Transition must use `git add -A` in the recheck primitive so untracked files "
        "change the hash — the Builder only asserts this for Seam A; Seam B must also do it"
    )


# ---------------------------------------------------------------------------
# (C) Seam B: mktemp + rm -f ordering (remove BEFORE git reads the path)
# ---------------------------------------------------------------------------

def test_seam_b_mktemp_rm_ordering_before_use(repo_root):
    """The Done Transition recheck must pair ``TMPIDX=$(mktemp) && rm -f "$TMPIDX"`` immediately
    before the ``GIT_INDEX_FILE="$TMPIDX" git add`` use.

    The same corrupt-index pitfall applies at Seam B: mktemp pre-creates an empty file that git
    rejects as a corrupt index unless removed first.  The Builder checks Seam A only."""
    section = _done_transition_section(_read(repo_root, SKILL))
    m = re.search(
        r'TMPIDX=\$\(mktemp\)\s*&&\s*rm -f "\$TMPIDX".*?'
        r'GIT_INDEX_FILE="\$TMPIDX"\s+git add',
        section,
        re.DOTALL,
    )
    assert m, (
        "Done Transition must pair `TMPIDX=$(mktemp) && rm -f \"$TMPIDX\"` immediately before "
        "`GIT_INDEX_FILE=\"$TMPIDX\" git add` — the rm must precede the git read to avoid the "
        "corrupt-index error (verified in Seam B independently of Seam A)"
    )


# ---------------------------------------------------------------------------
# (D) Seam A: rm -f cleanup AFTER git write-tree (post-use cleanup)
# ---------------------------------------------------------------------------

def test_seam_a_has_rm_cleanup_after_write_tree(repo_root):
    """Seam A must include an ``rm -f "$TMPIDX"`` AFTER the ``APPROVAL_TREE=$(… git write-tree)``
    assignment — the throwaway index must be cleaned up after use, not just removed before use.

    The Builder's ``test_snapshot_mktemp_rm_ordering_before_use`` checks that rm precedes the
    git read; this test checks the post-read cleanup is also present."""
    section = _approval_snapshot_section(_read(repo_root, SKILL))
    # Locate write-tree, then assert rm -f follows it
    approval_assign = section.find("APPROVAL_TREE=")
    assert approval_assign != -1, "APPROVAL_TREE= not found in Seam A"
    rm_after = re.search(r'rm -f "\$TMPIDX"', section[approval_assign:])
    assert rm_after, (
        "Seam A must have `rm -f \"$TMPIDX\"` AFTER the `APPROVAL_TREE=$(…git write-tree)` "
        "assignment — the throwaway index must be cleaned up after use"
    )


# ---------------------------------------------------------------------------
# (E) Seam B: rm -f cleanup AFTER git write-tree (post-use cleanup)
# ---------------------------------------------------------------------------

def test_seam_b_has_rm_cleanup_after_write_tree(repo_root):
    """Seam B must include an ``rm -f "$TMPIDX"`` AFTER the ``PRECOMMIT_TREE=$(… git write-tree)``
    assignment — the same post-use cleanup requirement as Seam A."""
    section = _done_transition_section(_read(repo_root, SKILL))
    precommit_assign = section.find("PRECOMMIT_TREE=")
    assert precommit_assign != -1, "PRECOMMIT_TREE= not found in Seam B (Done Transition)"
    rm_after = re.search(r'rm -f "\$TMPIDX"', section[precommit_assign:])
    assert rm_after, (
        "Done Transition must have `rm -f \"$TMPIDX\"` AFTER the `PRECOMMIT_TREE=$(…git write-tree)` "
        "assignment — the throwaway index must be cleaned up after use (same as Seam A)"
    )


# ---------------------------------------------------------------------------
# (F) No new pipeline column or status introduced — explicit in Seam B text
# ---------------------------------------------------------------------------

def test_stale_branch_does_not_introduce_new_status(repo_root):
    """The Seam B stale branch must explicitly state it is NOT a new column/status — the
    no-new-status constraint is a load-bearing requirement (REQ in the spec) and must be
    self-documenting in the instruction so agents cannot misread it as a new gate.

    The Builder tests that ``impl_review`` is re-used; this test asserts the negative statement
    is present in the text."""
    section = _done_transition_section(_read(repo_root, SKILL))
    assert re.search(r"NOT a new column/status", section), (
        "Done Transition stale branch must say 'NOT a new column/status' — the no-new-status "
        "constraint must be self-documenting (REQ: the re-review reuses the existing impl_review gate)"
    )


# ---------------------------------------------------------------------------
# (G) changes_requested path routes back to impl — the EXISTING reject loop
# ---------------------------------------------------------------------------

def test_stale_changes_requested_routes_to_impl(repo_root):
    """When the stale re-review returns ``changes_requested``, the path must route back to
    ``impl`` via the EXISTING ``impl_review → impl`` reject loop — NOT a new status.

    The Builder verifies ``impl_review_count > 3`` is respected; this test checks that
    ``changes_requested`` → ``impl`` is the explicit instruction in the text."""
    section = _done_transition_section(_read(repo_root, SKILL))
    m = re.search(
        r"changes_requested.*impl(?:_review)?\s*→\s*impl\b|"
        r"changes_requested.*impl reject loop|"
        r"changes_requested.*route back to.*impl\b",
        section, re.IGNORECASE | re.DOTALL,
    )
    assert m, (
        "Done Transition must state that a stale re-review `changes_requested` verdict fires the "
        "EXISTING `impl_review → impl` reject loop (routes back to Builder/impl) — "
        "not a new status or column"
    )


# ---------------------------------------------------------------------------
# (H) test-runner.md cross-ref mentions TREE CHANGE as the trigger
# ---------------------------------------------------------------------------

def test_test_runner_cross_ref_mentions_tree_change(repo_root):
    """The test-runner.md cross-reference must say that a working-tree change (or equivalent
    tree modification) triggers the impl_review re-fire — not just that the gate fires in the
    abstract.  This ensures Ranger understands WHY the backstop exists."""
    text = _read(repo_root, TEST_RUNNER)
    assert re.search(
        r"modif(?:y|ies|ied|ication)|change[sd]?.*(?:tree|working)|tree.*change[sd]?|"
        r"working.tree|working tree",
        text, re.IGNORECASE
    ), (
        "test-runner.md cross-reference must mention a working-tree change / tree modification "
        "as the trigger for re-firing the impl_review gate — not just 're-fires the gate' "
        "in the abstract (Ranger needs to understand the condition, not just the effect)"
    )


# ---------------------------------------------------------------------------
# (I) Non-vacuous self-test for Shield's own section extractor
# ---------------------------------------------------------------------------

def test_shield_section_extractor_self_test():
    """Shield's ``_done_transition_section`` must extract the right text from a planted snippet
    and return empty for an absent heading — confirming the helper is non-vacuous.

    This is a different self-test from the Builder's (which tests ``_approval_snapshot_section``
    and the extractor against a two-section document).  Here we verify Seam B extraction
    independently and confirm the fallback to empty is correct."""
    # Planted: a Done Transition section with known text, followed by another heading
    planted = (
        "## Pipeline\n\n"
        "#### → Done Transition (all levels)\n\n"
        "PRECOMMIT_TREE=$(git write-tree)\n"
        'if [ "$PRECOMMIT_TREE" = "$APPROVAL_TREE" ]; then\n'
        "  echo ok\n"
        "fi\n\n"
        "#### Other Section\n\n"
        "unrelated\n"
    )
    extracted = _done_transition_section(planted)
    assert "PRECOMMIT_TREE" in extracted, (
        "Shield's _done_transition_section must extract PRECOMMIT_TREE from the planted snippet"
    )
    assert "unrelated" not in extracted, (
        "Shield's _done_transition_section must NOT bleed into the next section"
    )
    assert _done_transition_section("## Pipeline\n\nno done section here\n") == "", (
        "Shield's _done_transition_section must return empty when the heading is absent"
    )
