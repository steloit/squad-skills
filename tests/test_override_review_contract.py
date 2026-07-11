"""Guards for the human gate-override write-through.

At a default-mode squad-run review gate a human may **reject** — *including after an agent
recorded `approved`*. The send-back is a durable, attributable server record: a mandatory
`reason` is required, then `/task/:id/override-review` is POSTed (record-only — appends a
superseding verdict that flips the derived `last_*_status`) BEFORE the verdict→move logic
computes the backward move. Attribution is delegation (`actor_kind=human`, stamped
`executed_by`/`on_behalf_of` server-side).

The mechanism now lives in `pipeline.py advance --human-reject` (behavioral unit tests below,
with the board stubbed) — squad-run/SKILL.md carries the gate instruction and the
no-silent-downgrade rule, and references/api.md documents the endpoint contract.

Hermetic: pipeline_mod._req is monkeypatched; no network.
"""
import re

import pytest


def _read(repo_root, rel):
    return (repo_root / rel).read_text()


# ── squad-run/SKILL.md: the gate instruction ───────────────────────────────────


def test_skill_gate_reject_requires_reason_and_uses_human_reject(repo_root):
    """The SKILL.md gate instructs: on human reject, a mandatory non-empty reason, passed to
    `advance --human-reject`."""
    text = _read(repo_root, "skills/squad-run/SKILL.md")
    assert "--human-reject" in text, "SKILL.md must route human rejects through advance --human-reject"
    assert re.search(r"mandatory[^\n]*reason|reason[^\n]*(is )?required", text, re.IGNORECASE), (
        "SKILL.md must state the reject reason is mandatory"
    )
    assert re.search(r"even after (the )?agent[^\n]*approved|including after", text, re.IGNORECASE), (
        "SKILL.md must state the human may reject even after an agent recorded approved"
    )


def test_skill_surfaces_403_never_fix_in_place(repo_root):
    """A 403 (PAT lacks the elevated task:override-review scope) is surfaced to the user,
    never silently downgraded to a fix-in-place."""
    text = _read(repo_root, "skills/squad-run/SKILL.md")
    assert "task:override-review" in text, "SKILL.md must name the elevated scope"
    assert re.search(r"fix.in.place", text, re.IGNORECASE), (
        "SKILL.md must state a 403 is surfaced, NOT downgraded to a silent fix-in-place"
    )


# ── pipeline.py advance --human-reject: behavioral contract ────────────────────


class _Args:
    def __init__(self, **kw):
        self.id = kw.get("id", "T-1")
        self.human_reject = kw.get("human_reject", False)
        self.reason = kw.get("reason")
        self.cid = kw.get("cid")
        self.force = kw.get("force", False)


def _stub(pipeline_mod, monkeypatch, task_fields):
    """Stub _req: records calls; GET returns task_fields (updated by override), POST/PATCH ok."""
    calls = []

    def fake_req(method, path, body=None):
        calls.append((method, path, body))
        if method == "GET":
            return 0, dict(task_fields)
        if method == "POST" and path.endswith("/override-review"):
            # The server flips the derived verdict for the stage.
            task_fields["last_review_status"] = "changes_requested"
            return 0, {"success": True}
        return 0, {"success": True}

    monkeypatch.setattr(pipeline_mod, "_req", fake_req)
    monkeypatch.setattr(pipeline_mod, "_emit_steering", lambda *a, **k: None)
    return calls


def test_advance_human_reject_requires_reason(pipeline_mod, monkeypatch, capsys):
    """--human-reject without --reason exits 2 and sends NOTHING."""
    calls = _stub(pipeline_mod, monkeypatch,
                  {"status": "impl_review", "level": 3, "version": 7,
                   "impl_review_count": 1, "last_review_status": "approved"})
    with pytest.raises(SystemExit) as exc:
        pipeline_mod.cmd_advance(_Args(human_reject=True, reason=None))
    assert exc.value.code == 2
    assert not [c for c in calls if c[0] in ("POST", "PATCH")], (
        "no write may be issued when the mandatory reason is missing"
    )


def test_advance_human_reject_posts_override_before_move(pipeline_mod, monkeypatch, capsys):
    """The override POST (gate + reason + expected_version) precedes the move PATCH, and the
    move is computed from the RE-READ, flipped verdict (the backward reject-loop move)."""
    calls = _stub(pipeline_mod, monkeypatch,
                  {"status": "impl_review", "level": 3, "version": 7,
                   "impl_review_count": 1, "last_review_status": "approved"})
    pipeline_mod.cmd_advance(_Args(human_reject=True, reason="stale snippet", cid="cid-1"))

    override_idx = next(i for i, c in enumerate(calls)
                        if c[0] == "POST" and c[1].endswith("/override-review"))
    body = calls[override_idx][2]
    assert body["gate"] == "impl_review"
    assert body["reason"] == "stale snippet"
    assert body["expected_version"] == 7, "the override must carry the optimistic-concurrency guard"
    assert body["correlation_id"] == "cid-1"

    move_idx = next(i for i, c in enumerate(calls) if c[0] == "PATCH")
    assert override_idx < move_idx, "the override must be recorded BEFORE the move"
    move_body = calls[move_idx][2]
    assert move_body["status"] == "impl", (
        "the move must follow the FLIPPED verdict (impl_review → impl backward move)"
    )
    assert move_body["actor"] == "Orchestrator"


def test_advance_human_reject_override_failure_aborts_without_move(pipeline_mod, monkeypatch):
    """A failed override write (e.g. 403 missing scope) aborts — no move is issued (the
    no-silent-downgrade rule: the server record is the source of truth)."""
    calls = []

    def fake_req(method, path, body=None):
        calls.append((method, path, body))
        if method == "GET":
            return 0, {"status": "impl_review", "level": 3, "version": 7,
                       "impl_review_count": 1, "last_review_status": "approved"}
        if method == "POST" and path.endswith("/override-review"):
            return 4, {"error": "FORBIDDEN"}
        return 0, {"success": True}

    monkeypatch.setattr(pipeline_mod, "_req", fake_req)
    monkeypatch.setattr(pipeline_mod, "_emit_steering", lambda *a, **k: None)
    with pytest.raises(SystemExit) as exc:
        pipeline_mod.cmd_advance(_Args(human_reject=True, reason="r"))
    assert exc.value.code == 4
    assert not [c for c in calls if c[0] == "PATCH"], (
        "a failed override must abort the gate — no move, no fix-in-place"
    )


def test_advance_human_reject_only_valid_at_review_gates(pipeline_mod, monkeypatch):
    """--human-reject outside a review gate (e.g. status impl) is a usage error."""
    _stub(pipeline_mod, monkeypatch,
          {"status": "impl", "level": 2, "version": 3, "impl_review_count": 0})
    with pytest.raises(SystemExit) as exc:
        pipeline_mod.cmd_advance(_Args(human_reject=True, reason="r"))
    assert exc.value.code == 2


# ── references/api.md: the endpoint contract doc ───────────────────────────────


def test_api_reference_documents_override(repo_root):
    """references/api.md documents /override-review: record-only, reason REQUIRED, the elevated
    scope, the flipped derived verdict → backward move, and delegation attribution."""
    text = _read(repo_root, "skills/squad/references/api.md")
    assert "override-review" in text
    assert re.search(r"record-only", text, re.IGNORECASE), (
        "the verdicts section must state these endpoints never change status"
    )
    assert re.search(r"reason REQUIRED", text), "reason must be documented as REQUIRED"
    assert "task:override-review" in text, "the elevated scope must be named"
    assert "actor_kind=human" in text, "delegation attribution must be documented"
    assert re.search(r"backward|reject-loop", text), (
        "the flipped-verdict → backward move consequence must be documented"
    )
