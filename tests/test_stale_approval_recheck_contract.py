"""Contract guards for the stale-approval recheck.

The contract survived the skills-efficiency re-architecture but the mechanism
moved out of squad-run/SKILL.md prose into the engine
(``skills/squad/scripts/pipeline.py``):

- the whole-tree content snapshot is ``_tree_hash()`` (throwaway temp-index +
  ``git write-tree``; tracked + untracked via ``git add -A``; non-destructive);
- Seam A (capture): ``cmd_advance`` returns ``approval_tree`` ONLY on the L3
  ``impl_review → test`` move (Inspector approved);
- Seam B (recheck): ``cmd_finalize --approval-tree <sha>`` re-hashes the tree
  BEFORE the done PATCH; a mismatch prints ``stale_approval: true`` and issues
  NO move — the orchestrator re-enters the loop at the EXISTING impl_review
  gate (squad-run/SKILL.md documents the re-entry).

Also guarded: the primitive source still uses the temp-index/write-tree form
(never ``git stash create``, which drops untracked files); the SKILL.md loop
instructions still route the stale branch through impl_review; test-runner.md
still carries the orchestrator-backstop cross-reference; no board id ships.

Deleted from the old suite (structurally obsolete):
- All assertions on the removed SKILL.md bash blocks (APPROVAL_TREE=/
  PRECOMMIT_TREE=/mktemp ordering/LEVEL guards) — that bash no longer exists;
  the same properties are unit-tested against ``_tree_hash``/``cmd_advance``/
  ``cmd_finalize`` directly.
- The markdown section-extractor self-tests (no markdown extraction remains).

Hermetic: ``_req`` is always stubbed (no network); git operations run in
tmp_path repos.
"""
import inspect
import json
import re
import subprocess
from types import SimpleNamespace

SKILL = "skills/squad-run/SKILL.md"
TEST_RUNNER = "skills/squad/templates/test-runner.md"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _stub_req(monkeypatch, pipeline_mod, handler=None):
    calls = []

    def fake_req(method, path, body=None):
        calls.append((method, path, body))
        if handler:
            return handler(method, path, body)
        return 0, {}

    monkeypatch.setattr(pipeline_mod, "_req", fake_req)
    return calls


def _init_repo(path):
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=path, check=True)
    subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=path, check=True)


def _commit_all(path, msg="init"):
    subprocess.run(["git", "add", "-A"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-q", "-m", msg], cwd=path, check=True, capture_output=True)


def _repo_with_commit(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    (repo / "src.txt").write_text("v1\n")
    _commit_all(repo)
    return repo


# ---------------------------------------------------------------------------
# the snapshot primitive: _tree_hash
# ---------------------------------------------------------------------------

def test_tree_hash_is_deterministic(pipeline_mod, tmp_path, monkeypatch):
    repo = _repo_with_commit(tmp_path)
    monkeypatch.chdir(repo)
    assert pipeline_mod._tree_hash() == pipeline_mod._tree_hash(), (
        "the same working-tree state must always hash to the same value"
    )


def test_tree_hash_changes_on_content_change(pipeline_mod, tmp_path, monkeypatch):
    repo = _repo_with_commit(tmp_path)
    monkeypatch.chdir(repo)
    before = pipeline_mod._tree_hash()
    (repo / "src.txt").write_text("v2 — changed after approval\n")
    assert pipeline_mod._tree_hash() != before, (
        "a content change must change the tree hash (detection is content "
        "equality, not a filename heuristic)"
    )


def test_tree_hash_includes_untracked_files(pipeline_mod, tmp_path, monkeypatch):
    """A NEW untracked file (the Ranger threat model) must change the hash —
    the reason `git stash create` (which drops untracked files) is forbidden."""
    repo = _repo_with_commit(tmp_path)
    monkeypatch.chdir(repo)
    before = pipeline_mod._tree_hash()
    (repo / "sneaky-new-file.txt").write_text("added post-approval\n")
    assert pipeline_mod._tree_hash() != before, (
        "an untracked file must be part of the content hash"
    )


def test_tree_hash_is_nondestructive(pipeline_mod, tmp_path, monkeypatch):
    """The snapshot must not mutate the real index, working tree, or HEAD."""
    repo = _repo_with_commit(tmp_path)
    (repo / "dirty.txt").write_text("uncommitted\n")
    monkeypatch.chdir(repo)

    def _state():
        status = subprocess.run(["git", "status", "--porcelain"], cwd=repo,
                                capture_output=True, text=True).stdout
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo,
                              capture_output=True, text=True).stdout
        return status, head

    before = _state()
    pipeline_mod._tree_hash()
    assert _state() == before, (
        "_tree_hash must be read-only: no staging, no commit, no tree mutation"
    )


def test_tree_hash_primitive_is_temp_index_write_tree_not_stash(pipeline_mod):
    """The primitive must stay the throwaway temp-index / `git write-tree` form
    with `git add -A` (tracked + untracked); `git stash create` is forbidden
    anywhere in the engine (it omits untracked files)."""
    src = inspect.getsource(pipeline_mod._tree_hash)
    assert "GIT_INDEX_FILE" in src, "snapshot must use a throwaway GIT_INDEX_FILE"
    assert "write-tree" in src, "snapshot must compute the SHA via git write-tree"
    assert re.search(r'"add",\s*"-A"', src), "snapshot must stage via git add -A"
    full = inspect.getsource(pipeline_mod)
    assert "git stash" not in full and '"stash"' not in full, (
        "git stash create is forbidden (drops untracked files)"
    )


# ---------------------------------------------------------------------------
# Seam A: cmd_advance captures approval_tree only on L3 impl_review → test
# ---------------------------------------------------------------------------

def _advance_args(**kw):
    base = dict(id="7", human_reject=False, reason=None, cid=None, force=False)
    base.update(kw)
    return SimpleNamespace(**base)


def test_advance_captures_approval_tree_on_l3_impl_review_to_test(
        pipeline_mod, tmp_path, monkeypatch, capsys):
    repo = _repo_with_commit(tmp_path)
    monkeypatch.chdir(repo)
    monkeypatch.setattr(pipeline_mod, "_emit_steering", lambda *a, **k: None)

    def handler(method, path, body):
        if method == "GET":
            return 0, {"status": "impl_review", "level": 3, "version": 4,
                       "impl_review_count": 1, "last_review_status": "approved"}
        return 0, {"success": True}

    calls = _stub_req(monkeypatch, pipeline_mod, handler)
    pipeline_mod.cmd_advance(_advance_args())

    out = json.loads(capsys.readouterr().out)
    assert out["moved"] is True and out["to"] == "test"
    assert out["approval_tree"] == pipeline_mod._tree_hash(), (
        "the L3 impl_review→test move must return the approval-tree snapshot"
    )
    patches = [c for c in calls if c[0] == "PATCH"]
    assert patches and patches[0][2]["status"] == "test"


def test_advance_l2_impl_review_approved_has_no_snapshot_and_defers_to_finalize(
        pipeline_mod, monkeypatch, capsys):
    """L2 (no test column): approved impl_review → next is done → advance does
    NOT move and does NOT snapshot; finalize owns the done path."""
    monkeypatch.setattr(pipeline_mod, "_emit_steering", lambda *a, **k: None)

    def handler(method, path, body):
        if method == "GET":
            return 0, {"status": "impl_review", "level": 2, "version": 4,
                       "impl_review_count": 1, "last_review_status": "approved"}
        return 0, {"success": True}

    calls = _stub_req(monkeypatch, pipeline_mod, handler)
    pipeline_mod.cmd_advance(_advance_args())

    out = json.loads(capsys.readouterr().out)
    assert out["moved"] is False and out["action"] == "finalize"
    assert "approval_tree" not in out, "the snapshot is L3-only (L1/L2 excluded)"
    assert not [c for c in calls if c[0] == "PATCH"], (
        "advance must not issue the done move itself"
    )


def test_advance_l3_test_pass_defers_to_finalize_without_snapshot(
        pipeline_mod, monkeypatch, capsys):
    monkeypatch.setattr(pipeline_mod, "_emit_steering", lambda *a, **k: None)

    def handler(method, path, body):
        if method == "GET":
            return 0, {"status": "test", "level": 3, "version": 9,
                       "last_test_status": "pass"}
        return 0, {"success": True}

    calls = _stub_req(monkeypatch, pipeline_mod, handler)
    pipeline_mod.cmd_advance(_advance_args())

    out = json.loads(capsys.readouterr().out)
    assert out["moved"] is False and out["action"] == "finalize"
    assert "approval_tree" not in out
    assert not [c for c in calls if c[0] == "PATCH"]


# ---------------------------------------------------------------------------
# Seam B: cmd_finalize rechecks the tree BEFORE the done move
# ---------------------------------------------------------------------------

def test_finalize_stale_approval_blocks_done_move(pipeline_mod, tmp_path, monkeypatch, capsys):
    """A tree that changed after approval → stale_approval: true, NO PATCH,
    NO commit event — the approval covers only the diff as approved."""
    repo = _repo_with_commit(tmp_path)
    monkeypatch.chdir(repo)

    def handler(method, path, body):
        if method == "GET":
            return 0, {"id": 7, "title": "t", "level": 3, "status": "test"}
        return 0, {"success": True}

    calls = _stub_req(monkeypatch, pipeline_mod, handler)
    stale_hash = "0" * 40  # never the current tree
    pipeline_mod.cmd_finalize(SimpleNamespace(id="7", approval_tree=stale_hash))

    out = json.loads(capsys.readouterr().out)
    assert out["finalized"] is False and out["stale_approval"] is True
    assert "impl_review" in out["note"] and "Inspector" in out["note"], (
        "the stale branch must route back through the EXISTING impl_review gate"
    )
    assert not [c for c in calls if c[0] in ("PATCH", "POST")], (
        "a stale approval must block the done PATCH and the commit event"
    )


def test_finalize_matching_tree_moves_done_and_commits(pipeline_mod, tmp_path, monkeypatch, capsys):
    repo = _repo_with_commit(tmp_path)
    (repo / "src.txt").write_text("approved change\n")
    monkeypatch.chdir(repo)
    approval = pipeline_mod._tree_hash()

    def handler(method, path, body):
        if method == "GET":
            return 0, {"id": 7, "title": "Ship it", "level": 3, "status": "test"}
        return 0, {"success": True}

    calls = _stub_req(monkeypatch, pipeline_mod, handler)
    pipeline_mod.cmd_finalize(SimpleNamespace(id="7", approval_tree=approval))

    out = json.loads(capsys.readouterr().out)
    assert out["finalized"] is True
    patches = [c for c in calls if c[0] == "PATCH"]
    assert patches and patches[0][2] == {
        "status": "done", "current_agent": None, "actor": "Orchestrator"}
    subject = subprocess.run(["git", "log", "-1", "--format=%s"], cwd=repo,
                             capture_output=True, text=True).stdout.strip()
    assert subject == "feat: Ship it [squad #7]", (
        "finalize must commit pending changes with the feat: <title> [squad #ID] message"
    )
    posts = [c for c in calls if c[0] == "POST"]
    assert posts and posts[0][2]["message"].startswith("Committed "), (
        "finalize must record the commit activity event"
    )


# ---------------------------------------------------------------------------
# SKILL.md still routes the stale branch through the existing impl_review gate
# ---------------------------------------------------------------------------

def test_skill_documents_stale_recheck_reenters_impl_review(repo_root):
    text = (repo_root / SKILL).read_text()
    assert "stale-approval recheck" in text, (
        "SKILL.md finalize step must name the L3 stale-approval recheck"
    )
    assert re.search(r"stale_approval.*does NOT move", text, re.DOTALL), (
        "SKILL.md must state the stale branch does NOT move to done"
    )
    assert re.search(r"re-enter the loop at `?impl_review`?", text), (
        "SKILL.md must route the stale branch back through the EXISTING "
        "impl_review gate (a fresh Inspector dispatch, not a new column/status)"
    )
    assert "fresh dispatch" in text, (
        "SKILL.md must re-dispatch freshly on staleness (fresh correlation id "
        "is minted per dispatch by the engine)"
    )


def test_skill_documents_approval_tree_handoff_to_finalize(repo_root):
    text = (repo_root / SKILL).read_text()
    assert re.search(r"`approval_tree`.*save it for finalize", text), (
        "SKILL.md must instruct saving advance's approval_tree for finalize"
    )
    assert "--approval-tree" in text, (
        "SKILL.md must pass --approval-tree to finalize"
    )


# ---------------------------------------------------------------------------
# test-runner.md cross-reference + instruction-only guard
# ---------------------------------------------------------------------------

def test_test_runner_carries_backstop_cross_reference(repo_root):
    text = (repo_root / TEST_RUNNER).read_text()
    assert re.search(r"impl_review gate", text), (
        "test-runner.md must cross-reference the orchestrator's impl_review re-fire backstop"
    )
    assert re.search(r"before the done-commit", text, re.IGNORECASE), (
        "test-runner.md cross-reference must note the re-fire happens before the done-commit"
    )


def test_shipped_files_carry_no_board_id(repo_root):
    for rel in (SKILL, TEST_RUNNER, "skills/squad/scripts/pipeline.py"):
        text = (repo_root / rel).read_text()
        assert not re.search(r"SQD-\d+", text), (
            f"{rel} must not embed an SQD-<n> board id (instruction-only)"
        )
