"""Structural guards for the `/complete` administrative-completion adoption across the squad skills.

The board grew an administrative completion action: a task can be completed from ANY non-terminal
status via `POST /api/orgs/{org}/task/{id}/complete` (optional `completion_note`), landing on the
existing `done` terminal. It records `completed_via` (`"admin"` vs the gated `"pipeline"` vs the
epic `"rollup"`), it is history-preserving and idempotent, a cancelled target returns `409`, and it
is reversible via the generalized reopen action (`cancelled` OR `done` → `todo`, which also nulls
`completion_note` + `completed_via`).

Post skills-efficiency re-architecture the contract's homes moved (the CONTRACTS are unchanged):
  - endpoint + 409-on-cancelled + reopen-nulls semantics → `skills/squad/references/api.md`
    (`skills/squad/shared.md` stays the hub carrying the move-matrix mention of `/complete`);
  - epic-blocker readiness semantics (readiness = STORED status; the derived epic `complete`
    rollup is display-only) → `skills/squad/references/epics.md`;
  - squad-run's terminal refusal + readiness gate → `skills/squad/scripts/pipeline.py`
    `preflight`, unit-tested here with a stubbed `_req` (no network);
  - `/squad complete` + `/squad reopen` → still `skills/squad/SKILL.md` (complete/cancel now
    share ONE "Terminal actions" section — the pairing is structural, not prose).

`/complete` is the symmetric twin of the `cancelled` adoption; this mirrors test_cancel_adoption.py
(hermetic; reads the committed skill files / stubs board I/O).
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


# ── shared.md hub + references/api.md: move-matrix, endpoint, reopen prose ─────


def test_shared_documents_complete_terminal_reachable(repo_root):
    """The docs state `done` is reachable via `/complete` from any non-terminal status: shared.md
    (hub) keeps the move-matrix mention; references/api.md carries the endpoint semantics."""
    hub = _read(repo_root, "skills/squad/shared.md")
    assert re.search(r"/complete", hub), "shared.md must reference the /complete action"
    api = _read(repo_root, "skills/squad/references/api.md")
    assert re.search(r"/complete", api), "references/api.md must document the /complete action"
    assert re.search(r"non-terminal", api, re.IGNORECASE), (
        "references/api.md must state /complete is reachable from any NON-TERMINAL status"
    )


def test_shared_documents_complete_endpoint(repo_root):
    """references/api.md's lifecycle block carries the executable `api POST /task/$ID/complete`
    call with an optional completion_note and the completed_via semantics."""
    text = _read(repo_root, "skills/squad/references/api.md")
    assert re.search(r"api POST /task/\$ID/complete", text), (
        "references/api.md must document the executable `api POST /task/$ID/complete` endpoint"
    )
    assert "completion_note" in text, "the complete endpoint doc must mention completion_note"
    assert "completed_via" in text, "references/api.md must mention completed_via"


def test_shared_reopen_prose_nulls_completion_fields(repo_root):
    """The reopen prose (now in references/api.md) must null completion_note AND completed_via
    (the un-complete path), alongside cancel_reason — the done-only reopen wording stays gone."""
    text = _read(repo_root, "skills/squad/references/api.md")
    # The reopen sentence must name both fields it clears.
    assert re.search(
        r"[Rr]eopen clears[^.]*completion_note[^.]*completed_via",
        text,
        re.DOTALL,
    ), "references/api.md reopen prose must null completion_note AND completed_via"
    assert re.search(r"[Rr]eopen clears[^.]*cancel_reason", text, re.DOTALL), (
        "references/api.md reopen prose must also null cancel_reason"
    )
    # The old narrow claim must still be gone from the hub AND the reference.
    for rel in ("skills/squad/shared.md", "skills/squad/references/api.md"):
        assert not re.search(
            r"only a\s+`?done`?\s+task can be reopened", _read(repo_root, rel), re.IGNORECASE
        ), f"{rel} still carries the old done-only reopen wording"


def test_shared_complete_endpoint_documents_409_on_cancelled(repo_root):
    """references/api.md must document /complete's 409-on-a-cancelled-target (reopen-first) guard —
    the third arm of AC#1 (endpoint + 409-on-cancelled + reopen-nulls-both). Without this a future
    edit could drop the `cancelled → 409` contract while every other complete guard stays green."""
    text = _read(repo_root, "skills/squad/references/api.md")
    assert re.search(r"cancelled target[^\n]{0,40}409", text, re.IGNORECASE), (
        "references/api.md must document that /complete on a CANCELLED target returns 409"
    )
    assert re.search(r"reopen first", text, re.IGNORECASE), (
        "the 409-on-cancelled doc must point at reopen-first"
    )


def test_shared_readiness_epic_blocker_complete_note(repo_root):
    """references/epics.md carries the epic-blocker readiness semantics: readiness is the STORED
    status (an epic blocker satisfies the gate when its stored status is terminal — the rollup
    sets it, `completed_via:"rollup"`); the derived epic `complete` flag is display-only."""
    text = _read(repo_root, "skills/squad/references/epics.md")
    assert re.search(r"epic[^\n]*blocker|blocker[^\n]*epic", text, re.IGNORECASE), (
        "references/epics.md must cover an epic used as a blocker satisfying the readiness gate"
    )
    assert re.search(r"stored status|status-based", text, re.IGNORECASE), (
        "references/epics.md must state readiness keys on the STORED status"
    )
    assert re.search(r"display-only|display\s*/\s*reporting", text, re.IGNORECASE), (
        "references/epics.md must state the derived epic `complete` rollup is display-only"
    )
    assert "rollup" in text, (
        "references/epics.md must document the completed_via rollup that resolves epic blockers"
    )
    # The resolved set is unchanged: done + cancelled.
    assert re.search(r"`done`\s+or\s+`cancelled`", text), (
        "references/epics.md must keep done/cancelled as the resolved (terminal) set"
    )


# ── squad-run readiness gate = pipeline.py preflight (done terminal refusal) ───


def test_squad_run_refuses_done_target(repo_root, pipeline_mod, monkeypatch, capsys):
    """squad-run's preflight (pipeline.py) refuses a `done` target before dispatch
    (terminal — reopen to run), with no special-casing on HOW it reached done."""
    out = _preflight(pipeline_mod, monkeypatch, capsys, _task(status="done"),
                     {"blocked_by": [], "children": [], "children_progress": None})
    assert out["runnable"] is False, "preflight must refuse a done target"
    assert "terminal" in out["reason"], "the done refusal must label it terminal"
    assert "reopen" in out["reason"].lower(), "the done refusal must point at reopen"
    # And the orchestrating skill acts on that verdict with the reopen pointer.
    text = _read(repo_root, "skills/squad-run/SKILL.md")
    assert "reopen to run" in text, "squad-run must relay 'reopen to run' on a terminal target"


def test_squad_run_readiness_jq_unchanged_for_done(pipeline_mod, monkeypatch, capsys):
    """(Was: the BLOCKERS readiness jq.) The readiness gate — now pipeline.py preflight —
    still treats a `done` dependency as resolved: /complete needs no readiness change
    (the key divergence from the cancel adoption)."""
    out = _preflight(pipeline_mod, monkeypatch, capsys, _task(),
                     {"blocked_by": [{"id": "SQD-9", "title": "dep", "status": "done"}],
                      "children": [], "children_progress": None})
    assert out["blockers"] == [], "a done dep must not appear as a blocker"
    assert out["runnable"] is True, "a task whose only dep is done must be runnable"


def test_squad_run_readiness_jq_not_wired_to_derived_epic_complete(pipeline_mod, monkeypatch, capsys):
    """NEGATIVE guard for the key divergence: readiness must key on the dep's `.status` ONLY —
    never on the derived epic rollup (`complete` / `children_progress` / `epic_status`). A dep
    carrying a truthy derived `complete` flag but a non-terminal STORED status must still block
    (the derived flag is display-only); a dep with a terminal stored status resolves regardless
    of its derived fields."""
    rollup_dep = {"id": "SQD-9", "title": "epic dep", "status": "impl",
                  "complete": True, "children_progress": {"done": 5, "total": 5},
                  "epic_status": "done", "card_type": "epic"}
    out = _preflight(pipeline_mod, monkeypatch, capsys, _task(),
                     {"blocked_by": [rollup_dep], "children": [], "children_progress": None})
    assert out["runnable"] is False and out["blockers"], (
        "readiness must stay status-based — a derived epic `complete` rollup must NOT satisfy "
        "a dependency whose stored status is non-terminal"
    )
    resolved_dep = dict(rollup_dep, status="done", complete=False)
    out = _preflight(pipeline_mod, monkeypatch, capsys, _task(),
                     {"blocked_by": [resolved_dep], "children": [], "children_progress": None})
    assert out["runnable"] is True and out["blockers"] == [], (
        "a dep with a terminal STORED status resolves regardless of derived fields"
    )


def test_squad_run_carries_epic_blocker_complete_note(repo_root):
    """(Was: the readiness note inlined in squad-run/SKILL.md.) squad-run now delegates readiness
    to `pipe preflight`; the epic-blocker note (status-based readiness, display-only derived
    rollup) lives in references/epics.md, which shared.md points every skill at."""
    run = _read(repo_root, "skills/squad-run/SKILL.md")
    assert "pipe preflight" in run, "squad-run must delegate readiness to pipeline.py preflight"
    epics = _read(repo_root, "skills/squad/references/epics.md")
    assert re.search(r"stored status|status-based", epics, re.IGNORECASE)
    assert re.search(r"display-only", epics, re.IGNORECASE)
    hub = _read(repo_root, "skills/squad/shared.md")
    assert "references/epics.md" in hub, (
        "shared.md must point skills at references/epics.md for readiness/rollup semantics"
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
    non-interactive (declares it, and never invokes AskUserQuestion in its section)."""
    text = _read(repo_root, "skills/squad/SKILL.md")
    assert "/squad complete" in text, "squad/SKILL.md must document the /squad complete command"
    assert re.search(r"api POST /task/\$ID/complete", text), (
        "/squad complete must call `api POST /task/$ID/complete`"
    )
    # Isolate the (now combined complete·cancel) Terminal-actions section.
    m = re.search(r"### `/squad complete.*?(?=\n### )", text, re.DOTALL)
    assert m, "could not isolate the /squad complete section"
    section = m.group(0)
    assert "non-interactive" in section.lower(), (
        "the /squad complete section must declare itself non-interactive"
    )
    assert "AskUserQuestion" not in section, (
        "the /squad complete section must not invoke AskUserQuestion (non-interactive)"
    )


def test_squad_skill_complete_paired_with_cancel_before_remove(repo_root):
    """squad/SKILL.md positions /squad complete before the irreversible /squad remove and pairs it
    with /squad cancel (complete = finished, cancel = won't-do). Post-rewrite the pairing is
    structural: both verbs share ONE 'Terminal actions' section."""
    text = _read(repo_root, "skills/squad/SKILL.md")
    complete_idx = text.find("### `/squad complete")
    remove_idx = text.find("### `/squad remove")
    assert complete_idx != -1 and remove_idx != -1, "both /squad complete and /squad remove must exist"
    assert complete_idx < remove_idx, "/squad complete must be documented BEFORE /squad remove"
    # Paired-with-cancel framing: one shared section documents both verbs.
    m = re.search(r"### `/squad complete.*?(?=\n### )", text, re.DOTALL)
    assert m and "/squad cancel" in m.group(0), (
        "/squad complete and /squad cancel must be documented as a pair (one shared section)"
    )
    assert re.search(r"finished", text, re.IGNORECASE) and re.search(r"won't-do|won.t-do", text, re.IGNORECASE), (
        "squad/SKILL.md must frame complete=finished vs cancel=won't-do"
    )


def test_squad_skill_reopen_nulls_completion_fields(repo_root):
    """squad/SKILL.md's /squad reopen command still calls POST .../reopen; the field-nulling
    detail (completion_note + completed_via cleared) lives in references/api.md."""
    text = _read(repo_root, "skills/squad/SKILL.md")
    assert "/squad reopen" in text, "squad/SKILL.md must document the /squad reopen command"
    assert re.search(r"api POST /task/\$ID/reopen", text), (
        "/squad reopen must call `api POST /task/$ID/reopen`"
    )
    api = _read(repo_root, "skills/squad/references/api.md")
    assert re.search(r"[Rr]eopen clears[^.]*completion_note[^.]*completed_via", api, re.DOTALL), (
        "references/api.md must state reopen nulls completion_note + completed_via"
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
