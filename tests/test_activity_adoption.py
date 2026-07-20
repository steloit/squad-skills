"""Structural guards for the activity-endpoint adoption (#314).

#314 migrated every squad skill + docs + templates off the dropped `agent_log`/`notes` JSON
columns onto the board's `task_activities`/`task_comments` model: machine work is recorded as
immutable events via `POST /api/task/:id/activity` `{actor, model, message, tokens?}`; the
human `/comment` channel is never written by a skill; readers use a full GET (embedded
`activity`) or `GET /api/task/:id/activity`; cross-task token stats use the single
`GET /api/activity/stats` aggregate.

These are deterministic grep invariants (mirroring test_coach_dispatch_centralization.py) that
keep the migration from silently regressing — a re-inlined `/note` POST, a creeping
`?fields=agent_log`, or a re-introduced read-modify-write of the old JSON blob.
"""
import re


# The two canonical contract docs MUST document every endpoint (including the human /comment
# channel and the ?fields= embedding caveat) — they are the source of truth, not writers.
# The operational guards below therefore scope to the executable skill files, excluding these.
_CONTRACT_DOCS = {"skills/squad/shared.md", "skills/squad/schema.md"}


def _skill_files(repo_root, exclude_contract_docs=False):
    """Authored skill sources (markdown + python), excluding this test file."""
    skills_dir = repo_root / "skills"
    files = list(skills_dir.rglob("*.md")) + list(skills_dir.rglob("*.py"))
    if exclude_contract_docs:
        files = [p for p in files if str(p.relative_to(repo_root)) not in _CONTRACT_DOCS]
    return files


def test_no_skill_posts_to_human_channel(repo_root):
    """No operational skill POSTs to /note (gone) or /comment (human-only) — machine records
    are events. shared.md/schema.md legitimately *document* the human channel and are excluded."""
    post_note = re.compile(r"POST[^\n]*/api/task/[^\n]*/note")
    post_comment = re.compile(r"POST[^\n]*/api/task/[^\n]*/comment(?![a-zA-Z])")
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


def test_token_stats_use_single_aggregate(repo_root):
    """squad/SKILL.md token stats use the single GET /api/activity/stats aggregate (no per-task loop)."""
    text = (repo_root / "skills" / "squad" / "SKILL.md").read_text()
    assert "/api/activity/stats" in text, "token stats must call GET /api/activity/stats"
    # The aggregate replaces the old per-task agent_log loop entirely.
    assert "agent_log" not in text, "squad/SKILL.md must not reference the dropped agent_log column"


def test_shared_documents_activity_contract(repo_root):
    """shared.md documents the POST /activity path, the {actor, model, message, tokens?} body,
    the actor vocabulary, and the full-read-only embedding rule."""
    text = (repo_root / "skills" / "squad" / "shared.md").read_text()
    assert "POST /api/task/:id/activity" in text, "shared.md must document the activity append path"
    # The literal body contract: all four keys named together.
    for key in ("actor", "model", "message", "tokens"):
        assert key in text
    # Actor vocabulary.
    for actor in ("Planner", "Critic", "Builder", "Shield", "Inspector", "Ranger",
                  "Orchestrator", "Heartbeat", "Refiner"):
        assert actor in text, f"shared.md missing actor {actor} in vocabulary"
    # Full-read-only embedding rule.
    assert "GET /api/task/:id/activity" in text
    assert "?fields=" in text, "shared.md must explain the ?fields= embedding caveat"


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
    for name in ("worker.md", "reviewer.md"):
        text = (tpl_dir / name).read_text()
        assert "agent_log" not in text, f"{name} still references agent_log self-append"


# ──────────────────────────────────────────────────────────────────────────────
# Strengthened assertions added by Shield (task #314) — keep the migration from
# silently regressing through partial rewrites or copy-paste of old patterns.
# ──────────────────────────────────────────────────────────────────────────────

# Writer skills that MUST reference POST /activity (they all produce machine events).
_WRITER_SKILLS = [
    "squad-run",
    "squad-refine",
    "squad-heartbeat",
    "squad-batch-run",
    "squad-kickstart",
]


def test_each_writer_skill_references_post_activity(repo_root):
    """Every skill that produces machine events must reference POST /activity (or /activity?project=).
    This ensures a skill migrated off /note today can't silently lose its write path on the next edit."""
    # A bare reference to /activity (in a POST context) is the minimum bar.
    # We accept: "POST /api/task/:id/activity", "POST.*activity", or "curl_post(...activity..."
    activity_pat = re.compile(r"(?:POST[^\n]*/activity|/activity\?project=|curl_post\b)", re.IGNORECASE)
    missing = []
    for name in _WRITER_SKILLS:
        text = (repo_root / "skills" / name / "SKILL.md").read_text()
        if not activity_pat.search(text):
            missing.append(name)
    assert not missing, (
        f"These writer skills have no reference to POST /activity — "
        f"migration may be incomplete: {missing}"
    )


def test_shared_documents_orchestrator_appends_not_agents(repo_root):
    """shared.md must say agents do NOT self-append (the :585 All-agents→append line is gone).
    The orchestrator does the appending; agents write only their domain field."""
    text = (repo_root / "skills" / "squad" / "shared.md").read_text()
    # Positive assertion: the correct orchestrator-appends wording must be present.
    assert "do NOT self-append" in text or "agents do not self-append" in text.lower(), (
        "shared.md must state that pipeline agents do NOT self-append — "
        "the orchestrating skill appends on their behalf"
    )
    # Negative assertion: the old wrong guidance must NOT be present.
    assert "All agents" not in text or "All agents → append" not in text, (
        "shared.md still contains the old 'All agents → append to agent_log' line — must be removed"
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
    """squad-heartbeat must read last-activity via GET /api/task/:id/activity (dedicated reader),
    NOT via ?fields=agent_log (dropped column) or ?fields=activity (does not embed)."""
    text = (repo_root / "skills" / "squad-heartbeat" / "SKILL.md").read_text()
    # Must use the dedicated activity reader path.
    assert "/activity" in text, (
        "squad-heartbeat must read activity via GET /api/task/:id/activity"
    )
    # Must NOT use the dropped ?fields=agent_log.
    assert "fields=agent_log" not in text, (
        "squad-heartbeat still reads the dropped ?fields=agent_log"
    )
    # Must NOT use ?fields=activity (not embedded — use dedicated reader).
    assert "fields=activity" not in text, (
        "squad-heartbeat uses ?fields=activity which does not embed — use GET /activity"
    )


def test_squad_stats_env_vars_exported_before_python(repo_root):
    """squad/SKILL.md stats block must export BOARD and STATS in the bash layer before the
    python3 heredoc runs — both must appear as `export <VAR>=` assignments so the subprocess
    inherits them via os.environ."""
    text = (repo_root / "skills" / "squad" / "SKILL.md").read_text()
    assert "export BOARD=" in text, (
        "squad/SKILL.md stats block must export BOARD= so the python3 heredoc can read os.environ['BOARD']"
    )
    assert "export STATS=" in text, (
        "squad/SKILL.md stats block must export STATS= so the python3 heredoc can read os.environ['STATS']"
    )
    # And the python layer must consume them via os.environ (not stdin or hardcoded)
    assert "os.environ['BOARD']" in text or 'os.environ["BOARD"]' in text, (
        "squad/SKILL.md python stats block must read BOARD via os.environ"
    )
    assert "os.environ['STATS']" in text or 'os.environ["STATS"]' in text, (
        "squad/SKILL.md python stats block must read STATS via os.environ"
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
