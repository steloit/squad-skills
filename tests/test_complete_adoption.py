"""Structural guards for the `/complete` administrative-completion adoption across the squad skills.

The board grew an administrative completion action: a task can be completed from ANY non-terminal
status via `POST /api/orgs/{org}/task/{id}/complete` (optional `completion_note`), landing on the
existing `done` terminal. It records `completed_via` (`"admin"` vs the gated `"pipeline"`), it is
history-preserving and idempotent, a cancelled target returns `409`, and it is reversible via the
generalized reopen action (`cancelled` OR `done` → `todo`, which now also nulls `completion_note` +
`completed_via`). These deterministic grep invariants keep the skills aligned with that action so the
adoption can't silently regress — a re-narrowed reopen, a dispatch that forgets `done` is terminal, a
missing `/complete` verb, or a readiness note that treats the derived epic `complete` rollup as a
dependency-satisfaction signal.

`/complete` is the symmetric twin of the `cancelled` adoption; this mirrors test_cancel_adoption.py
1:1 (hermetic; reads the committed skill files). The key divergence: readiness logic is NOT touched —
`done` is already in the resolved `{done, cancelled}` set, so there is no jq change to assert.
"""
import re


def _read(repo_root, rel):
    return (repo_root / rel).read_text()


# ── schema.md: the completion_note + completed_via fields + /complete prose ────


def test_schema_lists_completion_fields_and_complete_prose(repo_root):
    """schema.md documents `completion_note` + `completed_via`, the `/complete` terminal/reopen
    semantics, and the derived epic `complete` rollup as display/reporting only."""
    text = _read(repo_root, "skills/squad/schema.md")
    assert "completion_note" in text, "schema.md must document the `completion_note` field"
    assert "completed_via" in text, "schema.md must document the `completed_via` field"
    assert "/complete" in text, "schema.md must reference the POST .../complete endpoint"
    # Terminal + reopenable framing.
    assert "terminal" in text.lower(), "schema.md must describe `done` as terminal for /complete"
    assert "reopen" in text.lower(), "schema.md must say /complete-done is left only via reopen"
    # The completed_via values are documented.
    assert "pipeline" in text and "admin" in text, (
        "schema.md must document completed_via values {pipeline, admin}"
    )
    # Derived epic complete flag = display / reporting only, NOT a dependency-satisfaction signal.
    assert re.search(r"complete[^\n]*display", text, re.IGNORECASE) or re.search(
        r"display[^\n]*complete", text, re.IGNORECASE
    ), "schema.md must state the derived epic `complete` rollup is DISPLAY/REPORTING only"
    assert re.search(r"reporting only|display\s*/\s*reporting", text, re.IGNORECASE), (
        "schema.md must label the derived epic `complete` flag display/reporting only"
    )
    assert re.search(r"\bnot\b[^\n]{0,8}dependency-satisfaction", text, re.IGNORECASE), (
        "schema.md must state the derived epic `complete` flag is NOT a dependency-satisfaction signal"
    )


# ── shared.md: move-matrix, endpoint, reopen prose, epic-blocker readiness ─────


def test_shared_documents_complete_terminal_reachable(repo_root):
    """shared.md documents `done` reachable via `/complete` from any non-terminal status (in addition
    to the gated pipeline path)."""
    text = _read(repo_root, "skills/squad/shared.md")
    assert re.search(r"non-terminal", text, re.IGNORECASE), (
        "shared.md must state /complete is reachable from any NON-TERMINAL status"
    )
    assert re.search(r"/complete", text), "shared.md must reference the /complete action"


def test_shared_documents_complete_endpoint(repo_root):
    """shared.md's API Endpoints block adds an executable `api POST /task/$ID/complete` call with an
    optional completion_note and the completed_via/409 semantics."""
    text = _read(repo_root, "skills/squad/shared.md")
    assert re.search(r"api POST /task/\$ID/complete", text), (
        "shared.md must document the executable `api POST /task/$ID/complete` endpoint"
    )
    assert "completion_note" in text, "shared.md complete endpoint must mention completion_note"
    assert "completed_via" in text, "shared.md must mention completed_via"


def test_shared_reopen_prose_nulls_completion_fields(repo_root):
    """The reopen prose must null completion_note AND completed_via (the un-complete path), alongside
    cancel_reason — the done-only reopen wording stays gone."""
    text = _read(repo_root, "skills/squad/shared.md")
    # The reopen sentence must name both new fields it now clears.
    assert re.search(
        r"reopen[^.]*completion_note[^.]*completed_via|completion_note[^.]*\bcompleted_via\b",
        text,
        re.IGNORECASE | re.DOTALL,
    ), "shared.md reopen prose must null completion_note AND completed_via"
    # The old narrow claim must still be gone (mirrors the cancel-adoption guard).
    assert not re.search(r"only a\s+`?done`?\s+task can be reopened", text, re.IGNORECASE), (
        "shared.md still carries the old done-only reopen wording"
    )


def test_shared_complete_endpoint_documents_409_on_cancelled(repo_root):
    """shared.md must document /complete's 409-on-a-cancelled-target (reopen-first) guard — the third
    arm of AC#1 (endpoint + 409-on-cancelled + reopen-nulls-both). The sibling endpoint/reopen guards
    above never assert the 409 path, so without this a future edit could drop the `cancelled → 409`
    contract from the docs while every other complete guard stays green."""
    text = _read(repo_root, "skills/squad/shared.md")
    assert re.search(
        r"cancelled target returns\s+`?409`?|`?409`?\s+on a cancelled target", text, re.IGNORECASE
    ), "shared.md must document that /complete on a CANCELLED target returns 409 (reopen first)"


def test_shared_readiness_epic_blocker_complete_note(repo_root):
    """shared.md's readiness gate carries the epic-blocker `/complete`-to-unblock note: status-based
    readiness, the derived epic `complete` rollup is display-only (not a dependency signal)."""
    text = _read(repo_root, "skills/squad/shared.md")
    assert re.search(r"epic[^\n]*blocker|blocker[^\n]*/complete|epic[^\n]*/complete", text, re.IGNORECASE), (
        "shared.md must note an epic used as a blocker should be /complete'd to unblock dependents"
    )
    assert re.search(r"status-based", text, re.IGNORECASE), (
        "shared.md must state readiness stays status-based"
    )
    assert re.search(r"display-only|display\s*/\s*reporting", text, re.IGNORECASE), (
        "shared.md must state the derived epic `complete` rollup is display-only"
    )
    # The resolved set is unchanged — no jq/set edit for /complete.
    assert re.search(r"\{done,\s*cancelled\}", text), (
        "shared.md must keep {done, cancelled} as the resolved set (unchanged for /complete)"
    )


# ── squad-run: done terminal refusal (no special-casing on HOW it reached done) ─


def test_squad_run_refuses_done_target(repo_root):
    """squad-run refuses a `done` target before dispatch (terminal — reopen to re-run), with no
    special-casing on how it reached done."""
    text = _read(repo_root, "skills/squad-run/SKILL.md")
    assert re.search(r'STATUS"\s*=\s*"done"', text), (
        "squad-run must branch on STATUS == done before dispatch"
    )
    assert "done (terminal)" in text, "squad-run done refusal must label it terminal"
    assert "reopen" in text.lower(), "squad-run done refusal must point at reopen"


def test_squad_run_readiness_jq_unchanged_for_done(repo_root):
    """squad-run's BLOCKERS readiness jq is UNCHANGED — `done` was already excluded, so /complete
    needs no jq edit (the key divergence from the cancel adoption)."""
    text = _read(repo_root, "skills/squad-run/SKILL.md")
    assert re.search(
        r'\.blocked_by\[\]\?[^\n]*select\(\.status\s*!=\s*"done"\s+and\s+\.status\s*!=\s*"cancelled"\)',
        text,
    ), "squad-run BLOCKERS jq must still exclude done and cancelled (unchanged for /complete)"


def test_squad_run_readiness_jq_not_wired_to_derived_epic_complete(repo_root):
    """NEGATIVE guard for the key divergence: the readiness `.blocked_by` jq must key on `.status`
    ONLY — it must NOT wire the derived epic rollup (`.complete` / `children_progress` / `epic_status`
    / `card_type`) into dependency satisfaction. The positive `..._unchanged_for_done` guard above
    only matches the existing select form; it would still pass if an agent ADDED a second
    `.blocked_by` filter that treated a derived epic `complete` rollup as a resolved dep — the exact
    mistake the schema/shared/run prose warns against (the derived flag is display-only). This scans
    every `.blocked_by` jq line and fails if any references the rollup fields. (The unrelated epic
    `children_progress` PROGRESS read elsewhere in the skill is not a `.blocked_by` line, so it is
    correctly out of scope.)"""
    text = _read(repo_root, "skills/squad-run/SKILL.md")
    blocked_by_jq = [
        ln for ln in text.splitlines() if ".blocked_by" in ln and "jq" in ln
    ]
    assert blocked_by_jq, (
        "expected at least one executable `.blocked_by` jq line in squad-run's readiness gate"
    )
    forbidden = (".complete", "children_progress", "epic_status", "card_type")
    for ln in blocked_by_jq:
        for tok in forbidden:
            assert tok not in ln, (
                "squad-run readiness must stay status-based — a `.blocked_by` jq line wires the "
                f"derived epic rollup field {tok!r} into dependency satisfaction: {ln.strip()!r}"
            )


def test_squad_run_carries_epic_blocker_complete_note(repo_root):
    """squad-run's readiness gate carries the epic-blocker `/complete`-to-unblock note (status-based;
    derived rollup display-only)."""
    text = _read(repo_root, "skills/squad-run/SKILL.md")
    assert re.search(r"/complete", text), "squad-run must reference /complete in the readiness note"
    assert re.search(r"status-based", text, re.IGNORECASE), (
        "squad-run readiness note must state readiness stays status-based"
    )
    assert re.search(r"display-only", text, re.IGNORECASE), (
        "squad-run readiness note must call the derived epic `complete` rollup display-only"
    )


# ── squad-refine: a /complete-reached done target is a non-runnable terminal ───


def test_squad_refine_treats_complete_done_target_as_terminal(repo_root):
    """squad-refine treats a done target (reached via /complete OR the pipeline) as a non-runnable
    terminal, names reopen, and carries the epic-blocker /complete readiness note."""
    text = _read(repo_root, "skills/squad-refine/SKILL.md")
    assert "done" in text, "squad-refine must handle a done target"
    assert re.search(r"terminal", text, re.IGNORECASE), (
        "squad-refine must label a done/cancelled target as a non-runnable terminal"
    )
    assert "reopen" in text.lower(), (
        "squad-refine must point the user at reopen before refining a terminal target"
    )
    assert re.search(r"/complete", text), (
        "squad-refine must note /complete as a route to the done terminal + the epic-blocker note"
    )


# ── squad/SKILL.md: /squad complete (non-interactive) + paired-with-cancel ─────


def test_squad_skill_has_non_interactive_complete_calling_post_complete(repo_root):
    """squad/SKILL.md has a /squad complete command that calls POST .../complete and is
    non-interactive (no AskUserQuestion / confirmation in the complete section)."""
    text = _read(repo_root, "skills/squad/SKILL.md")
    assert "/squad complete" in text, "squad/SKILL.md must document the /squad complete command"
    assert re.search(r"api POST /task/\$ID/complete", text), (
        "/squad complete must call `api POST /task/$ID/complete`"
    )
    # Isolate the complete section and assert it is non-interactive.
    m = re.search(r"### `/squad complete.*?(?=\n### )", text, re.DOTALL)
    assert m, "could not isolate the /squad complete section"
    section = m.group(0)
    assert "non-interactive" in section.lower(), (
        "the /squad complete section must declare itself non-interactive"
    )
    assert re.search(r"no\s+`?AskUserQuestion`?", section), (
        "the /squad complete section must explicitly disclaim AskUserQuestion (non-interactive)"
    )


def test_squad_skill_complete_paired_with_cancel_before_remove(repo_root):
    """squad/SKILL.md positions /squad complete before the irreversible /squad remove and frames it as
    the paired twin of /squad cancel (complete = finished, cancel = won't-do)."""
    text = _read(repo_root, "skills/squad/SKILL.md")
    complete_idx = text.find("### `/squad complete")
    remove_idx = text.find("### `/squad remove")
    assert complete_idx != -1 and remove_idx != -1, "both /squad complete and /squad remove must exist"
    assert complete_idx < remove_idx, "/squad complete must be documented BEFORE /squad remove"
    # Paired-with-cancel framing.
    assert re.search(r"finished", text, re.IGNORECASE) and re.search(r"won't-do|won.t-do", text, re.IGNORECASE), (
        "squad/SKILL.md must frame complete=finished vs cancel=won't-do"
    )
    assert re.search(r"paired|twin", text, re.IGNORECASE), (
        "squad/SKILL.md must frame /squad complete as paired with /squad cancel"
    )


def test_squad_skill_reopen_nulls_completion_fields(repo_root):
    """squad/SKILL.md's /squad reopen section nulls completion_note + completed_via (the un-complete
    path), and still calls POST .../reopen."""
    text = _read(repo_root, "skills/squad/SKILL.md")
    assert "/squad reopen" in text, "squad/SKILL.md must document the /squad reopen command"
    assert re.search(r"api POST /task/\$ID/reopen", text), (
        "/squad reopen must call `api POST /task/$ID/reopen`"
    )
    m = re.search(r"### `/squad reopen.*?(?=\n### )", text, re.DOTALL)
    assert m, "could not isolate the /squad reopen section"
    section = m.group(0)
    assert "completion_note" in section and "completed_via" in section, (
        "the /squad reopen section must state it nulls completion_note + completed_via"
    )


# ── fixtures: the refreshed contract carries the complete endpoint ─────────────


def test_complete_endpoint_in_openapi_and_consumer_contract(repo_root):
    """The refreshed snapshots carry the complete endpoint: openapi.json has the path key and the
    consumer contract publishes POST .../complete."""
    import json

    spec = json.loads(_read(repo_root, "tests/fixtures/openapi.json"))
    assert any("complete" in p for p in spec["paths"]), (
        "openapi.json snapshot must include the .../complete path (run scripts/refresh-openapi.sh)"
    )
    contract = json.loads(_read(repo_root, "tests/fixtures/consumer-contract.json"))
    assert {"method": "POST", "path": "/orgs/{}/task/{}/complete"} in contract, (
        "consumer-contract.json must publish POST /orgs/{}/task/{}/complete "
        "(run scripts/refresh-consumer-contract.py)"
    )
