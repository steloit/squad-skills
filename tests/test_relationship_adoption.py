"""Structural guards for the unified relationships + epic adoption (#340).

#340 moved every squad skill onto the deployed unified `/relationships` API and the first-class
epic card model from #339:
  - dependency (`blocks`) I/O resolves via `GET /api/task/:id/relationships` → `.blocked_by`
    (the removed `/dependencies` endpoint and the `Depends on:` description-text convention are retired);
  - hierarchy is structured — skills create `card_type:'epic'` cards + `POST /relationships {type:'parent'}`
    edges (the `epic:<name>` tag-as-hierarchy convention is retired);
  - epics are excluded from the agent pipeline (containers), with a soft sub-task readiness nudge.

These are deterministic grep invariants (mirroring test_activity_adoption.py) that keep the
migration from silently regressing — a re-introduced `/dependencies` call, a creeping `Depends on:`
text-parse, or a re-introduced `epic:` hierarchy-tag write.
"""
import re


# The contract doc (shared.md) MUST document the retired conventions and the new endpoints — it is
# the source of truth, not an operational writer/parser. The operational guards below scope to the
# executable skill files, excluding it (mirrors _CONTRACT_DOCS in test_activity_adoption.py).
_CONTRACT_DOCS = {"skills/squad/shared.md", "skills/squad/schema.md"}


def _skill_files(repo_root, exclude_contract_docs=False):
    """Authored skill sources (markdown + python), excluding this test file."""
    skills_dir = repo_root / "skills"
    files = list(skills_dir.rglob("*.md")) + list(skills_dir.rglob("*.py"))
    if exclude_contract_docs:
        files = [p for p in files if str(p.relative_to(repo_root)) not in _CONTRACT_DOCS]
    return files


def test_no_skill_references_dependencies_endpoint(repo_root):
    """The `/dependencies` endpoint is REMOVED (404). No skill — including the contract docs —
    may reference it as a URL path segment."""
    bare_dep = re.compile(r"/dependencies\b")
    offenders = []
    for p in _skill_files(repo_root):
        if bare_dep.search(p.read_text()):
            offenders.append(str(p.relative_to(repo_root)))
    assert not offenders, f"Skills must not reference the removed /dependencies endpoint: {offenders}"


def test_no_skill_parses_depends_on_text(repo_root):
    """No operational skill text-parses the retired `Depends on:` convention. A bare *mention*
    in a 'this is retired' note is fine; what is banned is an extraction (grep/regex/search over
    `Depends on:`). shared.md documents the removal and is excluded."""
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
    tag *value* being written (in a tags string/array or a jq --arg tags). shared.md is excluded."""
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
    """squad-run ⓪ʙ resolves dependencies via GET /relationships → .blocked_by (not text-parse),
    and the old client-side circular-grep is gone."""
    text = (repo_root / "skills" / "squad-run" / "SKILL.md").read_text()
    assert "/relationships" in text, "squad-run must use the /relationships API"
    assert ".blocked_by" in text, "squad-run must read .blocked_by for dependency resolution"
    # The old text-parse extraction must be gone.
    assert "grep -ioP 'Depends on:" not in text, "squad-run still text-parses Depends on:"
    # The client-side circular-dependency check is removed (server returns 409).
    assert "circular dependency detected" not in text, (
        "squad-run still contains the removed client-side circular-dependency check"
    )


def test_squad_run_gates_on_blocked_by_status(repo_root):
    """squad-run's readiness block uses .blocked_by[].status (the hard dependency block)."""
    text = (repo_root / "skills" / "squad-run" / "SKILL.md").read_text()
    assert "blocked_by" in text
    assert "blocked by incomplete dependency" in text, (
        "squad-run must refuse a task blocked by an incomplete dependency in --auto mode"
    )


def test_declaration_skills_post_blocks_relationships(repo_root):
    """squad-refine / squad-batch-run / squad-kickstart each declare a blocks dependency via
    POST /relationships {type:'blocks'}."""
    declarers = ["squad-refine", "squad-batch-run", "squad-kickstart"]
    blocks_pat = re.compile(r"relationships[^\n]*type[^\n]*['\"]blocks['\"]|['\"]blocks['\"][^\n]*relationships")
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


def test_squad_run_and_batch_run_exclude_epics(repo_root):
    """squad-run refuses a card_type='epic' target; squad-batch-run excludes epics from selection."""
    run_text = (repo_root / "skills" / "squad-run" / "SKILL.md").read_text()
    assert "card_type" in run_text and 'CARD_TYPE' in run_text, "squad-run must read card_type for epics"
    assert 'CARD_TYPE" = "epic"' in run_text or '= "epic"' in run_text, (
        "squad-run must branch on card_type == epic"
    )
    assert "is a container" in run_text, "squad-run must refuse epics with a container message"

    batch_text = (repo_root / "skills" / "squad-batch-run" / "SKILL.md").read_text()
    assert "epic" in batch_text and "container" in batch_text, (
        "squad-batch-run must skip epics (containers) in selection"
    )
    # The plan_batch script must also exclude epics from the runnable set.
    plan_batch = (repo_root / "skills" / "squad-batch-run" / "scripts" / "plan_batch.py").read_text()
    assert 'card_type' in plan_batch and 'epic' in plan_batch, (
        "plan_batch.py must exclude card_type=='epic' from the runnable set"
    )


def test_squad_run_reads_children_for_nudge(repo_root):
    """squad-run reads .children to emit the soft sub-task readiness nudge."""
    text = (repo_root / "skills" / "squad-run" / "SKILL.md").read_text()
    assert ".children" in text, "squad-run must read .children for the sub-task nudge"
    assert "sub-task" in text, "squad-run must reference the sub-task nudge"


def test_shared_documents_relationships_and_epics(repo_root):
    """shared.md documents the unified model + endpoints/shapes + epic semantics, and marks BOTH
    the `Depends on:` and `epic:`-tag conventions removed."""
    text = (repo_root / "skills" / "squad" / "shared.md").read_text()
    assert "## Task Relationships & Epics" in text, "shared.md must have the Task Relationships & Epics section"
    # Unified typed model.
    for token in ("blocks", "parent", "card_type", "blocked_by", "children_progress"):
        assert token in text, f"shared.md missing {token}"
    # Endpoints + validation codes.
    assert "/api/task/:id/relationships" in text
    for code in ("400", "404", "409"):
        assert code in text, f"shared.md must document the {code} validation case"
    # The epics aggregate.
    assert "epics" in text, "shared.md must document the /api/board epics aggregate"
    # Both legacy conventions explicitly marked removed.
    assert "REMOVED" in text or "retired" in text.lower()
    assert "Depends on:" in text, "shared.md must name the retired Depends on: convention"
    assert "epic:" in text, "shared.md must name the retired epic: tag convention"


def test_squad_board_summary_reads_epics_aggregate(repo_root):
    """squad/SKILL.md board summaries group by the /api/board epics aggregate / children_progress,
    not tag parsing."""
    text = (repo_root / "skills" / "squad" / "SKILL.md").read_text()
    assert "epics" in text and "children_progress" in text, (
        "squad/SKILL.md board summaries must read the epics aggregate + children_progress"
    )


# ──────────────────────────────────────────────────────────────────────────────
# Strengthened assertions added by Shield (#340) — cover edge cases Builder
# flagged and tighten the guard against silent regressions.
# ──────────────────────────────────────────────────────────────────────────────


def test_squad_run_epic_refusal_handles_zero_children(repo_root):
    """squad-run's epic container refusal must handle zero children by printing '(no children yet)'.
    Builder edge case: epic with no children must still refuse + show the zero-children message."""
    text = (repo_root / "skills" / "squad-run" / "SKILL.md").read_text()
    assert "(no children yet)" in text, (
        "squad-run epic refusal must handle zero children with '(no children yet)' message"
    )
    # The refusal must also print children_progress — even for a zero-child epic.
    assert "children_progress" in text, (
        "squad-run must print children_progress in the epic refusal message"
    )


def test_squad_run_dep_block_precedes_subtask_nudge(repo_root):
    """The dep hard-block must be declared before (and as taking precedence over) the soft nudge.
    Builder edge case: a task BOTH blocked by an incomplete dep AND with open sub-tasks →
    the hard dep block fires first; the nudge is never reached."""
    text = (repo_root / "skills" / "squad-run" / "SKILL.md").read_text()
    # Hard block message (dep) and soft nudge message (sub-task) are both present.
    assert "blocked by incomplete dependency" in text
    assert "open sub-task" in text or "sub-task(s)" in text
    # The dep block is coded in ⓪ʙ and the nudge is in 1b; confirm the
    # skill's own text asserts the precedence ("takes precedence" or equivalent).
    precedence_markers = [
        "takes precedence",
        "dep hard-block",
        "hard block",
        "hard dep block",
        "HARD BLOCK",
        "precedes",
    ]
    assert any(m in text for m in precedence_markers), (
        "squad-run must document that the dep hard-block takes precedence over the soft sub-task nudge"
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
    """shared.md must explicitly say the server enforces acyclicity and that there is NO
    client-side circular-dependency check. This is the normative statement all skills defer to."""
    text = (repo_root / "skills" / "squad" / "shared.md").read_text()
    # The server-enforcement statement must be present.
    assert "enforces acyclicity" in text or "no client-side circular" in text.lower(), (
        "shared.md must document that the server enforces acyclicity (no client-side pre-check)"
    )
    # The 409 cycle response code must be documented.
    assert "409" in text, "shared.md must document the 409 cycle response from POST /relationships"


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
    import importlib.util, types, pathlib

    script = repo_root / "skills" / "squad-batch-run" / "scripts" / "plan_batch.py"
    spec = importlib.util.spec_from_file_location("plan_batch_mod", script)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    # Simulate a task list containing one epic and one regular task.
    epic_task_raw = {
        "id": "100", "title": "Auth epic", "status": "todo",
        "priority": "high", "level": 3, "tags": "phase:1",
        "description": "", "card_type": "epic", "relationships": {},
    }
    regular_task_raw = {
        "id": "101", "title": "Add login", "status": "todo",
        "priority": "high", "level": 2, "tags": "phase:1",
        "description": "", "card_type": "task", "relationships": {},
    }

    inferred = [mod.infer_task(epic_task_raw), mod.infer_task(regular_task_raw)]
    skipped_epics = [t["id"] for t in inferred if t.get("card_type") == "epic"]
    runnable = [t for t in inferred if t.get("card_type") != "epic"]

    assert skipped_epics == [100], "infer_task must preserve card_type:'epic' so it can be filtered"
    assert len(runnable) == 1 and runnable[0]["id"] == 101, (
        "plan_batch must exclude epics from the runnable set"
    )
