"""v2 pipeline contract: the 6-agent role-chain collapsed to Worker + Reviewer.

Guards the 2-agent surface introduced on the v2 branch:
  1. squad-run's dispatch table maps the 5 agent columns onto the two templates
     (worker.md / reviewer.md) with a FOCUS per column.
  2. The verdict→move table and the circuit breakers survive the rewrite.
  3. No file under skills/** references a deleted template filename or a dead
     model key (planner/critic/builder/shield/inspector/ranger).
  4. models.json, render_agent_prompt.py MODEL_KEYS, and the reasoning-effort
     map agree on the surviving key set {refiner, worker, reviewer, coach}.
  5. Correlation-id discipline survives: one fresh uuid per dispatch, threaded
     into the template AND the step's activity POST.
"""
import json
import re

SKILL = "skills/squad-run/SKILL.md"

DEAD_TEMPLATES = [
    "plan-agent.md",
    "review-agent.md",
    "worker-agent.md",
    "tdd-tester.md",
    "code-review-agent.md",
    "test-runner.md",
]

DEAD_MODEL_KEYS = ["planner", "critic", "builder", "shield", "inspector", "ranger"]
LIVE_MODEL_KEYS = {"refiner", "worker", "reviewer", "coach"}


def _skill_text(repo_root):
    return (repo_root / SKILL).read_text()


# ── 1. Dispatch table: 5 columns → 2 templates, one FOCUS each ─────────────────


def test_dispatch_table_maps_five_columns_to_two_templates(repo_root):
    text = _skill_text(repo_root)
    rows = {
        "plan": ("templates/worker.md", "`plan`"),
        "plan_review": ("templates/reviewer.md", "`plan_review`"),
        "impl": ("templates/worker.md", "`impl`"),
        "impl_review": ("templates/reviewer.md", "`impl_review`"),
        "test": ("templates/worker.md", "`test`"),
    }
    for status, (template, focus) in rows.items():
        matches = re.findall(rf"^\|\s*`{status}`\s*\|(.+)$", text, re.MULTILINE)
        assert matches, f"dispatch table missing a row for status {status}"
        assert any(template in m and focus in m for m in matches), (
            f"no row for status {status} dispatches {template} with FOCUS {focus}: {matches}"
        )


def test_templates_exist_with_focus_placeholder(repo_root):
    for name in ("worker.md", "reviewer.md"):
        tpl = (repo_root / "skills" / "squad" / "templates" / name).read_text()
        assert "<FOCUS>" in tpl, f"{name} must carry the <FOCUS> dispatch placeholder"


# ── 2. Verdict→move table + circuit breakers ───────────────────────────────────


def test_verdict_move_table_covers_both_agents(repo_root):
    text = _skill_text(repo_root)
    for anchor in (
        "Worker @ plan",
        "Reviewer @ plan_review",
        "Worker @ impl",
        "Reviewer @ impl_review",
        "Worker @ test",
    ):
        assert anchor in text, f"verdict→move table missing row: {anchor}"


def test_circuit_breakers_survive(repo_root):
    text = _skill_text(repo_root)
    assert "plan_review_count > 3" in text, "plan_review circuit breaker missing"
    assert "impl_review_count > 3" in text, "impl_review circuit breaker missing"


# ── 3. No dead references anywhere in skills/** ────────────────────────────────


def _skill_files(repo_root):
    return [
        p for p in (repo_root / "skills").rglob("*")
        if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"
    ]


def test_no_dead_template_references_in_skills(repo_root):
    offenders = []
    for p in _skill_files(repo_root):
        text = p.read_text(encoding="utf-8", errors="ignore")
        for name in DEAD_TEMPLATES:
            if name in text:
                offenders.append((str(p.relative_to(repo_root)), name))
    assert not offenders, f"deleted template filenames still referenced: {offenders}"


def test_no_dead_model_key_placeholders_in_skills(repo_root):
    # The dead keys as MODEL_/EFFORT_ placeholders or read_model/read_effort lookups.
    pats = [re.compile(rf"MODEL_{k.upper()}|EFFORT_{k.upper()}|read_model {k}\b|read_effort {k}\b")
            for k in DEAD_MODEL_KEYS]
    offenders = []
    for p in _skill_files(repo_root):
        text = p.read_text(encoding="utf-8", errors="ignore")
        for pat in pats:
            m = pat.search(text)
            if m:
                offenders.append((str(p.relative_to(repo_root)), m.group(0)))
    assert not offenders, f"dead model-key references remain: {offenders}"


# ── 4. Key-set agreement: models.json == render_agent_prompt.py ────────────────


def test_models_json_has_exactly_live_keys(repo_root):
    cfg = json.loads((repo_root / "skills" / "squad" / "models.json").read_text())
    for provider, keys in cfg["providers"].items():
        assert set(keys) == LIVE_MODEL_KEYS, (
            f"provider {provider} keys must be exactly {LIVE_MODEL_KEYS}, got {set(keys)}"
        )
    for provider, keys in cfg.get("reasoning_effort", {}).items():
        assert set(keys) <= LIVE_MODEL_KEYS, (
            f"reasoning_effort[{provider}] has dead keys: {set(keys) - LIVE_MODEL_KEYS}"
        )


def test_render_prompt_model_keys_match_models_json(repo_root, render_mod):
    assert set(render_mod.MODEL_KEYS.values()) == LIVE_MODEL_KEYS
    assert set(render_mod.EFFORT_KEYS.values()) == LIVE_MODEL_KEYS
    cfg = json.loads((repo_root / "skills" / "squad" / "models.json").read_text())
    for provider, keys in cfg["providers"].items():
        assert set(render_mod.MODEL_KEYS.values()) == set(keys), (
            f"MODEL_KEYS out of sync with models.json provider {provider}"
        )


# ── 5. Correlation-id discipline (one fresh uuid per dispatch, threaded twice) ─


def test_correlation_id_minted_fresh_per_dispatch(repo_root):
    text = _skill_text(repo_root)
    assert "CORRELATION_ID=$(python3 -c 'import uuid;print(uuid.uuid4())')" in text, (
        "step ② must mint a fresh uuid per dispatch"
    )
    assert re.search(r"never cache or\s+reuse one across the loop", text), (
        "the no-reuse rule for correlation ids must survive"
    )


def test_correlation_id_threaded_into_template_and_activity(repo_root):
    text = _skill_text(repo_root)
    assert '--set correlation_id="$CORRELATION_ID"' in text, (
        "the render call must pass the step's correlation id into the template"
    )
    assert "CID=\"$CORRELATION_ID\"" in text, (
        "the step-⑥ activity POST must carry the SAME correlation id"
    )
