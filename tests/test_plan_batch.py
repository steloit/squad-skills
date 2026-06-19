"""Deterministic unit tests for squad-batch-run's plan_batch.py.

These are pure-function tests — no board, no LLM, no network. They run on every PR.
"""


# ── Selector expansion ───────────────────────────────────────────────────────
def test_expand_selector_range(plan_batch):
    assert plan_batch.expand_selector("500-504") == [500, 501, 502, 503, 504]


def test_expand_selector_reverse_range_normalizes_descending(plan_batch):
    assert plan_batch.expand_selector("504-500") == [504, 503, 502, 501, 500]


def test_expand_selector_tilde_and_comma_and_space(plan_batch):
    assert plan_batch.expand_selector("10~12") == [10, 11, 12]
    assert plan_batch.expand_selector("500,501,504") == [500, 501, 504]
    assert plan_batch.expand_selector("500 501 502") == [500, 501, 502]


def test_expand_selector_dedups_preserving_order(plan_batch):
    assert plan_batch.expand_selector("500,500,501,500") == [500, 501]


# ── Metadata parsers ─────────────────────────────────────────────────────────
def test_parse_phase(plan_batch):
    assert plan_batch.parse_phase("phase:2") == 2
    assert plan_batch.parse_phase("phase:2,api") == 2
    assert plan_batch.parse_phase("api,phase:3,ui") == 3
    assert plan_batch.parse_phase("nophase") is None
    assert plan_batch.parse_phase(None) is None


def test_extract_blocked_by(plan_batch):
    # Dependencies come from the embedded relationships object (.blocked_by), not text.
    assert plan_batch.extract_blocked_by(
        {"relationships": {"blocked_by": [{"id": 500}, {"id": "501"}]}}
    ) == [500, 501]
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
        "id": "500",
        "title": "T",
        "status": "todo",
        "priority": "high",
        "level": 2,
        "tags": "phase:2,auth",
        "description": "Touches: auth, db\nParallel-safe: yes",
        "relationships": {"blocked_by": [{"id": 499}]},
    })
    assert out["id"] == 500 and isinstance(out["id"], int)
    assert out["phase"] == 2
    assert out["depends_on"] == [499]
    assert out["card_type"] == "task"
    assert out["parallel_safe"] is True
    assert out["module_hints"] == ["auth", "db"]  # sorted, deduped


def test_task_sort_key_orders_by_phase_then_input(plan_batch):
    order = {1: 0, 2: 1}
    a = plan_batch.task_sort_key({"id": 1, "phase": 2}, order)
    b = plan_batch.task_sort_key({"id": 2, "phase": 1}, order)
    assert b < a  # phase 1 sorts before phase 2 regardless of input order
    nophase = plan_batch.task_sort_key({"id": 1, "phase": None}, order)
    assert nophase[0] == 10_000  # missing phase sinks to the end


# ── Parallelization rules ────────────────────────────────────────────────────
def _t(plan_batch, **kw):
    base = {"id": 1, "status": "todo", "parallel_safe": None, "depends_on": [], "module_hints": []}
    base.update(kw)
    return base


def test_can_parallelize_rejects_non_todo(plan_batch):
    ok, reason = plan_batch.can_parallelize_with_group(
        [_t(plan_batch, id=1)], _t(plan_batch, id=2, status="impl"))
    assert ok is False and "not in todo" in reason


def test_can_parallelize_rejects_explicit_no(plan_batch):
    ok, _ = plan_batch.can_parallelize_with_group(
        [_t(plan_batch, id=1)], _t(plan_batch, id=2, parallel_safe=False))
    assert ok is False


def test_can_parallelize_rejects_dependency_in_group(plan_batch):
    ok, reason = plan_batch.can_parallelize_with_group(
        [_t(plan_batch, id=1)], _t(plan_batch, id=2, depends_on=[1]))
    assert ok is False and "depends on" in reason


def test_can_parallelize_rejects_hotspot_overlap(plan_batch):
    ok, reason = plan_batch.can_parallelize_with_group(
        [_t(plan_batch, id=1, module_hints=["billing"])],
        _t(plan_batch, id=2, module_hints=["api"]))  # 'api' is a hotspot
    assert ok is False and "hotspot" in reason


def test_can_parallelize_accepts_disjoint_modules(plan_batch):
    ok, _ = plan_batch.can_parallelize_with_group(
        [_t(plan_batch, id=1, module_hints=["billing"])],
        _t(plan_batch, id=2, module_hints=["profile"]))
    assert ok is True


# ── Grouping ─────────────────────────────────────────────────────────────────
def test_build_groups_splits_on_phase_boundary(plan_batch):
    tasks = [
        {"id": 1, "phase": 1, "status": "todo", "parallel_safe": None, "depends_on": [], "module_hints": ["a"]},
        {"id": 2, "phase": 2, "status": "todo", "parallel_safe": None, "depends_on": [], "module_hints": ["b"]},
    ]
    groups = plan_batch.build_groups(tasks)
    assert len(groups) == 2
    assert all(g["mode"] == "sequential" for g in groups)


def test_build_groups_merges_parallelizable_same_phase(plan_batch):
    tasks = [
        {"id": 1, "phase": 1, "status": "todo", "parallel_safe": True, "depends_on": [], "module_hints": ["billing"]},
        {"id": 2, "phase": 1, "status": "todo", "parallel_safe": True, "depends_on": [], "module_hints": ["profile"]},
    ]
    groups = plan_batch.build_groups(tasks)
    assert len(groups) == 1
    assert groups[0]["mode"] == "parallel_candidate"
    assert groups[0]["task_ids"] == [1, 2]


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


# ── Org-scoped resolution (env > per-org line > bare default) ─────────────────
def test_load_squad_auth_per_org_line(plan_batch, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("SQUAD_AUTH_TOKEN", raising=False)
    (tmp_path / ".squad").mkdir()
    (tmp_path / ".squad" / "auth").write_text(
        "SQUAD_AUTH_TOKEN=baretok\nSQUAD_AUTH_TOKEN_acme=acmetok\n"
    )
    monkeypatch.setenv("SQUAD_ORG", "acme")
    assert plan_batch.load_squad_auth().get("SQUAD_AUTH_TOKEN") == "acmetok"


def test_load_squad_auth_env_overrides_per_org(plan_batch, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / ".squad").mkdir()
    (tmp_path / ".squad" / "auth").write_text("SQUAD_AUTH_TOKEN_acme=acmetok\n")
    monkeypatch.setenv("SQUAD_ORG", "acme")
    monkeypatch.setenv("SQUAD_AUTH_TOKEN", "envtok")
    assert plan_batch.load_squad_auth().get("SQUAD_AUTH_TOKEN") == "envtok"


def test_load_squad_auth_unknown_org_falls_back_to_default(plan_batch, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("SQUAD_AUTH_TOKEN", raising=False)
    (tmp_path / ".squad").mkdir()
    (tmp_path / ".squad" / "auth").write_text(
        "SQUAD_AUTH_TOKEN=baretok\nSQUAD_AUTH_TOKEN_acme=acmetok\n"
    )
    monkeypatch.setenv("SQUAD_ORG", "ghost")
    assert plan_batch.load_squad_auth().get("SQUAD_AUTH_TOKEN") == "baretok"


def test_load_squad_auth_no_org_uses_default(plan_batch, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("SQUAD_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("SQUAD_ORG", raising=False)
    (tmp_path / ".squad").mkdir()
    (tmp_path / ".squad" / "auth").write_text(
        "SQUAD_AUTH_TOKEN=baretok\nSQUAD_AUTH_TOKEN_acme=acmetok\n"
    )
    assert plan_batch.load_squad_auth().get("SQUAD_AUTH_TOKEN") == "baretok"


def test_load_squad_auth_hyphenated_org(plan_batch, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("SQUAD_AUTH_TOKEN", raising=False)
    (tmp_path / ".squad").mkdir()
    (tmp_path / ".squad" / "auth").write_text("SQUAD_AUTH_TOKEN_acme-eu=eutok\n")
    monkeypatch.setenv("SQUAD_ORG", "acme-eu")
    assert plan_batch.load_squad_auth().get("SQUAD_AUTH_TOKEN") == "eutok"


def test_load_squad_auth_bare_only_backcompat(plan_batch, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("SQUAD_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("SQUAD_ORG", raising=False)
    (tmp_path / ".squad").mkdir()
    (tmp_path / ".squad" / "auth").write_text("SQUAD_AUTH_TOKEN=filetok\n")
    assert plan_batch.load_squad_auth().get("SQUAD_AUTH_TOKEN") == "filetok"


# ── Graceful no-token cases ───────────────────────────────────────────────────

def test_load_squad_auth_org_set_no_match_no_bare_default_is_absent(plan_batch, tmp_path, monkeypatch):
    """SQUAD_ORG set but file has no matching per-org line AND no bare default.

    load_squad_auth must return gracefully with no SQUAD_AUTH_TOKEN key —
    no KeyError, no crash.  This is the 'wrong org label' user error case.
    """
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("SQUAD_AUTH_TOKEN", raising=False)
    (tmp_path / ".squad").mkdir()
    # Only the acme org key; no bare default; SQUAD_ORG points at a different org
    (tmp_path / ".squad" / "auth").write_text("SQUAD_AUTH_TOKEN_acme=acmetok\n")
    monkeypatch.setenv("SQUAD_ORG", "ghost")
    result = plan_batch.load_squad_auth()
    assert result.get("SQUAD_AUTH_TOKEN") is None


def test_load_squad_auth_per_org_not_promoted_without_squad_org(plan_batch, tmp_path, monkeypatch):
    """A per-org line present in the file must NOT be silently promoted when
    SQUAD_ORG is unset — the bare default (or nothing) must be used instead.

    Guards the invariant that per-org promotion is gated strictly on the
    SQUAD_ORG env var, not on a file scan.
    """
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("SQUAD_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("SQUAD_ORG", raising=False)
    (tmp_path / ".squad").mkdir()
    # Only a per-org key; no SQUAD_ORG in env; no bare default
    (tmp_path / ".squad" / "auth").write_text("SQUAD_AUTH_TOKEN_acme=acmetok\n")
    result = plan_batch.load_squad_auth()
    assert result.get("SQUAD_AUTH_TOKEN") is None


def test_load_squad_auth_base_url_from_config_alongside_org_token(plan_batch, tmp_path, monkeypatch):
    """SQUAD_BASE_URL from ~/.squad/config is returned alongside the per-org
    token — verifies config-file resolution still works when the auth block runs.
    """
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("SQUAD_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("SQUAD_BASE_URL", raising=False)
    squad_dir = tmp_path / ".squad"
    squad_dir.mkdir()
    (squad_dir / "auth").write_text(
        "SQUAD_AUTH_TOKEN=baretok\nSQUAD_AUTH_TOKEN_acme=acmetok\n"
    )
    (squad_dir / "config").write_text("SQUAD_BASE_URL=https://my.board.example\n")
    monkeypatch.setenv("SQUAD_ORG", "acme")
    result = plan_batch.load_squad_auth()
    assert result.get("SQUAD_AUTH_TOKEN") == "acmetok"
    assert result.get("SQUAD_BASE_URL") == "https://my.board.example"
