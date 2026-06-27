"""Structural guards for the `cancelled` terminal-status adoption across the squad skills.

The board grew a `cancelled` terminal status: a task can be cancelled from ANY status via
`POST /api/orgs/{org}/task/{id}/cancel` (optional `cancel_reason`), it is history-preserving
and idempotent, and it is reversible only via the generalized reopen action
(`cancelled` OR `done` → `todo`). These deterministic grep invariants keep the skills aligned
with that status so the adoption can't silently regress — a re-narrowed reopen, a dispatch that
forgets `cancelled` is terminal, or a readiness/nudge filter that treats a cancelled dep/child as
still active.

Mirrors the style of test_relationship_adoption.py (hermetic; reads the committed skill files).
"""
import re


def _read(repo_root, rel):
    return (repo_root / rel).read_text()


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


# ── shared.md: move-matrix, endpoint, reopen prose ────────────────────────────


def test_shared_documents_cancelled_terminal_and_reopenable(repo_root):
    """shared.md documents cancelled as a terminal, reopenable status reachable from ANY status,
    with both done AND cancelled named as the reopenable terminals."""
    text = _read(repo_root, "skills/squad/shared.md")
    assert "cancelled" in text, "shared.md must document the cancelled status"
    # Move-matrix / semantics: reachable from any status, left only via reopen.
    assert re.search(r"any\s+status", text, re.IGNORECASE), (
        "shared.md must state cancelled is reachable from ANY status"
    )
    assert re.search(r"done\s+(?:and|or|AND|OR)\s+cancelled|cancelled.*reopenable|reopenable terminal", text, re.IGNORECASE), (
        "shared.md must name done AND cancelled as the reopenable terminal statuses"
    )


def test_shared_documents_cancel_endpoint(repo_root):
    """shared.md's API Endpoints block adds an executable `api POST /task/$ID/cancel` call with
    an optional cancel_reason."""
    text = _read(repo_root, "skills/squad/shared.md")
    assert re.search(r"api POST /task/\$ID/cancel", text), (
        "shared.md must document the executable `api POST /task/$ID/cancel` endpoint"
    )
    assert "cancel_reason" in text, "shared.md cancel endpoint must mention cancel_reason"


def test_shared_reopen_prose_covers_done_or_cancelled(repo_root):
    """The reopen prose must accept done OR cancelled (the old done-only wording is gone)."""
    text = _read(repo_root, "skills/squad/shared.md")
    # New wording: a done OR cancelled task can be reopened.
    assert re.search(r"done\s+(?:\*\*)?OR(?:\*\*)?\s+`?cancelled`?", text), (
        "shared.md reopen prose must accept a done OR cancelled task"
    )
    # The old narrow claim must be gone — case-insensitively, so BOTH the prose
    # ("Only a `done` task can be reopened") AND the old 409 JSON error string
    # ("only a done task can be reopened") are forbidden from creeping back.
    assert "Only a `done` task can be reopened" not in text, (
        "shared.md still carries the old 'Only a done task can be reopened' wording"
    )
    assert not re.search(r"only a\s+`?done`?\s+task can be reopened", text, re.IGNORECASE), (
        "shared.md still carries the old done-only reopen wording (prose or the 409 error string)"
    )


def test_shared_readiness_and_nudge_treat_cancelled_as_resolved(repo_root):
    """shared.md's readiness gate, IN PROGRESS rule, and sub-task nudge treat a cancelled dep/child
    as resolved (excluded alongside done)."""
    text = _read(repo_root, "skills/squad/shared.md")
    # Readiness gate names {done, cancelled} as the resolved set.
    assert re.search(r"\{done,\s*cancelled\}", text), (
        "shared.md must use {done, cancelled} as the resolved status set in readiness/dep prose"
    )


# ── squad-run: terminal refusal + readiness/nudge jq exclusions ───────────────


def test_squad_run_refuses_cancelled_target(repo_root):
    """squad-run refuses a cancelled target before dispatch (terminal — reopen to run)."""
    text = _read(repo_root, "skills/squad-run/SKILL.md")
    assert re.search(r'STATUS"\s*=\s*"cancelled"', text), (
        "squad-run must branch on STATUS == cancelled before dispatch"
    )
    assert "cancelled (terminal)" in text, (
        "squad-run cancelled refusal must label it terminal"
    )
    assert "reopen to run" in text, (
        "squad-run cancelled refusal must point at reopen"
    )


def test_squad_run_readiness_jq_excludes_cancelled(repo_root):
    """squad-run's BLOCKERS readiness jq excludes cancelled deps (resolved alongside done)."""
    text = _read(repo_root, "skills/squad-run/SKILL.md")
    assert re.search(
        r'\.blocked_by\[\]\?[^\n]*select\(\.status\s*!=\s*"done"\s+and\s+\.status\s*!=\s*"cancelled"\)',
        text,
    ), "squad-run BLOCKERS jq must exclude both done and cancelled deps"


def test_squad_run_nudge_jq_excludes_cancelled(repo_root):
    """squad-run's OPEN_KIDS sub-task nudge jq excludes cancelled children."""
    text = _read(repo_root, "skills/squad-run/SKILL.md")
    assert re.search(
        r'OPEN_KIDS=[^\n]*select\(\.status\s*!=\s*"done"\s+and\s+\.status\s*!=\s*"cancelled"\)',
        text,
    ), "squad-run OPEN_KIDS jq must exclude both done and cancelled children"


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
    (no AskUserQuestion / confirmation in the cancel section)."""
    text = _read(repo_root, "skills/squad/SKILL.md")
    assert "/squad cancel" in text, "squad/SKILL.md must document the /squad cancel command"
    assert re.search(r"api POST /task/\$ID/cancel", text), (
        "/squad cancel must call `api POST /task/$ID/cancel`"
    )
    # Isolate the cancel section and assert it is non-interactive.
    m = re.search(r"### `/squad cancel.*?(?=\n### )", text, re.DOTALL)
    assert m, "could not isolate the /squad cancel section"
    section = m.group(0)
    assert "non-interactive" in section.lower(), (
        "the /squad cancel section must declare itself non-interactive"
    )
    # Non-interactive = the section disclaims AskUserQuestion (the only mention is a "no
    # AskUserQuestion" negation), never invokes it as a step.
    assert re.search(r"no\s+`?AskUserQuestion`?", section), (
        "the /squad cancel section must explicitly disclaim AskUserQuestion (non-interactive)"
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
    section appears before the remove section."""
    text = _read(repo_root, "skills/squad/SKILL.md")
    cancel_idx = text.find("### `/squad cancel")
    remove_idx = text.find("### `/squad remove")
    assert cancel_idx != -1 and remove_idx != -1, "both /squad cancel and /squad remove must exist"
    assert cancel_idx < remove_idx, "/squad cancel must be documented BEFORE /squad remove"
    # The remove section steers toward cancel for won't-do / superseded work.
    assert re.search(r"prefer.*`?/squad cancel`?", text, re.IGNORECASE), (
        "squad/SKILL.md must steer won't-do/superseded work to /squad cancel over remove"
    )
    assert re.search(r"irreversible", text, re.IGNORECASE), (
        "the /squad remove steer must call DELETE irreversible"
    )


def test_squad_stats_columns_include_cancelled(repo_root):
    """The /squad stats column list includes `cancelled`."""
    text = _read(repo_root, "skills/squad/SKILL.md")
    assert re.search(r"columns\s*=\s*\[[^\]]*'cancelled'", text), (
        "/squad stats `columns` list must include 'cancelled'"
    )


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
