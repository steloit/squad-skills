"""Structural guards for the activity-endpoint adoption (#314).

#314 migrated every squad skill + docs + templates off the dropped `agent_log`/`notes` JSON
columns onto the board's `task_activities`/`task_comments` model: machine work is recorded as
immutable events via `POST .../task/:id/activity` `{actor, model, message, tokens?}`; the
human `/comment` channel is never written by a skill; readers use a full GET (embedded
`activity`) or `GET .../task/:id/activity`; cross-task token stats use the single
`GET .../activity/stats` aggregate.

Post skills-efficiency re-architecture the contract's homes moved (the CONTRACTS are unchanged):
  - the activity endpoint doc (body, actor vocabulary, reader, embedding caveat) →
    `skills/squad/references/api.md`;
  - the orchestration write path → pipeline.py `event` / `record` (both POST /task/:id/activity;
    unit-tested here with a stubbed `_req` — no network). Skills that used to inline the POST
    now call `pipe event` / `pipe record`; that mediation satisfies the writer contract;
  - token stats → scripts/stats.py (one `/activity/stats` aggregate call, no per-task loop).

These deterministic invariants keep the migration from silently regressing — a re-inlined
`/note` POST, a creeping `?fields=agent_log`, or a re-introduced read-modify-write of the
old JSON blob.
"""
import argparse
import json
import re


# The canonical contract docs MUST document every endpoint (including the human /comment
# channel and the ?fields= embedding caveat) — they are the source of truth, not writers.
# The operational guards below therefore scope to the executable skill files, excluding these.
_CONTRACT_DOCS = {
    "skills/squad/shared.md",
    "skills/squad/schema.md",
    "skills/squad/references/api.md",
}


def _skill_files(repo_root, exclude_contract_docs=False):
    """Authored skill sources (markdown + python), excluding this test file."""
    skills_dir = repo_root / "skills"
    files = list(skills_dir.rglob("*.md")) + list(skills_dir.rglob("*.py"))
    if exclude_contract_docs:
        files = [p for p in files if str(p.relative_to(repo_root)) not in _CONTRACT_DOCS]
    return files


def test_no_skill_posts_to_human_channel(repo_root):
    """No operational skill POSTs to /note (gone) or /comment (human-only) — machine records
    are events. The contract docs legitimately *document* the human channel and are excluded."""
    post_note = re.compile(r"POST[^\n]*/task/[^\n]*/note")
    post_comment = re.compile(r"POST[^\n]*/task/[^\n]*/comment(?![a-zA-Z])")
    offenders = []
    for p in _skill_files(repo_root, exclude_contract_docs=True):
        text = p.read_text()
        if post_note.search(text) or post_comment.search(text):
            offenders.append(str(p.relative_to(repo_root)))
    assert not offenders, f"skills must not POST to the human channel (/note|/comment): {offenders}"


def test_no_fields_agent_log_reads(repo_root):
    """No skill reads the dropped column via ?fields=agent_log (the column is gone everywhere,
    docs included). The ?fields=activity anti-pattern is only *named* in the contract docs'
    embedding rule, so that caveat is checked separately, not banned outright."""
    offenders = []
    for p in _skill_files(repo_root):
        if "fields=agent_log" in p.read_text():
            offenders.append(str(p.relative_to(repo_root)))
    assert not offenders, f"?fields=agent_log reads the dropped column — must be gone: {offenders}"

    # In the operational skill files (not the contract docs), ?fields=activity must not appear
    # as an actual read either — it does not embed.
    activity_offenders = []
    for p in _skill_files(repo_root, exclude_contract_docs=True):
        if "fields=activity" in p.read_text():
            activity_offenders.append(str(p.relative_to(repo_root)))
    assert not activity_offenders, f"?fields=activity does not embed — use a full GET: {activity_offenders}"


def test_no_read_modify_write_agent_log(repo_root):
    """No remaining read-modify-write PATCH of the agent_log JSON blob."""
    rmw = re.compile(r"['\"]agent_log['\"]\s*:\s*json\.dumps")
    offenders = []
    for p in _skill_files(repo_root):
        if rmw.search(p.read_text()):
            offenders.append(str(p.relative_to(repo_root)))
    assert not offenders, f"read-modify-write agent_log PATCH must be gone: {offenders}"


def test_no_pathless_append_to_agent_log(repo_root):
    """No skill instruction still says 'append to agent_log' (the column is gone)."""
    pat = re.compile(r"append[^\n]{0,40}agent_log", re.IGNORECASE)
    offenders = []
    for p in _skill_files(repo_root):
        if pat.search(p.read_text()):
            offenders.append(str(p.relative_to(repo_root)))
    assert not offenders, f"'append to agent_log' guidance must be gone: {offenders}"


def test_token_stats_use_single_aggregate(repo_root, stats_mod):
    """(Was: the SKILL.md python-heredoc stats block.) /squad stats now delegates to
    scripts/stats.py, which uses the single GET /activity/stats aggregate — no per-task loop,
    no dropped agent_log column."""
    import inspect

    src = inspect.getsource(stats_mod.main)
    assert "/activity/stats" in src, "stats.py must call the single GET /activity/stats aggregate"
    assert "/task/" not in src, "stats.py must not loop per-task — one aggregate call only"
    full = (repo_root / "skills" / "squad" / "scripts" / "stats.py").read_text()
    assert "agent_log" not in full, "stats.py must not reference the dropped agent_log column"
    text = (repo_root / "skills" / "squad" / "SKILL.md").read_text()
    assert "stats.py" in text, "/squad stats must delegate to scripts/stats.py"
    assert "agent_log" not in text, "squad/SKILL.md must not reference the dropped agent_log column"


def test_shared_documents_activity_contract(repo_root):
    """references/api.md documents the POST /activity path, the {actor, model, message, tokens?}
    body, the actor vocabulary, and the projected-read (?fields=) embedding caveat."""
    text = (repo_root / "skills" / "squad" / "references" / "api.md").read_text()
    assert re.search(r"api POST /task/\$ID/activity", text), (
        "references/api.md must document the activity append path"
    )
    # The literal body contract: all four keys named together.
    for key in ("actor", "model", "message", "tokens"):
        assert key in text
    # Actor vocabulary.
    for actor in ("Planner", "Critic", "Builder", "Shield", "Inspector", "Ranger",
                  "Orchestrator", "Heartbeat", "Refiner"):
        assert actor in text, f"references/api.md missing actor {actor} in vocabulary"
    # Dedicated reader + the embedding rule (a projected ?fields= read does NOT embed activity).
    assert re.search(r"api GET /task/\$ID/activity", text)
    assert "?fields=" in text, "references/api.md must document the ?fields= projected read"
    assert re.search(r"does NOT embed activity|not embed", text, re.IGNORECASE), (
        "references/api.md must state a ?fields= projected read does not embed activity"
    )


def test_schema_documents_child_tables(repo_root):
    """schema.md documents task_activities/task_comments and drops the agent_log/notes columns."""
    text = (repo_root / "skills" / "squad" / "schema.md").read_text()
    assert "task_activities" in text
    assert "task_comments" in text
    # The dropped columns are gone from the DDL and the column table, and the read-modify-write
    # snippet is gone. (A single prose note that task_activities "replaces the old agent_log
    # column" is fine — it documents the migration, it is not a DDL/column-table/snippet artifact.)
    assert "  agent_log TEXT," not in text, "agent_log must be dropped from the tasks DDL"
    assert "  notes TEXT," not in text, "notes must be dropped from the tasks DDL"
    assert "| `agent_log` |" not in text, "agent_log must be dropped from the column table"
    assert "| `notes` |" not in text, "notes must be dropped from the column table"
    assert "json.dumps({'agent_log'" not in text, "read-modify-write snippet must be gone"


def test_templates_drop_self_append_comment(repo_root):
    """The agent templates no longer imply agent self-append of tokens to agent_log."""
    tpl_dir = repo_root / "skills" / "squad" / "templates"
    for name in ("worker-agent.md", "plan-agent.md", "tdd-tester.md"):
        text = (tpl_dir / name).read_text()
        assert "agent_log" not in text, f"{name} still references agent_log self-append"


# ──────────────────────────────────────────────────────────────────────────────
# Strengthened assertions added by Shield (task #314) — keep the migration from
# silently regressing through partial rewrites or copy-paste of old patterns.
# ──────────────────────────────────────────────────────────────────────────────

# Writer skills that MUST have an activity write path (they all produce machine events).
_WRITER_SKILLS = [
    "squad-run",
    "squad-refine",
    "squad-heartbeat",
    "squad-batch-run",
    "squad-kickstart",
]

# A direct POST reference OR the pipeline.py mediation (`pipe event` / `pipe record` /
# `pipeline.py event`) — pipeline.py itself POSTs /task/:id/activity (unit-tested below).
_ACTIVITY_WRITE_PAT = re.compile(
    r"POST[^\n]*/activity|/activity\?project=|pipe (?:event|record)\b|pipeline\.py['\" ]+event\b",
    re.IGNORECASE,
)


def test_each_writer_skill_references_post_activity(repo_root):
    """Every skill that produces machine events must carry an activity write path — either the
    direct POST /activity reference or the pipeline.py mediation (`pipe event`/`pipe record`).
    This ensures a skill migrated off /note can't silently lose its write path on the next edit."""
    missing = []
    for name in _WRITER_SKILLS:
        text = (repo_root / "skills" / name / "SKILL.md").read_text()
        if not _ACTIVITY_WRITE_PAT.search(text):
            missing.append(name)
    assert not missing, (
        f"These writer skills have no activity write path (POST /activity or pipe event/record) — "
        f"migration may be incomplete: {missing}"
    )


def test_pipeline_event_and_record_post_activity(pipeline_mod, monkeypatch, capsys):
    """The pipeline.py mediation actually writes the activity channel: `event` and `record`
    both POST /task/:id/activity with the {actor, model, message} body (correlation_id when
    given; tokens omitted when unknown, never null). Stubbed board; no network."""
    calls = []
    task = {"id": "SQD-7", "status": "impl", "level": 2,
            "plan_review_count": 0, "impl_review_count": 0}

    def fake_req(method, path, body=None):
        calls.append((method, path, body))
        return (0, task) if method == "GET" else (0, {})

    monkeypatch.setattr(pipeline_mod, "_req", fake_req)

    capsys.readouterr()
    pipeline_mod.cmd_event(argparse.Namespace(
        id="SQD-7", actor="Orchestrator", message="note", model="system",
        cid="cid-1", tokens=None))
    method, path, body = calls[0]
    assert (method, path) == ("POST", "/task/SQD-7/activity")
    assert body["actor"] == "Orchestrator" and body["model"] == "system"
    assert body["message"] == "note" and body["correlation_id"] == "cid-1"
    assert "tokens" not in body, "tokens must be omitted when unknown (never null)"

    calls.clear()
    capsys.readouterr()
    pipeline_mod.cmd_record(argparse.Namespace(
        id="SQD-7", agent="builder", message="built it", tokens=None, cid="cid-2"))
    posts = [c for c in calls if c[0] == "POST"]
    assert posts and posts[0][1] == "/task/SQD-7/activity", "record must POST the activity event"
    assert posts[0][2]["actor"] == "Builder", "record must attribute the event to the agent"
    assert posts[0][2]["correlation_id"] == "cid-2"
    out = json.loads(capsys.readouterr().out)
    assert out["proposed_next"] == "impl_review", "record must report the step verdict bundle"


def test_shared_documents_orchestrator_appends_not_agents(repo_root):
    """Agents do NOT self-append activity — the orchestrator appends on their behalf.
    Post-rewrite this is structural: no agent template instructs an /activity write (agents
    record only their domain artifact/verdict), and squad-run's orchestrator records each step
    via `pipe record` after the agent Task completes."""
    tpl_dir = repo_root / "skills" / "squad" / "templates"
    self_append = re.compile(r"POST[^\n]*/activity|api POST /task/\$ID/activity|pipe (?:event|record)\b")
    offenders = []
    for p in sorted(tpl_dir.glob("*.md")):
        if self_append.search(p.read_text()):
            offenders.append(p.name)
    assert not offenders, (
        f"agent templates must not instruct an activity self-append (orchestrator-only): {offenders}"
    )
    run = (repo_root / "skills" / "squad-run" / "SKILL.md").read_text()
    assert "pipe record" in run, (
        "squad-run's orchestrator must append the step activity via `pipe record` after the Task"
    )
    # Negative assertion: the old wrong guidance must NOT creep back anywhere.
    shared = (repo_root / "skills" / "squad" / "shared.md").read_text()
    assert "All agents → append" not in shared, (
        "shared.md must not resurrect the old 'All agents → append to agent_log' line"
    )


def test_no_bare_note_url_anywhere(repo_root):
    """/note as a URL segment must not appear in any skill file — the endpoint is gone.
    This is a broader guard than the POST-prefixed regex: catches URL strings, variable
    interpolations, and prose references that could mislead an agent into calling the dead endpoint."""
    # Match /note as a URL path segment (not as a word like "implementation_notes" or "# Note:")
    bare_note = re.compile(r"/note\b")
    offenders = []
    for p in _skill_files(repo_root, exclude_contract_docs=True):
        if bare_note.search(p.read_text()):
            offenders.append(str(p.relative_to(repo_root)))
    assert not offenders, f"Skills must not reference the dead /note endpoint: {offenders}"


def test_heartbeat_reads_activity_endpoint_not_fields_param(repo_root):
    """squad-heartbeat must read last-activity via GET .../task/:id/activity (dedicated reader),
    NOT via ?fields=agent_log (dropped column) or ?fields=activity (does not embed)."""
    text = (repo_root / "skills" / "squad-heartbeat" / "SKILL.md").read_text()
    # Must use the dedicated activity reader path.
    assert "/activity" in text, (
        "squad-heartbeat must read activity via GET .../task/:id/activity"
    )
    # Must NOT use the dropped ?fields=agent_log.
    assert "fields=agent_log" not in text, (
        "squad-heartbeat still reads the dropped ?fields=agent_log"
    )
    # Must NOT use ?fields=activity (not embedded — use dedicated reader).
    assert "fields=activity" not in text, (
        "squad-heartbeat uses ?fields=activity which does not embed — use GET /activity"
    )


def test_squad_stats_env_vars_exported_before_python(repo_root, stats_mod):
    """(Was: `export BOARD=`/`export STATS=` before the SKILL.md python3 heredoc.) The bash→python
    env handoff is structurally gone: stats.py now fetches BOTH datasets itself through api.py —
    no environment-variable data handoff exists to break. The surviving contract is that the
    renderer really receives the board + stats payloads it renders."""
    import inspect

    src = inspect.getsource(stats_mod.main)
    assert "/board?summary=true" in src, "stats.py must fetch the board summary itself"
    assert "/activity/stats" in src, "stats.py must fetch the activity aggregate itself"
    full = (repo_root / "skills" / "squad" / "scripts" / "stats.py").read_text()
    assert "os.environ" not in full, (
        "stats.py must not depend on an env-var data handoff (the failure mode the old "
        "export-before-heredoc guard protected against)"
    )


def test_schema_drops_agent_log_from_ddl_and_snippet(repo_root):
    """Stronger than test_schema_documents_child_tables: schema.md must not contain the
    old read-modify-write json.dumps pattern in ANY form, and must not have the column
    listed anywhere in the tasks DDL block."""
    text = (repo_root / "skills" / "squad" / "schema.md").read_text()
    # json.dumps with agent_log — the read-modify-write snippet in any permutation.
    rmw_patterns = [
        "json.dumps({'agent_log'",
        'json.dumps({"agent_log"',
        "\"agent_log\": json.dumps",
        "'agent_log': json.dumps",
    ]
    for pat in rmw_patterns:
        assert pat not in text, (
            f"schema.md still contains read-modify-write pattern: {pat!r}"
        )


def test_coach_template_trajectory_label_uses_activity_not_agent_log(repo_root):
    """coach.md's trajectory input label must say 'activity events', not 'agent_log'.
    The two generic evidence-source mentions ('agent_log moment', 'agent_log line') in the
    rubric description are out of scope (not reader/writer code) and are NOT banned here."""
    text = (repo_root / "skills" / "squad" / "templates" / "coach.md").read_text()
    # The trajectory section's display label.
    assert "activity events" in text, (
        "coach.md trajectory section must be labelled 'activity events', not 'agent_log'"
    )
    # The old label must not appear as the trajectory section header.
    assert "Trajectory (agent_log" not in text, (
        "coach.md trajectory label still says 'agent_log' — should be 'activity events'"
    )
