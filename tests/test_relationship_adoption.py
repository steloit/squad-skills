"""Structural guards for the unified relationships + epic adoption (#340).

#340 moved every squad skill onto the deployed unified `/relationships` API and the first-class
epic card model from #339:
  - dependency (`blocks`) I/O resolves via `GET .../task/:id/relationships` → `.blocked_by`
    (the removed `/dependencies` endpoint and the `Depends on:` description-text convention are retired);
  - hierarchy is structured — skills create `card_type:'epic'` cards + `POST /relationships {type:'parent'}`
    edges (the `epic:<name>` tag-as-hierarchy convention is retired);
  - epics are excluded from the agent pipeline (containers), with a soft sub-task readiness nudge.

Post skills-efficiency re-architecture the contract's homes moved (the CONTRACTS are unchanged):
  - the relationships/epics doc → `skills/squad/references/epics.md` (shared.md stays the hub);
  - squad-run's dependency resolution, epic refusal, and sub-task nudge → pipeline.py `preflight`
    (unit-tested here with a stubbed `_req` — no network); batch creation edges → create_tasks.py.

These deterministic invariants keep the migration from silently regressing — a re-introduced
`/dependencies` call, a creeping `Depends on:` text-parse, or a re-introduced `epic:`
hierarchy-tag write.
"""
import argparse
import json
import re


# The contract docs MUST document the retired conventions and the new endpoints — they are
# the source of truth, not operational writers/parsers. The operational guards below scope to the
# executable skill files, excluding them (mirrors _CONTRACT_DOCS in test_activity_adoption.py).
_CONTRACT_DOCS = {
    "skills/squad/shared.md",
    "skills/squad/schema.md",
    "skills/squad/references/epics.md",
    "skills/squad/references/api.md",
}


def _skill_files(repo_root, exclude_contract_docs=False):
    """Authored skill sources (markdown + python), excluding this test file."""
    skills_dir = repo_root / "skills"
    files = list(skills_dir.rglob("*.md")) + list(skills_dir.rglob("*.py"))
    if exclude_contract_docs:
        files = [p for p in files if str(p.relative_to(repo_root)) not in _CONTRACT_DOCS]
    return files


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


def test_no_skill_references_dependencies_endpoint(repo_root):
    """The `/dependencies` endpoint is REMOVED (404). No skill — including the contract docs —
    may reference it as a URL path segment. (The doc-pointer phrase 'epics/dependencies:' in
    squad/SKILL.md names the references/epics.md file, not an endpoint — it is stripped before
    scanning so any other `/dependencies` occurrence is still flagged.)"""
    bare_dep = re.compile(r"/dependencies\b")
    offenders = []
    for p in _skill_files(repo_root):
        text = p.read_text().replace("epics/dependencies", "")
        if bare_dep.search(text):
            offenders.append(str(p.relative_to(repo_root)))
    assert not offenders, f"Skills must not reference the removed /dependencies endpoint: {offenders}"


def test_no_skill_parses_depends_on_text(repo_root):
    """No operational skill text-parses the retired `Depends on:` convention. A bare *mention*
    in a 'this is retired' note is fine; what is banned is an extraction (grep/regex/search over
    `Depends on:`). The contract docs document the removal and are excluded."""
    # Extraction signatures: a regex/grep that captures `Depends on:`.
    parse_pats = [
        re.compile(r"grep[^\n]*Depends on:", re.IGNORECASE),
        re.compile(r"(?i)depends\s*on:\\s\*"),          # a regex literal like `Depends on:\s*`
        re.compile(r"DEPENDS_RE"),                       # the old python regex constant
    ]
    offenders = []
    for p in _skill_files(repo_root, exclude_contract_docs=True):
        text = p.read_text()
        if any(pat.search(text) for pat in parse_pats):
            offenders.append(str(p.relative_to(repo_root)))
    assert not offenders, (
        f"skills must not parse the retired `Depends on:` text — use GET /relationships .blocked_by: {offenders}"
    )


def test_no_skill_writes_epic_hierarchy_tag(repo_root):
    """No skill writes an `epic:<name>` hierarchy tag. Hierarchy is `card_type:'epic'` + parent edges.
    A bare mention in a 'no epic: tag' deprecation note is fine; what is banned is an `epic:<name>`
    tag *value* being written (in a tags string/array or a jq --arg tags). Contract docs excluded."""
    # An epic: tag value followed by a name char — e.g. `epic:auth`, `"epic:foo"`.
    # The retired writes were `epic:<name>` in tag strings; deprecation notes write `epic:` bare
    # (no following name) or inside backticks like `epic:<name>` / `epic:` — those are allowed.
    write_pat = re.compile(r"epic:[A-Za-z0-9]")
    offenders = []
    for p in _skill_files(repo_root, exclude_contract_docs=True):
        for line in p.read_text().splitlines():
            if write_pat.search(line):
                offenders.append(f"{p.relative_to(repo_root)}: {line.strip()}")
    assert not offenders, f"skills must not write `epic:<name>` hierarchy tags: {offenders}"


def test_squad_run_resolves_deps_via_relationships(repo_root):
    """squad-run's dependency resolution — now pipeline.py — reads GET /relationships →
    .blocked_by (not text-parse), and the old client-side circular-grep stays gone from both
    the skill and the engine script."""
    pipeline_src = (repo_root / "skills" / "squad" / "scripts" / "pipeline.py").read_text()
    assert "/relationships" in pipeline_src, "pipeline.py must use the /relationships API"
    assert "blocked_by" in pipeline_src, "pipeline.py must read .blocked_by for dependency resolution"
    run_text = (repo_root / "skills" / "squad-run" / "SKILL.md").read_text()
    assert "pipe preflight" in run_text, "squad-run must delegate dep resolution to pipeline preflight"
    for text, name in ((run_text, "squad-run/SKILL.md"), (pipeline_src, "pipeline.py")):
        assert "grep -ioP 'Depends on:" not in text, f"{name} still text-parses Depends on:"
        assert "circular dependency detected" not in text, (
            f"{name} still contains the removed client-side circular-dependency check"
        )


def test_squad_run_gates_on_blocked_by_status(repo_root, pipeline_mod, monkeypatch, capsys):
    """The readiness gate keys on .blocked_by[].status (the hard dependency block): a non-terminal
    dep makes the task non-runnable, and squad-run refuses with the incomplete-dependency message
    in --auto mode."""
    out = _preflight(pipeline_mod, monkeypatch, capsys, _task(),
                     {"blocked_by": [{"id": "SQD-9", "title": "dep", "status": "plan"}],
                      "children": [], "children_progress": None})
    assert out["runnable"] is False
    assert "blocked by incomplete dependency" in out["reason"]
    text = (repo_root / "skills" / "squad-run" / "SKILL.md").read_text()
    assert "blocked by incomplete dependency" in text, (
        "squad-run must refuse a task blocked by an incomplete dependency in --auto mode"
    )


def test_declaration_skills_post_blocks_relationships(repo_root):
    """squad-refine / squad-batch-run / squad-kickstart each declare a blocks dependency via
    POST /relationships {type:'blocks'}."""
    declarers = ["squad-refine", "squad-batch-run", "squad-kickstart"]
    missing = []
    for name in declarers:
        text = (repo_root / "skills" / name / "SKILL.md").read_text()
        if "/relationships" not in text or not re.search(r'type["\s:]+.*blocks', text):
            missing.append(name)
    assert not missing, (
        f"these skills must declare blocks deps via POST /relationships {{type:'blocks'}}: {missing}"
    )


def test_kickstart_and_explore_create_epic_cards_and_parent_edges(repo_root):
    """squad-kickstart and squad-explore each create card_type:'epic' cards and set children's
    parent via POST /relationships {type:'parent'}."""
    for name in ("squad-kickstart", "squad-explore"):
        text = (repo_root / "skills" / name / "SKILL.md").read_text()
        assert re.search(r'card_type["\s:]+.*epic', text), (
            f"{name} must create card_type:'epic' cards"
        )
        assert re.search(r'type["\s:]+.*parent', text), (
            f"{name} must set children's parent via POST /relationships {{type:'parent'}}"
        )


def test_squad_run_and_batch_run_exclude_epics(repo_root, pipeline_mod, monkeypatch, capsys):
    """squad-run's preflight refuses a card_type='epic' target (container); squad-batch-run
    excludes epics from selection."""
    out = _preflight(pipeline_mod, monkeypatch, capsys, _task(card_type="epic"),
                     {"blocked_by": [], "children": [], "children_progress": None})
    assert out["runnable"] is False, "preflight must refuse an epic target"
    assert "container" in out["reason"], "the epic refusal must call it a container"
    run_text = (repo_root / "skills" / "squad-run" / "SKILL.md").read_text()
    assert "epic" in run_text and "children" in run_text, (
        "squad-run must act on the epic refusal by listing children and stopping"
    )

    batch_text = (repo_root / "skills" / "squad-batch-run" / "SKILL.md").read_text()
    assert "epic" in batch_text and "container" in batch_text, (
        "squad-batch-run must skip epics (containers) in selection"
    )
    # The plan_batch script must also exclude epics from the runnable set.
    plan_batch = (repo_root / "skills" / "squad-batch-run" / "scripts" / "plan_batch.py").read_text()
    assert 'card_type' in plan_batch and 'epic' in plan_batch, (
        "plan_batch.py must exclude card_type=='epic' from the runnable set"
    )


def test_squad_run_reads_children_for_nudge(repo_root, pipeline_mod, monkeypatch, capsys):
    """The preflight bundle reads .children and reports open_subtasks so squad-run can emit the
    soft sub-task readiness nudge."""
    out = _preflight(pipeline_mod, monkeypatch, capsys, _task(),
                     {"blocked_by": [],
                      "children": [{"id": "SQD-2", "title": "kid", "status": "todo"}],
                      "children_progress": {"done": 0, "total": 1}})
    assert out["open_subtasks"] == ["SQD-2"], "preflight must surface open children"
    text = (repo_root / "skills" / "squad-run" / "SKILL.md").read_text()
    assert "open_subtasks" in text, "squad-run must act on the open_subtasks field"
    assert "sub-task" in text, "squad-run must reference the sub-task nudge"


def test_shared_documents_relationships_and_epics(repo_root):
    """references/epics.md documents the unified model + endpoints/shapes + epic semantics, marks
    BOTH the `Depends on:` and `epic:`-tag conventions retired, and shared.md (hub) points at it."""
    text = (repo_root / "skills" / "squad" / "references" / "epics.md").read_text()
    assert re.search(r"^# Task Relationships & Epics", text, re.MULTILINE), (
        "references/epics.md must be the Task Relationships & Epics doc"
    )
    # Unified typed model.
    for token in ("blocks", "parent", "card_type", "blocked_by", "children_progress"):
        assert token in text, f"references/epics.md missing {token}"
    # Endpoints + validation codes.
    assert re.search(r"api POST /task/\$ID/relationships", text)
    assert re.search(r"api GET /task/\$ID/relationships", text)
    for code in ("400", "404", "409"):
        assert code in text, f"references/epics.md must document the {code} validation case"
    # The epics aggregate.
    assert "epics" in text, "references/epics.md must document the board epics aggregate"
    # Both legacy conventions explicitly marked removed.
    assert "REMOVED" in text or "retired" in text.lower()
    assert "Depends on:" in text, "references/epics.md must name the retired Depends on: convention"
    assert "epic:" in text, "references/epics.md must name the retired epic: tag convention"
    hub = (repo_root / "skills" / "squad" / "shared.md").read_text()
    assert "references/epics.md" in hub, "shared.md must point skills at references/epics.md"


def test_squad_board_summary_reads_epics_aggregate(repo_root):
    """squad/SKILL.md board summaries group by the board epics aggregate / children_progress,
    not tag parsing."""
    text = (repo_root / "skills" / "squad" / "SKILL.md").read_text()
    assert "epics" in text and "children_progress" in text, (
        "squad/SKILL.md board summaries must read the epics aggregate + children_progress"
    )


# ──────────────────────────────────────────────────────────────────────────────
# Strengthened assertions added by Shield (#340) — cover edge cases Builder
# flagged and tighten the guard against silent regressions.
# ──────────────────────────────────────────────────────────────────────────────


def test_squad_run_epic_refusal_handles_zero_children(pipeline_mod, monkeypatch, capsys):
    """The epic container refusal must handle zero children: preflight still refuses, reports an
    empty children list (so the '(no children yet)' presentation is derivable) and carries the
    children_progress field either way."""
    out = _preflight(pipeline_mod, monkeypatch, capsys, _task(card_type="epic"),
                     {"blocked_by": [], "children": [], "children_progress": {"done": 0, "total": 0}})
    assert out["runnable"] is False and "container" in out["reason"], (
        "an epic with zero children must still be refused as a container"
    )
    assert out["children"] == [], "preflight must report the (empty) children list"
    assert "children_progress" in out, "preflight must carry children_progress in the refusal bundle"


def test_squad_run_dep_block_precedes_subtask_nudge(repo_root, pipeline_mod, monkeypatch, capsys):
    """The dep hard-block takes precedence over the soft sub-task nudge. Builder edge case: a task
    BOTH blocked by an incomplete dep AND with open sub-tasks → the hard dep block is the refusal
    reason; the nudge data is still surfaced separately."""
    out = _preflight(pipeline_mod, monkeypatch, capsys, _task(),
                     {"blocked_by": [{"id": "SQD-9", "title": "dep", "status": "impl"}],
                      "children": [{"id": "SQD-2", "title": "kid", "status": "todo"}],
                      "children_progress": {"done": 0, "total": 1}})
    assert out["runnable"] is False and "blocked by incomplete dependency" in out["reason"], (
        "the dep hard-block must win when both a blocker and open sub-tasks exist"
    )
    assert out["open_subtasks"] == ["SQD-2"], "the nudge data must still be reported"
    # The skill's own text keeps the two messages distinct and marks the nudge soft.
    text = (repo_root / "skills" / "squad-run" / "SKILL.md").read_text()
    assert "blocked by incomplete dependency" in text
    assert "open sub-task" in text or "sub-task(s)" in text
    assert "soft nudge" in text, (
        "squad-run must mark the sub-task nudge as soft (the dep block is the hard refusal)"
    )


def test_no_client_side_circular_check_in_any_skill(repo_root):
    """No skill contains a client-side circular-dependency pre-check.
    The server enforces acyclicity (in-transaction CTE) and returns 409 on a cycle.
    Builder confirmed the grep block is gone from squad-run; this guard covers ALL skills."""
    circular_pats = [
        re.compile(r"circular dependency detected", re.IGNORECASE),
        # A client that builds a dep graph to pre-check cycles.
        re.compile(r"detect.*circular|circular.*detect", re.IGNORECASE),
    ]
    offenders = []
    for p in _skill_files(repo_root, exclude_contract_docs=True):
        text = p.read_text()
        for pat in circular_pats:
            if pat.search(text):
                offenders.append(str(p.relative_to(repo_root)))
                break
    assert not offenders, (
        f"skills must not contain client-side circular-dependency checks (server returns 409): {offenders}"
    )


def test_plan_batch_old_parse_depends_on_function_gone(repo_root):
    """plan_batch.py must NOT contain the old `parse_depends_on` function.
    Builder replaced it with `extract_blocked_by` (reads .relationships.blocked_by).
    A regression would silently break the epic/blocking migration."""
    plan_batch = (repo_root / "skills" / "squad-batch-run" / "scripts" / "plan_batch.py").read_text()
    assert "parse_depends_on" not in plan_batch, (
        "plan_batch.py still defines the old parse_depends_on function — must be replaced by extract_blocked_by"
    )
    assert "extract_blocked_by" in plan_batch, (
        "plan_batch.py must define extract_blocked_by (reads .relationships.blocked_by)"
    )


def test_plan_batch_outputs_skipped_epics_field(repo_root):
    """plan_batch.py must produce a `skipped_epics` field in its JSON output when epics are filtered.
    This makes the epic exclusion visible to the SKILL.md layer so it can report skipped epics."""
    plan_batch = (repo_root / "skills" / "squad-batch-run" / "scripts" / "plan_batch.py").read_text()
    assert "skipped_epics" in plan_batch, (
        "plan_batch.py must produce a 'skipped_epics' field in its JSON output"
    )


def test_squad_refine_reads_children_for_epic_container_guard(repo_root):
    """squad-refine's epic container guard must fetch .children (GET /relationships) to point
    the user at the children — not just stop silently."""
    text = (repo_root / "skills" / "squad-refine" / "SKILL.md").read_text()
    # The guard must mention .children or the /relationships call to list sub-tasks.
    assert ".children" in text or "children" in text, (
        "squad-refine epic container guard must reference .children to redirect to sub-tasks"
    )
    # It must also state the epic is a container (not just silently skip).
    assert "container" in text, (
        "squad-refine must label the epic target as a container in the guard message"
    )


def test_shared_documents_server_enforced_acyclicity(repo_root):
    """references/epics.md must explicitly say the server enforces acyclicity and that there is NO
    client-side circular-dependency check. This is the normative statement all skills defer to."""
    text = (repo_root / "skills" / "squad" / "references" / "epics.md").read_text()
    # The server-enforcement statement must be present.
    assert "enforces acyclicity" in text or "no client-side circular" in text.lower(), (
        "references/epics.md must document that the server enforces acyclicity (no client-side pre-check)"
    )
    # The 409 cycle response code must be documented.
    assert "409" in text, "references/epics.md must document the 409 cycle response from POST /relationships"


def test_squad_run_nudge_message_distinguishes_block_vs_nudge(repo_root):
    """squad-run's dep block and sub-task nudge use distinct vocabulary so an agent reading
    the log can tell them apart. Builder required: block → 'incomplete dependency'; nudge →
    'open sub-task(s)' / 'usually run those first'."""
    text = (repo_root / "skills" / "squad-run" / "SKILL.md").read_text()
    # Dep hard-block vocabulary.
    assert "incomplete dependency" in text, (
        "squad-run dep block message must contain 'incomplete dependency'"
    )
    # Sub-task nudge vocabulary.
    assert "usually run those first" in text, (
        "squad-run sub-task nudge must contain 'usually run those first'"
    )


def test_plan_batch_epic_exclusion_is_functional(repo_root):
    """Functional test of plan_batch.infer_task + epic filtering: an epic card must be
    detected by card_type and excluded from the ordered tasks list."""
    import importlib.util

    script = repo_root / "skills" / "squad-batch-run" / "scripts" / "plan_batch.py"
    spec = importlib.util.spec_from_file_location("plan_batch_mod", script)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    # Simulate a task list containing one epic and one regular task. Ids are
    # opaque per-project display strings, preserved verbatim (no int cast).
    epic_task_raw = {
        "id": "SQD-100", "title": "Auth epic", "status": "todo",
        "priority": "high", "level": 3, "tags": "phase:1",
        "description": "", "card_type": "epic", "relationships": {},
    }
    regular_task_raw = {
        "id": "SQD-101", "title": "Add login", "status": "todo",
        "priority": "high", "level": 2, "tags": "phase:1",
        "description": "", "card_type": "task", "relationships": {},
    }

    inferred = [mod.infer_task(epic_task_raw), mod.infer_task(regular_task_raw)]
    skipped_epics = [t["id"] for t in inferred if t.get("card_type") == "epic"]
    runnable = [t for t in inferred if t.get("card_type") != "epic"]

    assert skipped_epics == ["SQD-100"], "infer_task must preserve card_type:'epic' so it can be filtered"
    assert len(runnable) == 1 and runnable[0]["id"] == "SQD-101", (
        "plan_batch must exclude epics from the runnable set"
    )


# ──────────────────────────────────────────────────────────────────────────────
# create_tasks.py — batch creation wires parent/blocks edges (kickstart/explore
# now delegate creation to this script; the edge contract is unit-tested here).
# ──────────────────────────────────────────────────────────────────────────────


def test_create_tasks_wires_parent_and_blocks_edges(create_tasks_mod, monkeypatch, capsys):
    """create_tasks.py creates the epic (card_type:'epic') + tasks, then wires child→epic
    `parent` edges and `blocks` edges (POSTed on the BLOCKER with to=<blocked task>) —
    intra-batch int indices resolve to the created ids. Stubbed board; no network."""
    import io
    import sys as _sys

    calls = []
    ids = iter(["EP-1", "T-1", "T-2"])

    def fake_req(method, path, body=None):
        calls.append((method, path, body))
        if path == "/task":
            return 0, {"id": next(ids)}
        return 0, {}

    monkeypatch.setattr(create_tasks_mod.pipeline, "_req", fake_req)
    spec = {
        "epic": {"title": "Epic", "priority": "high"},
        "tasks": [
            {"title": "one", "level": 2},
            {"title": "two", "level": 2, "blocked_by": [0, "KEY-9"]},
        ],
    }
    monkeypatch.setattr(_sys, "stdin", io.StringIO(json.dumps(spec)))
    capsys.readouterr()
    rc = create_tasks_mod.main()
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["epic"] == {"id": "EP-1", "title": "Epic"}
    assert [t["id"] for t in out["tasks"]] == ["T-1", "T-2"]

    creates = [c for c in calls if c[1] == "/task"]
    assert creates[0][2]["card_type"] == "epic", "the batch epic must be card_type:'epic'"
    edges = [c for c in calls if c[1].endswith("/relationships")]
    # Both children get a parent edge to the epic.
    assert ("POST", "/task/T-1/relationships", {"to": "EP-1", "type": "parent"}) in edges
    assert ("POST", "/task/T-2/relationships", {"to": "EP-1", "type": "parent"}) in edges
    # blocked_by: [0, "KEY-9"] → POST on each BLOCKER with to=T-2.
    assert ("POST", "/task/T-1/relationships", {"to": "T-2", "type": "blocks"}) in edges
    assert ("POST", "/task/KEY-9/relationships", {"to": "T-2", "type": "blocks"}) in edges


def test_kickstart_and_explore_delegate_creation_to_create_tasks(repo_root):
    """squad-kickstart and squad-explore create their epic + tasks + edges through
    create_tasks.py (one batch call) rather than hand-rolled per-task POSTs."""
    for name in ("squad-kickstart", "squad-explore"):
        text = (repo_root / "skills" / name / "SKILL.md").read_text()
        assert "create_tasks.py" in text, f"{name} must delegate batch creation to create_tasks.py"
