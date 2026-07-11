"""Structural guards for the `cancelled` terminal-status adoption across the squad skills.

The board grew a `cancelled` terminal status: a task can be cancelled from ANY status via
`POST /api/orgs/{org}/task/{id}/cancel` (optional `cancel_reason`), it is history-preserving
and idempotent, and it is reversible only via the generalized reopen action
(`cancelled` OR `done` → `todo`).

Post skills-efficiency re-architecture the contract's homes moved (the CONTRACTS are unchanged):
  - endpoint + reopen semantics → `skills/squad/references/api.md` (`shared.md` stays the hub
    with the move-matrix mention of `/cancel` + the reopenable-terminal framing);
  - the resolved-dependency set (done AND cancelled) → `skills/squad/references/epics.md` +
    pipeline.py's TERMINAL constant;
  - squad-run's terminal refusal + readiness/nudge filters → `skills/squad/scripts/pipeline.py`
    `preflight`, unit-tested here with a stubbed `_req` (no network);
  - `/squad cancel` + `/squad reopen` → still `skills/squad/SKILL.md` (complete/cancel now share
    ONE "Terminal actions" section);
  - the /squad stats column list → `skills/squad/scripts/stats.py` `COLUMNS`.

Mirrors test_complete_adoption.py (hermetic; reads committed files / stubs board I/O).
"""
import argparse
import json
import re


def _read(repo_root, rel):
    return (repo_root / rel).read_text()


def _preflight(pipeline_mod, monkeypatch, capsys, task, rel):
    """Run pipeline.py's `preflight` against a stubbed board — read-only, no network."""
    def fake_req(method, path, body=None):
        assert method == "GET", f"preflight must be read-only, got {method} {path}"
        if path.endswith("/relationships"):
            return 0, rel
        return 0, task
    monkeypatch.setattr(pipeline_mod, "_req", fake_req)
    capsys.readouterr()
    pipeline_mod.cmd_preflight(argparse.Namespace(id=task["id"]))
    return json.loads(capsys.readouterr().out)


def _task(**over):
    base = {"id": "SQD-1", "title": "T", "status": "todo", "level": 2,
            "card_type": "task", "plan_review_count": 0, "impl_review_count": 0}
    base.update(over)
    return base


# ── schema.md: the status enum + the cancel_reason field ──────────────────────


def test_schema_lists_cancelled_status_and_cancel_reason(repo_root):
    """schema.md documents `cancelled` in the status enum, the `cancel_reason` field, and the
    terminal/reopenable/POST-cancel semantics."""
    text = _read(repo_root, "skills/squad/schema.md")
    assert "cancelled" in text, "schema.md must list `cancelled` in the status enum"
    assert "cancel_reason" in text, "schema.md must document the `cancel_reason` field"
    # Terminal + reopenable + how it is reached.
    assert "terminal" in text.lower(), "schema.md must describe `cancelled` as terminal"
    assert "/cancel" in text, "schema.md must reference the POST .../cancel endpoint"
    assert "reopen" in text.lower(), "schema.md must say cancelled is left only via reopen"


# ── shared.md hub + references/api.md: move-matrix, endpoint, reopen prose ─────


def test_shared_documents_cancelled_terminal_and_reopenable(repo_root):
    """shared.md documents cancelled as a terminal, reopenable status reachable from ANY status,
    with both done AND cancelled named as the reopenable terminals."""
    text = _read(repo_root, "skills/squad/shared.md")
    assert "cancelled" in text, "shared.md must document the cancelled status"
    # Move-matrix / semantics: reachable from any status, left only via reopen.
    assert re.search(r"any\s+status", text, re.IGNORECASE), (
        "shared.md must state cancelled is reachable from ANY status"
    )
    assert re.search(r"done\s+(?:and|or|AND|OR)\s+cancelled|done,\s*cancelled.*reopen|reopenable terminal", text, re.IGNORECASE), (
        "shared.md must name done AND cancelled as the reopenable terminal statuses"
    )


def test_shared_documents_cancel_endpoint(repo_root):
    """references/api.md's lifecycle block carries the executable `api POST /task/$ID/cancel`
    call with an optional cancel_reason."""
    text = _read(repo_root, "skills/squad/references/api.md")
    assert re.search(r"api POST /task/\$ID/cancel", text), (
        "references/api.md must document the executable `api POST /task/$ID/cancel` endpoint"
    )
    assert "cancel_reason" in text, "the cancel endpoint doc must mention cancel_reason"


def test_shared_reopen_prose_covers_done_or_cancelled(repo_root):
    """The reopen prose (now in references/api.md) must accept done OR cancelled — the old
    done-only wording stays gone from both the hub and the reference."""
    text = _read(repo_root, "skills/squad/references/api.md")
    # New wording: a done OR cancelled task can be reopened.
    assert re.search(r"done\s+(?:\*\*)?OR(?:\*\*)?\s+`?cancelled`?", text), (
        "references/api.md reopen prose must accept a done OR cancelled task"
    )
    # The old narrow claim must be gone — case-insensitively, so BOTH the prose
    # ("Only a `done` task can be reopened") AND the old 409 JSON error string
    # ("only a done task can be reopened") are forbidden from creeping back.
    for rel in ("skills/squad/shared.md", "skills/squad/references/api.md"):
        assert not re.search(
            r"only a\s+`?done`?\s+task can be reopened", _read(repo_root, rel), re.IGNORECASE
        ), f"{rel} still carries the old done-only reopen wording (prose or the 409 error string)"


def test_shared_readiness_and_nudge_treat_cancelled_as_resolved(repo_root, pipeline_mod):
    """The readiness docs treat a cancelled dep/child as resolved (alongside done): the normative
    statement lives in references/epics.md, and pipeline.py's TERMINAL set implements it."""
    text = _read(repo_root, "skills/squad/references/epics.md")
    assert re.search(r"terminal[^\n]*`done`\s+or\s+`cancelled`", text), (
        "references/epics.md must name {done, cancelled} (terminal) as the resolved dep set"
    )
    assert pipeline_mod.TERMINAL == {"done", "cancelled"}, (
        "pipeline.py TERMINAL must be exactly {done, cancelled}"
    )


# ── squad-run (pipeline.py preflight): terminal refusal + readiness/nudge ──────


def test_squad_run_refuses_cancelled_target(repo_root, pipeline_mod, monkeypatch, capsys):
    """squad-run's preflight (pipeline.py) refuses a cancelled target before dispatch
    (terminal — reopen to run)."""
    out = _preflight(pipeline_mod, monkeypatch, capsys, _task(status="cancelled"),
                     {"blocked_by": [], "children": [], "children_progress": None})
    assert out["runnable"] is False, "preflight must refuse a cancelled target"
    assert "terminal" in out["reason"], "the cancelled refusal must label it terminal"
    assert "reopen" in out["reason"].lower(), "the cancelled refusal must point at reopen"
    # And the orchestrating skill relays the reopen pointer.
    text = _read(repo_root, "skills/squad-run/SKILL.md")
    assert "reopen to run" in text, "squad-run must relay 'reopen to run' on a terminal target"


def test_squad_run_readiness_jq_excludes_cancelled(pipeline_mod, monkeypatch, capsys):
    """(Was: the BLOCKERS readiness jq.) The readiness gate — now pipeline.py preflight —
    excludes cancelled deps (resolved alongside done); a non-terminal dep still blocks."""
    out = _preflight(pipeline_mod, monkeypatch, capsys, _task(),
                     {"blocked_by": [{"id": "SQD-9", "title": "dep", "status": "cancelled"}],
                      "children": [], "children_progress": None})
    assert out["blockers"] == [] and out["runnable"] is True, (
        "a cancelled dep must be treated as resolved (not a blocker)"
    )
    out = _preflight(pipeline_mod, monkeypatch, capsys, _task(),
                     {"blocked_by": [{"id": "SQD-9", "title": "dep", "status": "impl"}],
                      "children": [], "children_progress": None})
    assert out["runnable"] is False and out["blockers"] == [{"id": "SQD-9", "status": "impl"}], (
        "a non-terminal dep must still block"
    )


def test_squad_run_nudge_jq_excludes_cancelled(pipeline_mod, monkeypatch, capsys):
    """(Was: the OPEN_KIDS sub-task nudge jq.) preflight's open_subtasks excludes cancelled
    (and done) children; a non-terminal child still counts as open."""
    children = [
        {"id": "SQD-2", "title": "kid a", "status": "cancelled"},
        {"id": "SQD-3", "title": "kid b", "status": "done"},
        {"id": "SQD-4", "title": "kid c", "status": "impl"},
    ]
    out = _preflight(pipeline_mod, monkeypatch, capsys, _task(),
                     {"blocked_by": [], "children": children,
                      "children_progress": {"done": 2, "total": 3}})
    assert out["open_subtasks"] == ["SQD-4"], (
        "open_subtasks must exclude cancelled and done children"
    )


# ── squad-batch-run: a cancelled dep is resolved (does not block a batch member) ─


def test_squad_batch_run_treats_cancelled_dep_as_resolved(repo_root):
    """squad-batch-run's `.blocked_by` prerequisite names cancelled alongside done as a resolved
    terminal — a cancelled dep no longer blocks a batch member (mirrors the squad-run readiness gate).
    This file is otherwise untouched by the cancel-adoption guards, so without this the batch-run
    edit could silently regress to a done-only prerequisite."""
    text = _read(repo_root, "skills/squad-batch-run/SKILL.md")
    assert re.search(r"\.blocked_by[^\n]*\bdone\b[^\n]*\bcancelled\b", text, re.IGNORECASE), (
        "squad-batch-run must name cancelled alongside done as a resolved dep state in the "
        "`.blocked_by` prerequisite prose"
    )


# ── squad-refine: cancelled target is a non-runnable terminal ─────────────────


def test_squad_refine_treats_cancelled_target_as_terminal(repo_root):
    """squad-refine warns (and skips the interview) on a cancelled/done terminal target and names reopen."""
    text = _read(repo_root, "skills/squad-refine/SKILL.md")
    assert "cancelled" in text, "squad-refine must handle a cancelled target"
    assert re.search(r"terminal", text, re.IGNORECASE), (
        "squad-refine must label a cancelled/done target as a non-runnable terminal"
    )
    assert "reopen" in text.lower(), (
        "squad-refine must point the user at reopen before refining a terminal target"
    )


# ── squad/SKILL.md: /squad cancel (non-interactive) + /squad reopen + steer ───


def test_squad_skill_has_non_interactive_cancel_calling_post_cancel(repo_root):
    """squad/SKILL.md has a /squad cancel command that calls POST .../cancel and is non-interactive
    (declares it, and never invokes AskUserQuestion in its section). Post-rewrite /squad cancel
    shares the 'Terminal actions' section with /squad complete."""
    text = _read(repo_root, "skills/squad/SKILL.md")
    assert "/squad cancel" in text, "squad/SKILL.md must document the /squad cancel command"
    assert re.search(r"api POST /task/\$ID/cancel", text), (
        "/squad cancel must call `api POST /task/$ID/cancel`"
    )
    # Isolate the combined complete·cancel Terminal-actions section.
    m = re.search(r"### `/squad complete.*?(?=\n### )", text, re.DOTALL)
    assert m and "/squad cancel" in m.group(0), "could not isolate the /squad cancel section"
    section = m.group(0)
    assert "non-interactive" in section.lower(), (
        "the /squad cancel section must declare itself non-interactive"
    )
    # Non-interactive = the section never invokes AskUserQuestion as a step.
    assert "AskUserQuestion" not in section, (
        "the /squad cancel section must not invoke AskUserQuestion (non-interactive)"
    )


def test_squad_skill_has_reopen_uncancel(repo_root):
    """squad/SKILL.md has a /squad reopen command (the uncancel path) calling POST .../reopen."""
    text = _read(repo_root, "skills/squad/SKILL.md")
    assert "/squad reopen" in text, "squad/SKILL.md must document the /squad reopen command"
    assert re.search(r"api POST /task/\$ID/reopen", text), (
        "/squad reopen must call `api POST /task/$ID/reopen`"
    )


def test_squad_skill_positions_cancel_preferred_over_remove(repo_root):
    """squad/SKILL.md positions cancel as preferred over the irreversible remove, and the cancel
    section (the combined Terminal-actions section) appears before the remove section."""
    text = _read(repo_root, "skills/squad/SKILL.md")
    cancel_idx = text.find("/squad cancel")
    remove_idx = text.find("### `/squad remove")
    assert cancel_idx != -1 and remove_idx != -1, "both /squad cancel and /squad remove must exist"
    assert cancel_idx < remove_idx, "/squad cancel must be documented BEFORE /squad remove"
    # The remove section steers toward cancel for won't-do / superseded work.
    assert re.search(r"prefer(?:red)?[^\n]*cancel", text, re.IGNORECASE), (
        "squad/SKILL.md must steer won't-do/superseded work to cancel over remove"
    )
    assert re.search(r"irreversible", text, re.IGNORECASE), (
        "the /squad remove steer must call DELETE irreversible"
    )


def test_squad_stats_columns_include_cancelled(repo_root, stats_mod):
    """(Was: the SKILL.md python-heredoc columns list.) /squad stats now delegates to
    scripts/stats.py; its COLUMNS list must include `cancelled` (and `done`)."""
    assert "cancelled" in stats_mod.COLUMNS, "stats.py COLUMNS must include 'cancelled'"
    assert "done" in stats_mod.COLUMNS, "stats.py COLUMNS must include 'done'"
    text = _read(repo_root, "skills/squad/SKILL.md")
    assert "stats.py" in text, "/squad stats must delegate to scripts/stats.py"


# ── fixtures: the refreshed contract carries the cancel endpoint ──────────────


def test_cancel_endpoint_in_openapi_and_consumer_contract(repo_root):
    """The refreshed snapshots carry the cancel endpoint: openapi.json has the path key and the
    consumer contract publishes POST .../cancel."""
    import json

    spec = json.loads(_read(repo_root, "tests/fixtures/openapi.json"))
    assert any("cancel" in p for p in spec["paths"]), (
        "openapi.json snapshot must include the .../cancel path (run scripts/refresh-openapi.sh)"
    )
    contract = json.loads(_read(repo_root, "tests/fixtures/consumer-contract.json"))
    assert {"method": "POST", "path": "/orgs/{}/task/{}/cancel"} in contract, (
        "consumer-contract.json must publish POST /orgs/{}/task/{}/cancel "
        "(run scripts/refresh-consumer-contract.py)"
    )
