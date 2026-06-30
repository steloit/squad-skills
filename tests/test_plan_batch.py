"""Deterministic unit tests for squad-batch-run's plan_batch.py.

These are pure-function tests — no board, no LLM, no network. They run on every PR.
"""

import pytest


# ── Explicit id-list parsing (opaque strings) ────────────────────────────────
def test_parse_id_list_comma_and_space(plan_batch):
    assert plan_batch.parse_id_list("SQD-500,SQD-501,SQD-504") == ["SQD-500", "SQD-501", "SQD-504"]
    assert plan_batch.parse_id_list("SQD-500 SQD-501 SQD-502") == ["SQD-500", "SQD-501", "SQD-502"]
    assert plan_batch.parse_id_list("SQD-500, SQD-501  SQD-504") == ["SQD-500", "SQD-501", "SQD-504"]


def test_parse_id_list_keeps_opaque_strings(plan_batch):
    # A real id has a non-numeric left side, so a hyphen is NOT a range.
    out = plan_batch.parse_id_list("ENG-42 SG-7")
    assert out == ["ENG-42", "SG-7"]
    assert all(isinstance(i, str) for i in out)


def test_parse_id_list_dedups_preserving_order(plan_batch):
    assert plan_batch.parse_id_list("SQD-500,SQD-500,SQD-501,SQD-500") == ["SQD-500", "SQD-501"]


def test_parse_id_list_rejects_numeric_range(plan_batch):
    for bad in ("500-504", "500~504", "504-500"):
        with pytest.raises(SystemExit) as exc:
            plan_batch.parse_id_list(bad)
        msg = str(exc.value)
        assert "--status" in msg and "--epic" in msg  # message names the new syntax


def test_parse_id_list_rejects_bare_numeric(plan_batch):
    with pytest.raises(SystemExit) as exc:
        plan_batch.parse_id_list("500")
    assert "--tasks" in str(exc.value)


# ── Declarative filters ──────────────────────────────────────────────────────
def test_matches_filters_status(plan_batch):
    task = {"id": "SQD-1", "status": "todo", "tags": "phase:2,auth"}
    assert plan_batch.matches_filters(task, statuses=["todo"], tags=[], phase=None) is True
    assert plan_batch.matches_filters(task, statuses=["impl"], tags=[], phase=None) is False


def test_matches_filters_tag(plan_batch):
    task = {"id": "SQD-1", "status": "todo", "tags": "phase:2,auth"}
    assert plan_batch.matches_filters(task, statuses=[], tags=["auth"], phase=None) is True
    assert plan_batch.matches_filters(task, statuses=[], tags=["billing"], phase=None) is False


def test_matches_filters_phase(plan_batch):
    task = {"id": "SQD-1", "status": "todo", "tags": "phase:2,auth"}
    assert plan_batch.matches_filters(task, statuses=[], tags=[], phase=2) is True
    assert plan_batch.matches_filters(task, statuses=[], tags=[], phase=3) is False


def test_matches_filters_and_combination(plan_batch):
    task = {"id": "SQD-1", "status": "todo", "tags": "phase:2,auth"}
    # all three must hold (AND)
    assert plan_batch.matches_filters(task, statuses=["todo"], tags=["auth"], phase=2) is True
    assert plan_batch.matches_filters(task, statuses=["todo"], tags=["auth"], phase=3) is False
    # omitted filters are no-ops
    assert plan_batch.matches_filters({"id": "X"}, statuses=[], tags=[], phase=None) is True


def test_expand_epic_returns_child_ids(plan_batch):
    rel = {"children": [{"id": "SQD-2", "status": "todo"}, {"id": "SQD-3", "status": "done"}]}
    assert plan_batch.expand_epic(rel) == ["SQD-2", "SQD-3"]
    assert plan_batch.expand_epic({"children": []}) == []
    assert plan_batch.expand_epic({}) == []


# ── Metadata parsers ─────────────────────────────────────────────────────────
def test_parse_phase(plan_batch):
    assert plan_batch.parse_phase("phase:2") == 2
    assert plan_batch.parse_phase("phase:2,api") == 2
    assert plan_batch.parse_phase("api,phase:3,ui") == 3
    assert plan_batch.parse_phase("nophase") is None
    assert plan_batch.parse_phase(None) is None


def test_extract_blocked_by(plan_batch):
    # Dependencies come from the embedded relationships object (.blocked_by), not
    # text — ids are opaque display strings kept verbatim (no int cast).
    out = plan_batch.extract_blocked_by(
        {"relationships": {"blocked_by": [{"id": "SQD-500"}, {"id": "SQD-501"}]}}
    )
    assert out == ["SQD-500", "SQD-501"]
    assert all(isinstance(i, str) for i in out)
    assert plan_batch.extract_blocked_by({"relationships": {"blocked_by": []}}) == []
    assert plan_batch.extract_blocked_by({"relationships": {}}) == []
    assert plan_batch.extract_blocked_by({}) == []


def test_parse_parallel_safe(plan_batch):
    assert plan_batch.parse_parallel_safe("Parallel-safe: yes") is True
    assert plan_batch.parse_parallel_safe("Parallel-safe: safe") is True
    assert plan_batch.parse_parallel_safe("Parallel-safe: NO") is False
    assert plan_batch.parse_parallel_safe("Parallel-safe: maybe") is None
    assert plan_batch.parse_parallel_safe(None) is None


def test_parse_touches_lowercases_and_strips(plan_batch):
    assert plan_batch.parse_touches("Touches: Auth, Billing") == ["auth", "billing"]
    assert plan_batch.parse_touches("Touches: a,,b") == ["a", "b"]
    assert plan_batch.parse_touches(None) == []


def test_extract_tag_modules_filters_generic_and_prefixes(plan_batch):
    assert plan_batch.extract_tag_modules("phase:1,auth,ui") == ["auth"]
    assert plan_batch.extract_tag_modules("explore-x,billing") == ["billing"]
    assert plan_batch.extract_tag_modules("api") == ["api"]  # not generic; kept
    assert plan_batch.extract_tag_modules(None) == []


# ── Inference + sorting ──────────────────────────────────────────────────────
def test_infer_task(plan_batch):
    out = plan_batch.infer_task({
        "id": "SQD-500",
        "title": "T",
        "status": "todo",
        "priority": "high",
        "level": 2,
        "tags": "phase:2,auth",
        "description": "Touches: auth, db\nParallel-safe: yes",
        "relationships": {"blocked_by": [{"id": "SQD-499"}]},
    })
    assert out["id"] == "SQD-500" and isinstance(out["id"], str)
    assert out["phase"] == 2
    assert out["depends_on"] == ["SQD-499"]
    assert out["card_type"] == "task"
    assert out["parallel_safe"] is True
    assert out["module_hints"] == ["auth", "db"]  # sorted, deduped


def test_task_sort_key_orders_by_phase_then_input(plan_batch):
    order = {"SQD-1": 0, "SQD-2": 1}
    a = plan_batch.task_sort_key({"id": "SQD-1", "phase": 2}, order)
    b = plan_batch.task_sort_key({"id": "SQD-2", "phase": 1}, order)
    assert b < a  # phase 1 sorts before phase 2 regardless of input order
    nophase = plan_batch.task_sort_key({"id": "SQD-1", "phase": None}, order)
    assert nophase[0] == 10_000  # missing phase sinks to the end


# ── Parallelization rules ────────────────────────────────────────────────────
def _t(plan_batch, **kw):
    base = {"id": "SQD-1", "status": "todo", "parallel_safe": None, "depends_on": [], "module_hints": []}
    base.update(kw)
    return base


def test_can_parallelize_rejects_non_todo(plan_batch):
    ok, reason = plan_batch.can_parallelize_with_group(
        [_t(plan_batch, id="SQD-1")], _t(plan_batch, id="SQD-2", status="impl"))
    assert ok is False and "not in todo" in reason


def test_can_parallelize_rejects_explicit_no(plan_batch):
    ok, _ = plan_batch.can_parallelize_with_group(
        [_t(plan_batch, id="SQD-1")], _t(plan_batch, id="SQD-2", parallel_safe=False))
    assert ok is False


def test_can_parallelize_rejects_dependency_in_group(plan_batch):
    ok, reason = plan_batch.can_parallelize_with_group(
        [_t(plan_batch, id="SQD-1")], _t(plan_batch, id="SQD-2", depends_on=["SQD-1"]))
    assert ok is False and "depends on" in reason


def test_can_parallelize_rejects_hotspot_overlap(plan_batch):
    ok, reason = plan_batch.can_parallelize_with_group(
        [_t(plan_batch, id="SQD-1", module_hints=["billing"])],
        _t(plan_batch, id="SQD-2", module_hints=["api"]))  # 'api' is a hotspot
    assert ok is False and "hotspot" in reason


def test_can_parallelize_accepts_disjoint_modules(plan_batch):
    ok, _ = plan_batch.can_parallelize_with_group(
        [_t(plan_batch, id="SQD-1", module_hints=["billing"])],
        _t(plan_batch, id="SQD-2", module_hints=["profile"]))
    assert ok is True


# ── Grouping ─────────────────────────────────────────────────────────────────
def test_build_groups_splits_on_phase_boundary(plan_batch):
    tasks = [
        {"id": "SQD-1", "phase": 1, "status": "todo", "parallel_safe": None, "depends_on": [], "module_hints": ["a"]},
        {"id": "SQD-2", "phase": 2, "status": "todo", "parallel_safe": None, "depends_on": [], "module_hints": ["b"]},
    ]
    groups = plan_batch.build_groups(tasks)
    assert len(groups) == 2
    assert all(g["mode"] == "sequential" for g in groups)


def test_build_groups_merges_parallelizable_same_phase(plan_batch):
    tasks = [
        {"id": "SQD-1", "phase": 1, "status": "todo", "parallel_safe": True, "depends_on": [], "module_hints": ["billing"]},
        {"id": "SQD-2", "phase": 1, "status": "todo", "parallel_safe": True, "depends_on": [], "module_hints": ["profile"]},
    ]
    groups = plan_batch.build_groups(tasks)
    assert len(groups) == 1
    assert groups[0]["mode"] == "parallel_candidate"
    assert groups[0]["task_ids"] == ["SQD-1", "SQD-2"]


# ── Auth resolution (env precedence over file) ───────────────────────────────
def test_load_squad_auth_reads_file(plan_batch, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("SQUAD_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("SQUAD_BASE_URL", raising=False)
    (tmp_path / ".squad").mkdir()
    (tmp_path / ".squad" / "auth").write_text("SQUAD_AUTH_TOKEN=filetok\n")
    assert plan_batch.load_squad_auth().get("SQUAD_AUTH_TOKEN") == "filetok"


def test_load_squad_auth_env_overrides_file(plan_batch, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / ".squad").mkdir()
    (tmp_path / ".squad" / "auth").write_text("SQUAD_AUTH_TOKEN=filetok\n")
    monkeypatch.setenv("SQUAD_AUTH_TOKEN", "envtok")
    assert plan_batch.load_squad_auth().get("SQUAD_AUTH_TOKEN") == "envtok"


# ── Single-token resolution (env > bare file line; no per-org promotion) ──────
def test_load_squad_auth_ignores_per_org_lines(plan_batch, tmp_path, monkeypatch):
    """SQD-889: there is a SINGLE SQUAD_AUTH_TOKEN. A legacy per-org line in the
    file is never promoted — even when SQUAD_ORG matches it — the bare
    SQUAD_AUTH_TOKEN is what resolves.
    """
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("SQUAD_AUTH_TOKEN", raising=False)
    (tmp_path / ".squad").mkdir()
    (tmp_path / ".squad" / "auth").write_text(
        "SQUAD_AUTH_TOKEN=baretok\nSQUAD_AUTH_TOKEN_acme=acmetok\n"
    )
    monkeypatch.setenv("SQUAD_ORG", "acme")
    assert plan_batch.load_squad_auth().get("SQUAD_AUTH_TOKEN") == "baretok"


def test_load_squad_auth_env_overrides_file(plan_batch, tmp_path, monkeypatch):
    """Env SQUAD_AUTH_TOKEN wins over the bare file line regardless of SQUAD_ORG."""
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / ".squad").mkdir()
    (tmp_path / ".squad" / "auth").write_text("SQUAD_AUTH_TOKEN=filetok\n")
    monkeypatch.setenv("SQUAD_ORG", "acme")
    monkeypatch.setenv("SQUAD_AUTH_TOKEN", "envtok")
    assert plan_batch.load_squad_auth().get("SQUAD_AUTH_TOKEN") == "envtok"


def test_load_squad_auth_org_irrelevant_to_token(plan_batch, tmp_path, monkeypatch):
    """SQUAD_ORG no longer affects token resolution — same bare token resolves
    whether SQUAD_ORG is set or not.
    """
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("SQUAD_AUTH_TOKEN", raising=False)
    (tmp_path / ".squad").mkdir()
    (tmp_path / ".squad" / "auth").write_text("SQUAD_AUTH_TOKEN=baretok\n")

    monkeypatch.setenv("SQUAD_ORG", "ghost")
    assert plan_batch.load_squad_auth().get("SQUAD_AUTH_TOKEN") == "baretok"

    monkeypatch.delenv("SQUAD_ORG", raising=False)
    assert plan_batch.load_squad_auth().get("SQUAD_AUTH_TOKEN") == "baretok"


def test_load_squad_auth_bare_file_read(plan_batch, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("SQUAD_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("SQUAD_ORG", raising=False)
    (tmp_path / ".squad").mkdir()
    (tmp_path / ".squad" / "auth").write_text("SQUAD_AUTH_TOKEN=filetok\n")
    assert plan_batch.load_squad_auth().get("SQUAD_AUTH_TOKEN") == "filetok"


# ── Graceful no-token cases ───────────────────────────────────────────────────

def test_load_squad_auth_no_bare_token_is_absent(plan_batch, tmp_path, monkeypatch):
    """File has only a legacy per-org line and no bare SQUAD_AUTH_TOKEN.

    Since per-org lines are no longer promoted, load_squad_auth returns
    gracefully with no SQUAD_AUTH_TOKEN key — no KeyError, no crash.
    """
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("SQUAD_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("SQUAD_ORG", raising=False)
    (tmp_path / ".squad").mkdir()
    # Only a legacy per-org key; no bare default
    (tmp_path / ".squad" / "auth").write_text("SQUAD_AUTH_TOKEN_acme=acmetok\n")
    result = plan_batch.load_squad_auth()
    assert result.get("SQUAD_AUTH_TOKEN") is None


def test_load_squad_auth_base_url_from_config(plan_batch, tmp_path, monkeypatch):
    """SQUAD_BASE_URL from ~/.squad/config is returned alongside the bare token —
    verifies config-file resolution still works when the auth block runs.
    """
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("SQUAD_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("SQUAD_BASE_URL", raising=False)
    monkeypatch.delenv("SQUAD_ORG", raising=False)
    squad_dir = tmp_path / ".squad"
    squad_dir.mkdir()
    (squad_dir / "auth").write_text("SQUAD_AUTH_TOKEN=baretok\n")
    (squad_dir / "config").write_text("SQUAD_BASE_URL=https://my.board.example\n")
    result = plan_batch.load_squad_auth()
    assert result.get("SQUAD_AUTH_TOKEN") == "baretok"
    assert result.get("SQUAD_BASE_URL") == "https://my.board.example"


# ── Shield additions: gap coverage ───────────────────────────────────────────
# Builder flagged edges: parse_id_list (empty, whitespace, mixed, bare-in-list),
# matches_filters (multi-value match-any, case-insensitive tags, None/empty tags),
# expand_epic (child sans id, None id, order), task_sort_key same-phase tiebreak,
# split_filter_values helper, infer_task (no tags, tags-without-phase, id type),
# resolve_selection (6 paths via monkeypatched network stubs).


# ── parse_id_list ─────────────────────────────────────────────────────────────

def test_parse_id_list_empty_and_whitespace_returns_empty(plan_batch):
    """Empty, whitespace-only, and comma-only input produce [] without error."""
    assert plan_batch.parse_id_list("") == []
    assert plan_batch.parse_id_list("  ") == []
    assert plan_batch.parse_id_list(",") == []
    assert plan_batch.parse_id_list(" , , ") == []


def test_parse_id_list_token_surrounding_whitespace_trimmed(plan_batch):
    """Extra whitespace and mixed separators around tokens are stripped."""
    assert plan_batch.parse_id_list("  SQD-500  ,  SQD-501  ") == ["SQD-500", "SQD-501"]
    assert plan_batch.parse_id_list("SQD-500\t SQD-501") == ["SQD-500", "SQD-501"]


def test_parse_id_list_single_valid_id(plan_batch):
    """A single display id is returned as a one-element list."""
    assert plan_batch.parse_id_list("SQD-42") == ["SQD-42"]


def test_parse_id_list_mixed_valid_then_bad_range_fails(plan_batch):
    """A numeric range embedded among valid ids fails on the offending token, naming it."""
    with pytest.raises(SystemExit) as exc:
        plan_batch.parse_id_list("SQD-500,500-504,SQD-501")
    assert "500-504" in str(exc.value)


def test_parse_id_list_bare_numeric_in_list_fails(plan_batch):
    """A bare numeric token mixed with valid ids is rejected."""
    with pytest.raises(SystemExit) as exc:
        plan_batch.parse_id_list("SQD-500 500 SQD-501")
    msg = str(exc.value)
    assert "500" in msg and "--tasks" in msg


def test_parse_id_list_tilde_range_message_names_syntax(plan_batch):
    """Tilde range rejection message names the new filter syntax including --tag/--phase."""
    with pytest.raises(SystemExit) as exc:
        plan_batch.parse_id_list("500~504")
    msg = str(exc.value)
    assert "--tasks" in msg
    assert "--tag" in msg or "--phase" in msg


# ── matches_filters ───────────────────────────────────────────────────────────

def test_matches_filters_status_match_any(plan_batch):
    """Within --status CSV, at-least-one match suffices (match-any, not match-all)."""
    task = {"id": "SQD-5", "status": "todo", "tags": ""}
    assert plan_batch.matches_filters(task, statuses=["todo", "impl"], tags=[], phase=None) is True
    assert plan_batch.matches_filters(task, statuses=["impl", "plan"], tags=[], phase=None) is False


def test_matches_filters_tag_match_any(plan_batch):
    """Within --tag CSV, at-least-one match suffices (match-any)."""
    task = {"id": "SQD-5", "status": "todo", "tags": "auth,billing"}
    assert plan_batch.matches_filters(task, statuses=[], tags=["auth", "shipping"], phase=None) is True
    assert plan_batch.matches_filters(task, statuses=[], tags=["devops", "shipping"], phase=None) is False


def test_matches_filters_tag_case_insensitive(plan_batch):
    """matches_filters lowercases task tags before comparing; filter tags come
    pre-lowercased from split_filter_values. A task with mixed-case tag storage
    still matches a lowercase filter tag."""
    task = {"id": "SQD-5", "status": "todo", "tags": "Auth,Billing"}
    # Task tags are lowercased internally by matches_filters; filter tags are
    # pre-lowercased by split_filter_values before being passed here.
    assert plan_batch.matches_filters(task, statuses=[], tags=["auth"], phase=None) is True
    assert plan_batch.matches_filters(task, statuses=[], tags=["billing"], phase=None) is True
    # Confirms split_filter_values lowercases so "BILLING" → "billing" before the call
    assert plan_batch.split_filter_values("BILLING,AUTH") == ["billing", "auth"]


def test_matches_filters_none_tags_field_fails_tag_filter(plan_batch):
    """Task without a 'tags' key fails any tag filter (treated as no tags)."""
    task = {"id": "SQD-5", "status": "todo"}  # no "tags" key at all
    assert plan_batch.matches_filters(task, statuses=[], tags=["auth"], phase=None) is False


def test_matches_filters_empty_tags_string_fails_tag_and_phase(plan_batch):
    """Task with tags='' fails tag and phase filters (empty string → no tag tokens)."""
    task = {"id": "SQD-5", "status": "todo", "tags": ""}
    assert plan_batch.matches_filters(task, statuses=[], tags=["auth"], phase=None) is False
    assert plan_batch.matches_filters(task, statuses=[], tags=[], phase=1) is False


# ── expand_epic ───────────────────────────────────────────────────────────────

def test_expand_epic_skips_children_without_id_key(plan_batch):
    """Children dicts missing the 'id' key are silently omitted."""
    rel = {"children": [{"id": "SQD-2"}, {"status": "todo"}]}  # second has no "id"
    assert plan_batch.expand_epic(rel) == ["SQD-2"]


def test_expand_epic_skips_none_id_children(plan_batch):
    """Children with id=None are omitted."""
    rel = {"children": [{"id": "SQD-3"}, {"id": None}]}
    assert plan_batch.expand_epic(rel) == ["SQD-3"]


def test_expand_epic_preserves_api_order(plan_batch):
    """Children are returned in their original API-listed order."""
    ids = ["SQD-10", "SQD-5", "SQD-20"]
    rel = {"children": [{"id": cid} for cid in ids]}
    assert plan_batch.expand_epic(rel) == ids


# ── task_sort_key ─────────────────────────────────────────────────────────────

def test_task_sort_key_same_phase_tiebreak_by_input_order(plan_batch):
    """Tasks in the same phase are ordered by their position in input_order."""
    order = {"SQD-A": 0, "SQD-B": 1, "SQD-C": 2}
    k0 = plan_batch.task_sort_key({"id": "SQD-A", "phase": 1}, order)
    k1 = plan_batch.task_sort_key({"id": "SQD-B", "phase": 1}, order)
    k2 = plan_batch.task_sort_key({"id": "SQD-C", "phase": 1}, order)
    assert k0 < k1 < k2


# ── split_filter_values ───────────────────────────────────────────────────────

def test_split_filter_values_none_and_empty(plan_batch):
    assert plan_batch.split_filter_values(None) == []
    assert plan_batch.split_filter_values("") == []


def test_split_filter_values_lowercases_and_splits(plan_batch):
    assert plan_batch.split_filter_values("Todo,Impl") == ["todo", "impl"]
    assert plan_batch.split_filter_values("auth billing") == ["auth", "billing"]
    assert plan_batch.split_filter_values(" , done , ") == ["done"]


# ── infer_task edge cases ─────────────────────────────────────────────────────

def test_infer_task_no_tags_yields_none_phase_and_empty_hints(plan_batch):
    """tags=None → phase None, no tag-derived module_hints, no crash."""
    out = plan_batch.infer_task({
        "id": "SQD-900", "title": "No tags", "status": "todo",
        "priority": "medium", "level": 2, "tags": None,
        "description": "", "relationships": {},
    })
    assert out["id"] == "SQD-900"
    assert out["phase"] is None
    assert out["module_hints"] == []


def test_infer_task_tags_without_phase(plan_batch):
    """Tags present but no phase:N tag → phase=None but tag-derived module_hints populated."""
    out = plan_batch.infer_task({
        "id": "SQD-901", "title": "No phase", "status": "todo",
        "priority": "low", "level": 2, "tags": "auth,billing",
        "description": "", "relationships": {},
    })
    assert out["phase"] is None
    assert "auth" in out["module_hints"]
    assert "billing" in out["module_hints"]


def test_infer_task_id_is_string(plan_batch):
    """infer_task must return id as the exact string from the task dict (no cast)."""
    out = plan_batch.infer_task({
        "id": "ENG-77", "title": "x", "status": "todo",
        "priority": "low", "level": 1, "tags": "",
        "description": "", "relationships": {},
    })
    assert out["id"] == "ENG-77"
    assert isinstance(out["id"], str)


# ── resolve_selection (network stubs via monkeypatch) ────────────────────────
# resolve_selection's network paths (fetch_task/fetch_board/fetch_relationships)
# are monkeypatched so these remain pure unit tests with no real board calls.

def test_resolve_selection_explicit_ids_no_filters_passthrough(plan_batch, monkeypatch):
    """Explicit ids + no filters → ids flow through directly; fetch_task NOT called."""
    calls: list = []
    monkeypatch.setattr(plan_batch, "fetch_task", lambda *a, **kw: calls.append(a) or {})
    result = plan_batch.resolve_selection(
        "http://test", "org", "proj", "token", None,
        explicit_ids=["SQD-A", "SQD-B"],
        epic_id=None, statuses=[], tags=[], phase=None,
    )
    assert result == ["SQD-A", "SQD-B"]
    assert calls == [], "fetch_task must NOT be called when there are no filters"


def test_resolve_selection_explicit_ids_with_status_filter(plan_batch, monkeypatch):
    """Explicit ids + status filter → fetches each task and filters by status."""
    tasks = [
        {"id": "SQD-1", "status": "todo", "tags": ""},
        {"id": "SQD-2", "status": "impl", "tags": ""},
    ]
    monkeypatch.setattr(plan_batch, "fetch_task",
        lambda _bu, _org, _proj, tid, _tok, _ssl: next(t for t in tasks if t["id"] == tid))
    result = plan_batch.resolve_selection(
        "http://test", "org", "proj", "token", None,
        explicit_ids=["SQD-1", "SQD-2"],
        epic_id=None, statuses=["todo"], tags=[], phase=None,
    )
    assert result == ["SQD-1"]


def test_resolve_selection_epic_expands_to_children(plan_batch, monkeypatch):
    """Epic id → relationships fetched → children ids returned in order."""
    rel = {"children": [{"id": "SQD-10"}, {"id": "SQD-11"}]}
    monkeypatch.setattr(plan_batch, "fetch_relationships", lambda *a, **kw: rel)
    result = plan_batch.resolve_selection(
        "http://test", "org", "proj", "token", None,
        explicit_ids=[], epic_id="SQD-E1",
        statuses=[], tags=[], phase=None,
    )
    assert result == ["SQD-10", "SQD-11"]


def test_resolve_selection_epic_empty_children_exits(plan_batch, monkeypatch):
    """Epic with no children → empty result → SystemExit with 'no tasks matched'."""
    monkeypatch.setattr(plan_batch, "fetch_relationships", lambda *a, **kw: {"children": []})
    with pytest.raises(SystemExit) as exc:
        plan_batch.resolve_selection(
            "http://test", "org", "proj", "token", None,
            explicit_ids=[], epic_id="SQD-EMPTY",
            statuses=[], tags=[], phase=None,
        )
    assert "no tasks matched" in str(exc.value)


def test_resolve_selection_board_with_status_filter(plan_batch, monkeypatch):
    """No explicit ids, no epic + status filter → fetches whole board, applies filter."""
    board = [
        {"id": "SQD-20", "status": "todo", "tags": "phase:1"},
        {"id": "SQD-21", "status": "done", "tags": "phase:1"},
    ]
    monkeypatch.setattr(plan_batch, "fetch_board", lambda *a, **kw: board)
    result = plan_batch.resolve_selection(
        "http://test", "org", "proj", "token", None,
        explicit_ids=[], epic_id=None,
        statuses=["todo"], tags=[], phase=None,
    )
    assert result == ["SQD-20"]


def test_resolve_selection_empty_result_exits_with_hint(plan_batch, monkeypatch):
    """No tasks survive the filter → SystemExit message names filter flags."""
    monkeypatch.setattr(plan_batch, "fetch_board",
        lambda *a, **kw: [{"id": "SQD-30", "status": "done", "tags": ""}])
    with pytest.raises(SystemExit) as exc:
        plan_batch.resolve_selection(
            "http://test", "org", "proj", "token", None,
            explicit_ids=[], epic_id=None,
            statuses=["todo"], tags=[], phase=None,
        )
    msg = str(exc.value)
    assert "no tasks matched" in msg
    assert "--status" in msg or "--epic" in msg


def test_resolve_selection_dedup_preserving_order(plan_batch, monkeypatch):
    """Duplicate ids in the resolved base are deduped preserving first-seen order."""
    # Simulate board returning two cards with the same id (shouldn't happen in practice,
    # but resolve_selection must be robust).
    board = [
        {"id": "SQD-A", "status": "todo", "tags": ""},
        {"id": "SQD-B", "status": "todo", "tags": ""},
        {"id": "SQD-A", "status": "todo", "tags": ""},  # duplicate
    ]
    monkeypatch.setattr(plan_batch, "fetch_board", lambda *a, **kw: board)
    result = plan_batch.resolve_selection(
        "http://test", "org", "proj", "token", None,
        explicit_ids=[], epic_id=None,
        statuses=["todo"], tags=[], phase=None,
    )
    assert result == ["SQD-A", "SQD-B"]
