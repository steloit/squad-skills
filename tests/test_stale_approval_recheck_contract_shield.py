"""Gap-coverage tests for the stale-approval recheck contract.

Companion to ``test_stale_approval_recheck_contract.py`` — covers gaps rather
than duplicating it. Post-re-architecture, both seams (the advance-time capture
and the finalize-time recheck) call the SAME engine primitive
(``pipeline.py::_tree_hash``), so the old Seam-A/Seam-B bash-duplication checks
(temp-index form, ``git add -A``, mktemp/rm ordering, post-use cleanup in each
seam) are structurally obsolete: there is one primitive and it cannot drift
between seams. What replaces them:

(shared primitive)  cmd_advance and cmd_finalize both call ``_tree_hash()`` —
                    asserted at source level so a future fork of the primitive
                    per-seam is caught.
(threat model)      an untracked-file-only change after approval (the Ranger
                    threat) is detected by the finalize recheck end-to-end.
(no new status)     the stale branch introduces no new pipeline column/status —
                    the engine's transition table only ever yields the
                    canonical statuses, and no `stale`-named status exists.
(reject loop)       ``changes_requested`` at impl_review and ``fail`` at test
                    both route back to ``impl`` — the EXISTING reject loop.
(re-snapshot)       after a send-back, the re-approved impl_review→test advance
                    captures a FRESH approval_tree (the new tree, not the old).
(x-ref trigger)     test-runner.md names the working-tree CHANGE as the re-fire
                    trigger, not just the gate in the abstract.

Deleted (structurally obsolete): the markdown section-extractor self-tests —
no markdown section extraction remains in this suite.

Hermetic: ``_req`` stubbed, git in tmp_path repos, no network.
"""
import inspect
import json
import re
import subprocess
from types import SimpleNamespace

TEST_RUNNER = "skills/squad/templates/test-runner.md"


def _stub_req(monkeypatch, pipeline_mod, handler=None):
    calls = []

    def fake_req(method, path, body=None):
        calls.append((method, path, body))
        if handler:
            return handler(method, path, body)
        return 0, {}

    monkeypatch.setattr(pipeline_mod, "_req", fake_req)
    return calls


def _repo_with_commit(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=repo, check=True)
    subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=repo, check=True)
    (repo / "src.txt").write_text("v1\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True,
                   capture_output=True)
    return repo


def _advance_args(**kw):
    base = dict(id="7", human_reject=False, reason=None, cid=None, force=False)
    base.update(kw)
    return SimpleNamespace(**base)


# ---------------------------------------------------------------------------
# (shared primitive) both seams use the ONE _tree_hash primitive
# ---------------------------------------------------------------------------

def test_advance_and_finalize_share_the_one_tree_hash_primitive(pipeline_mod):
    """Capture (cmd_advance) and recheck (cmd_finalize) must both call
    ``_tree_hash()`` — one primitive, so the two seams cannot drift apart the
    way the old duplicated bash blocks could."""
    assert "_tree_hash()" in inspect.getsource(pipeline_mod.cmd_advance), (
        "cmd_advance must capture the approval snapshot via _tree_hash()"
    )
    assert "_tree_hash()" in inspect.getsource(pipeline_mod.cmd_finalize), (
        "cmd_finalize must recheck via the same _tree_hash() primitive"
    )


# ---------------------------------------------------------------------------
# (threat model) untracked-file-only change is detected at the recheck seam
# ---------------------------------------------------------------------------

def test_finalize_stale_detects_untracked_only_change(pipeline_mod, tmp_path, monkeypatch, capsys):
    """The primary threat model: Ranger adds a NEW (untracked) file after the
    Inspector approval. The finalize recheck must flag it stale end-to-end."""
    repo = _repo_with_commit(tmp_path)
    monkeypatch.chdir(repo)
    approval = pipeline_mod._tree_hash()
    (repo / "ranger-added.txt").write_text("post-approval file\n")

    def handler(method, path, body):
        if method == "GET":
            return 0, {"id": 7, "title": "t", "level": 3, "status": "test"}
        return 0, {"success": True}

    calls = _stub_req(monkeypatch, pipeline_mod, handler)
    pipeline_mod.cmd_finalize(SimpleNamespace(id="7", approval_tree=approval))

    out = json.loads(capsys.readouterr().out)
    assert out.get("stale_approval") is True, (
        "an untracked-file-only change after approval must be flagged stale"
    )
    assert not [c for c in calls if c[0] in ("PATCH", "POST")], (
        "no move / no commit event may be issued on a stale approval"
    )


# ---------------------------------------------------------------------------
# (no new status) the stale branch reuses the existing pipeline, no new column
# ---------------------------------------------------------------------------

_CANONICAL = {"todo", "plan", "plan_review", "impl", "impl_review", "test",
              "done", "cancelled"}


def test_engine_transition_table_yields_only_canonical_statuses(pipeline_mod):
    seen = set()
    for status in ("todo", "plan", "plan_review", "impl", "impl_review", "test"):
        for level in (1, 2, 3):
            for verdict in (None, "approved", "changes_requested", "pass", "fail"):
                nxt = pipeline_mod._next_status(status, level, verdict)
                if nxt is not None:
                    seen.add(nxt)
    assert seen <= _CANONICAL, (
        f"_next_status must only ever yield canonical statuses, got {seen - _CANONICAL}"
    )


def test_no_stale_named_status_exists_in_the_engine(pipeline_mod):
    src = inspect.getsource(pipeline_mod)
    assert "stale_review" not in src, (
        "the stale branch must reuse the existing impl_review gate, not a new status"
    )
    assert set(pipeline_mod.STATUS_AGENT) <= _CANONICAL


# ---------------------------------------------------------------------------
# (reject loop) changes_requested / fail route back to impl — the EXISTING loop
# ---------------------------------------------------------------------------

def test_stale_rereview_changes_requested_routes_to_impl(pipeline_mod):
    assert pipeline_mod._next_status("impl_review", 3, "changes_requested") == "impl", (
        "a changes_requested re-review must fire the EXISTING impl_review→impl reject loop"
    )
    assert pipeline_mod._next_status("impl_review", 2, "changes_requested") == "impl"


def test_test_fail_routes_to_impl(pipeline_mod):
    assert pipeline_mod._next_status("test", 3, "fail") == "impl", (
        "a test failure must fire the EXISTING test→impl reject loop"
    )


# ---------------------------------------------------------------------------
# (re-snapshot) re-approval captures a FRESH approval_tree
# ---------------------------------------------------------------------------

def test_reapproval_recaptures_fresh_snapshot(pipeline_mod, tmp_path, monkeypatch, capsys):
    """After a stale send-back the tree has changed; the re-approved
    impl_review→test advance must return the NEW tree hash, never the old."""
    repo = _repo_with_commit(tmp_path)
    monkeypatch.chdir(repo)
    monkeypatch.setattr(pipeline_mod, "_emit_steering", lambda *a, **k: None)

    def handler(method, path, body):
        if method == "GET":
            return 0, {"status": "impl_review", "level": 3, "version": 4,
                       "impl_review_count": 2, "last_review_status": "approved"}
        return 0, {"success": True}

    _stub_req(monkeypatch, pipeline_mod, handler)
    pipeline_mod.cmd_advance(_advance_args())
    first = json.loads(capsys.readouterr().out)["approval_tree"]

    (repo / "src.txt").write_text("reworked after send-back\n")
    pipeline_mod.cmd_advance(_advance_args())
    second = json.loads(capsys.readouterr().out)["approval_tree"]

    assert second != first, "the re-approval snapshot must be FRESH (new tree)"
    assert second == pipeline_mod._tree_hash()


# ---------------------------------------------------------------------------
# (x-ref trigger) test-runner.md names the tree CHANGE as the trigger
# ---------------------------------------------------------------------------

def test_test_runner_cross_ref_mentions_tree_change(repo_root):
    """The test-runner.md cross-reference must say a working-tree change (or
    equivalent tree modification) triggers the impl_review re-fire — Ranger
    needs the condition, not just the effect."""
    text = (repo_root / TEST_RUNNER).read_text()
    assert re.search(
        r"modif(?:y|ies|ied|ication)|change[sd]?.*(?:tree|working)|tree.*change[sd]?|"
        r"working.tree|working tree",
        text, re.IGNORECASE,
    ), (
        "test-runner.md must mention a working-tree change / modification as the "
        "trigger for re-firing the impl_review gate"
    )
