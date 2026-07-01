"""Structural guards for the stale-approval recheck contract (SQD-872).

When the Inspector records ``approved`` at the L3 ``impl_review`` gate, the orchestrator
captures a content-hash snapshot of the whole working tree (``APPROVAL_TREE``). Before the
``test → done`` commit it re-captures the tree (``PRECOMMIT_TREE``) and compares: if the
tree changed after approval (e.g. Ranger edited source post-review), the approval is STALE
and the orchestrator re-fires the EXISTING ``impl_review`` gate before committing — closing
the gate-bypass that let a Ranger-introduced change reach commit unreviewed.

Load-bearing properties guarded here (read against the committed skill files):

(A capture)    a named ``##### L3 Approval Snapshot (Inspector → test)`` sub-section assigns
               ``APPROVAL_TREE`` at the Inspector-``approved`` impl_review→test seam.
(L3 guard)     the capture is guarded by a ``LEVEL == 3`` check (L1/L2 excluded).
(primitive)    the snapshot is the non-destructive temp-index / ``git write-tree`` form:
               ``GIT_INDEX_FILE`` AND ``git write-tree`` both appear, and the corrected
               ``mktemp`` + ``rm -f "$TMPIDX"`` ordering (remove BEFORE git reads it) is present.
(no stash)     ``git stash create`` is FORBIDDEN — it omits untracked files.
(untracked)    the capture uses ``git add -A`` so untracked files are in the hash.
(no commit)    the snapshot block does not mutate the real tree (no ``git commit`` inside it).
(compare seam) the test→done section re-captures ``PRECOMMIT_TREE`` and compares it to
               ``APPROVAL_TREE`` BEFORE the ``{"status": "done"}`` commit PATCH.
(whole-tree)   detection is content equality — NO ``grep -v '.test.'`` / ``tests/`` suffix
               heuristic in the recheck logic.
(reuse gate)   the stale branch re-fires the EXISTING impl_review gate / Inspector /
               ``impl_review_count > 3`` breaker — NOT a new column/status.
(re-snapshot)  on re-approve a FRESH approval snapshot is captured.
(principle)    a one-sentence staleness-principle note exists at the impl_review→test→done seam.
(x-ref)        test-runner.md carries the orchestrator-backstop cross-reference line.
(instruction)  the shipped SKILL.md + test-runner.md additions carry NO ``SQD-<n>`` board id.

Hermetic: reads committed skill files only, no network. Stdlib (``re``) only.
"""
import re

SKILL = "skills/squad-run/SKILL.md"
TEST_RUNNER = "skills/squad/templates/test-runner.md"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _read(repo_root, rel: str) -> str:
    return (repo_root / rel).read_text(encoding="utf-8")


def _section(text: str, heading_regex: str) -> str:
    """Body from a heading up to the next same-or-higher-level ``#`` heading or EOF.

    The heading line is consumed first (``.*\n``) so the closing lookahead does not match
    the section's own heading at offset 0. The terminator matches only real markdown
    headings (``##``..``######``) — never a single-``#`` bash comment inside a code fence.
    """
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
# (A capture) Seam A — named sub-section assigns APPROVAL_TREE
# ---------------------------------------------------------------------------

def test_approval_snapshot_subsection_exists(repo_root):
    section = _approval_snapshot_section(_read(repo_root, SKILL))
    assert section, (
        "SKILL.md must contain a '##### L3 Approval Snapshot (Inspector → test)' sub-section"
    )


def test_approval_snapshot_assigns_approval_tree(repo_root):
    section = _approval_snapshot_section(_read(repo_root, SKILL))
    assert re.search(r"APPROVAL_TREE\s*=", section), (
        "the L3 Approval Snapshot sub-section must assign APPROVAL_TREE"
    )


# ---------------------------------------------------------------------------
# (L3 guard) capture is L3-only
# ---------------------------------------------------------------------------

def test_capture_is_level_3_guarded(repo_root):
    section = _approval_snapshot_section(_read(repo_root, SKILL))
    assert re.search(r'\[\s*"\$LEVEL"\s*=\s*"3"\s*\]', section), (
        "the approval-snapshot capture must be guarded by a LEVEL == 3 check (L1/L2 excluded)"
    )


# ---------------------------------------------------------------------------
# (primitive) non-destructive temp-index / write-tree, with the corrected ordering
# ---------------------------------------------------------------------------

def test_snapshot_uses_nondestructive_primitive(repo_root):
    section = _approval_snapshot_section(_read(repo_root, SKILL))
    assert "GIT_INDEX_FILE" in section, "snapshot must use a throwaway GIT_INDEX_FILE temp index"
    assert "git write-tree" in section, "snapshot must compute a tree SHA via git write-tree"


def test_snapshot_mktemp_rm_ordering_before_use(repo_root):
    """The temp index path must be removed (`rm -f "$TMPIDX"`) AFTER mktemp and BEFORE the
    `GIT_INDEX_FILE=…git add` use — otherwise git rejects the pre-created empty file as a
    corrupt index ('index file smaller than expected')."""
    section = _approval_snapshot_section(_read(repo_root, SKILL))
    m = re.search(
        r'TMPIDX=\$\(mktemp\)\s*&&\s*rm -f "\$TMPIDX".*?'
        r'GIT_INDEX_FILE="\$TMPIDX"\s+git add',
        section,
        re.DOTALL,
    )
    assert m, (
        "snapshot must pair `TMPIDX=$(mktemp) && rm -f \"$TMPIDX\"` immediately and then use "
        "`GIT_INDEX_FILE=\"$TMPIDX\" git add` — the rm must precede the git read"
    )


def test_snapshot_does_not_mutate_real_tree(repo_root):
    """The snapshot block must not issue a real `git commit` (it is read-only)."""
    section = _approval_snapshot_section(_read(repo_root, SKILL))
    assert "git commit" not in section, (
        "the approval-snapshot block must not run `git commit` (non-destructive)"
    )


# ---------------------------------------------------------------------------
# (no stash) git stash create is FORBIDDEN
# ---------------------------------------------------------------------------

def test_snapshot_does_not_use_git_stash_create(repo_root):
    """`git stash create` omits untracked files — it would silently break the
    untracked-file EDGE and is explicitly excluded."""
    text = _read(repo_root, SKILL)
    section_a = _approval_snapshot_section(text)
    section_b = _done_transition_section(text)
    assert "git stash create" not in section_a, (
        "git stash create is forbidden in the approval-snapshot primitive (omits untracked files)"
    )
    assert "git stash create" not in section_b, (
        "git stash create is forbidden in the recheck primitive (omits untracked files)"
    )


# ---------------------------------------------------------------------------
# (untracked) git add -A captures untracked files
# ---------------------------------------------------------------------------

def test_snapshot_includes_untracked_via_add_all(repo_root):
    section = _approval_snapshot_section(_read(repo_root, SKILL))
    assert re.search(r"git add (-A|--all)\b", section), (
        "the snapshot must use `git add -A` so untracked files are in the content hash"
    )


# ---------------------------------------------------------------------------
# (compare seam) PRECOMMIT_TREE re-captured + compared BEFORE the done PATCH
# ---------------------------------------------------------------------------

def test_done_transition_recaptures_and_compares(repo_root):
    section = _done_transition_section(_read(repo_root, SKILL))
    assert re.search(r"PRECOMMIT_TREE\s*=", section), (
        "the Done Transition must re-capture PRECOMMIT_TREE before the commit"
    )
    assert re.search(r'\[\s*"\$PRECOMMIT_TREE"\s*=\s*"\$APPROVAL_TREE"\s*\]', section), (
        "the Done Transition must compare PRECOMMIT_TREE to APPROVAL_TREE"
    )


def test_compare_precedes_done_commit_patch(repo_root):
    """The compare must occur BEFORE the `{"status": "done"}` move PATCH."""
    section = _done_transition_section(_read(repo_root, SKILL))
    compare_at = section.find('"$PRECOMMIT_TREE"')
    done_at = section.find('"status": "done"')
    assert compare_at != -1, "PRECOMMIT_TREE compare not found in Done Transition"
    assert done_at != -1, '{"status": "done"} PATCH not found in Done Transition'
    assert compare_at < done_at, (
        "the stale-approval compare must precede the {status: done} commit PATCH"
    )


def test_recheck_is_level_3_and_nonempty_guarded(repo_root):
    section = _done_transition_section(_read(repo_root, SKILL))
    assert re.search(r'\[\s*"\$LEVEL"\s*=\s*"3"\s*\]', section), (
        "the recheck must be L3-guarded"
    )
    assert re.search(r'\[\s*-n\s*"\$APPROVAL_TREE"\s*\]', section), (
        "the recheck must be a no-op when APPROVAL_TREE is empty (L1/L2 path)"
    )


# ---------------------------------------------------------------------------
# (whole-tree) no test-vs-source classification heuristic
# ---------------------------------------------------------------------------

def test_recheck_has_no_test_vs_source_classification(repo_root):
    section = _done_transition_section(_read(repo_root, SKILL))
    assert "grep -v '.test.'" not in section and "grep -v \".test.\"" not in section, (
        "detection must be whole-tree content equality, NOT a test-vs-source grep heuristic"
    )
    assert not re.search(r"diff --name-only.*grep", section, re.DOTALL), (
        "detection must not classify changed files by name (whole-tree content equality only)"
    )


# ---------------------------------------------------------------------------
# (reuse gate) re-fire EXISTING impl_review gate + breaker, no new column/status
# ---------------------------------------------------------------------------

def test_stale_branch_reuses_impl_review_gate(repo_root):
    section = _done_transition_section(_read(repo_root, SKILL))
    assert "impl_review" in section, (
        "the stale branch must re-dispatch through the EXISTING impl_review gate"
    )
    assert re.search(r"impl_review_count\s*>\s*3", section), (
        "the stale branch must respect the EXISTING impl_review_count > 3 circuit breaker"
    )
    assert "Inspector" in section, "the stale branch must re-dispatch the Inspector"


def test_stale_branch_mints_fresh_correlation_id(repo_root):
    section = _done_transition_section(_read(repo_root, SKILL))
    assert re.search(r"fresh.*correlation_id", section, re.IGNORECASE), (
        "the stale re-review must mint a FRESH per-step correlation_id"
    )


# ---------------------------------------------------------------------------
# (re-snapshot) on re-approve a FRESH approval snapshot is captured
# ---------------------------------------------------------------------------

def test_reapprove_recaptures_fresh_snapshot(repo_root):
    section = _done_transition_section(_read(repo_root, SKILL))
    assert re.search(r"FRESH\s+APPROVAL_TREE", section), (
        "on re-review approved, a FRESH APPROVAL_TREE must be re-captured"
    )


# ---------------------------------------------------------------------------
# (principle) one-sentence staleness-principle note at the seam
# ---------------------------------------------------------------------------

def test_staleness_principle_documented(repo_root):
    section = _done_transition_section(_read(repo_root, SKILL))
    assert re.search(r"approval covers the diff", section, re.IGNORECASE), (
        "a staleness-principle note must state an approval covers the diff as approved"
    )
    assert re.search(r"re-review", section, re.IGNORECASE), (
        "the staleness-principle note must say a later change requires re-review"
    )


# ---------------------------------------------------------------------------
# (x-ref) test-runner.md cross-reference
# ---------------------------------------------------------------------------

def test_test_runner_carries_backstop_cross_reference(repo_root):
    text = _read(repo_root, TEST_RUNNER)
    assert re.search(r"impl_review gate", text), (
        "test-runner.md must cross-reference the orchestrator's impl_review re-fire backstop"
    )
    assert re.search(r"before the done-commit", text, re.IGNORECASE), (
        "test-runner.md cross-reference must note the re-fire happens before the done-commit"
    )


# ---------------------------------------------------------------------------
# (instruction) shipped additions carry no board id
# ---------------------------------------------------------------------------

def test_shipped_additions_carry_no_board_id(repo_root):
    for rel in (SKILL, TEST_RUNNER):
        text = _read(repo_root, rel)
        assert not re.search(r"SQD-\d+", text), (
            f"{rel} must not embed an SQD-<n> board id (instruction-only)"
        )


# ---------------------------------------------------------------------------
# self-test — keep the suite non-vacuous
# ---------------------------------------------------------------------------

def test_section_extractor_is_non_vacuous():
    planted = (
        "## X\n\n##### L3 Approval Snapshot (Inspector → test)\n\nAPPROVAL_TREE=$(...)\n\n"
        "#### → Done Transition (all levels)\n\nbody\n"
    )
    assert "APPROVAL_TREE" in _approval_snapshot_section(planted)
    assert "body" in _done_transition_section(planted)
    assert _approval_snapshot_section("## X\n\nnothing\n") == ""
