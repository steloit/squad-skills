"""Contract guards for agent-attributed writes + step events.

The contract survived the skills-efficiency re-architecture but the mechanism
moved: the per-step activity event is now issued by the engine
(``pipeline.py record``) rather than a SKILL.md bash snippet. The attribution
model is unchanged:

- the per-step event is attributed to the AGENT that did the work
  (``actor: <Nickname>``, ``model: <the agent's resolved model>``), with
  ``tokens`` included only when the orchestrator passed a runtime-reported
  figure — never ``actor: "Orchestrator"``;
- the orchestrator's own machine events keep ``actor: "Orchestrator"``: the
  dispatch entry PATCH, every status-move PATCH (advance/finalize), the
  format-normalize notes and the finalize commit note (``model: "system"``);
- the field-write templates (Planner/Builder/Shield) self-attribute their
  record-write PATCH with ``actor`` + ``model`` in the SAME body;
- the verdict templates (Critic/Inspector/Ranger) carry ``model`` but never a
  self-guessed ``tokens`` figure (the engine's step event is the single token
  source of truth).

Also kept from the old suite (still true, location unchanged): schema.md's
Token Usage Guide is runtime-sourced (never estimated), and no shipped
``skills/**`` file hardcodes a runtime-specific token field name.

Hermetic: ``_req`` is always stubbed; no network.
"""
import json
import re
import subprocess
from types import SimpleNamespace


SKILL_PATH = "skills/squad-run/SKILL.md"
SCHEMA_PATH = "skills/squad/schema.md"

# Field-write templates: the agent PATCHes its own work-product.
_FIELD_WRITE_TEMPLATES = {
    "skills/squad/templates/plan-agent.md": "Planner",
    "skills/squad/templates/worker-agent.md": "Builder",
    "skills/squad/templates/tdd-tester.md": "Shield",
}

# Verdict templates: the agent POSTs a verdict; no self-guessed tokens.
_VERDICT_TEMPLATES = [
    "skills/squad/templates/review-agent.md",
    "skills/squad/templates/code-review-agent.md",
    "skills/squad/templates/test-runner.md",
]

_AGENT_MODEL_KEYS = {
    "Planner": "planner", "Critic": "critic", "Builder": "builder",
    "Shield": "shield", "Inspector": "inspector", "Ranger": "ranger",
}


def _stub_req(monkeypatch, pipeline_mod, handler=None):
    calls = []

    def fake_req(method, path, body=None):
        calls.append((method, path, body))
        if handler:
            return handler(method, path, body)
        return 0, {}

    monkeypatch.setattr(pipeline_mod, "_req", fake_req)
    return calls


def _claude_models(repo_root):
    cfg = json.loads((repo_root / "skills/squad/models.json").read_text())
    return cfg["providers"]["claude"]


def _record_args(**kw):
    base = dict(id="7", agent="builder", message="did the work", tokens=None, cid="cid-1")
    base.update(kw)
    return SimpleNamespace(**base)


def _record_handler(method, path, body):
    if method == "GET":
        return 0, {"status": "impl", "level": 2}
    return 0, {"success": True}


# ──────────────────────────────────────────────────────────────────────────────
# 1. `pipeline.py record` — the per-step event is agent-attributed
# ──────────────────────────────────────────────────────────────────────────────


def test_record_posts_agent_attributed_event(pipeline_mod, repo_root, monkeypatch, capsys):
    monkeypatch.setenv("SQUAD_MODEL_PROVIDER", "claude")
    calls = _stub_req(monkeypatch, pipeline_mod, _record_handler)

    pipeline_mod.cmd_record(_record_args(agent="builder", message="built it"))

    posts = [c for c in calls if c[0] == "POST"]
    assert len(posts) == 1 and posts[0][1] == "/task/7/activity"
    body = posts[0][2]
    assert body["actor"] == "Builder", (
        "the step event must be attributed to the AGENT's nickname"
    )
    assert body["actor"] != "Orchestrator", (
        "the per-step event must never be actor:'Orchestrator'"
    )
    assert body["model"] == _claude_models(repo_root)["builder"], (
        "the step event must carry the agent's own resolved model"
    )
    assert body["message"] == "built it"
    assert body["correlation_id"] == "cid-1"


def test_record_resolves_each_agents_model_from_models_json(
        pipeline_mod, repo_root, monkeypatch, capsys):
    monkeypatch.setenv("SQUAD_MODEL_PROVIDER", "claude")
    models = _claude_models(repo_root)
    for nickname, key in _AGENT_MODEL_KEYS.items():
        calls = _stub_req(monkeypatch, pipeline_mod, _record_handler)
        pipeline_mod.cmd_record(_record_args(agent=nickname.lower()))
        capsys.readouterr()
        body = [c for c in calls if c[0] == "POST"][0][2]
        assert body["actor"] == nickname
        assert body["model"] == models[key], (
            f"{nickname}'s step event must carry models.json's {key} model"
        )


def test_record_includes_tokens_only_when_reported(pipeline_mod, monkeypatch, capsys):
    monkeypatch.setenv("SQUAD_MODEL_PROVIDER", "claude")
    calls = _stub_req(monkeypatch, pipeline_mod, _record_handler)
    pipeline_mod.cmd_record(_record_args(tokens=12345))
    capsys.readouterr()
    body = [c for c in calls if c[0] == "POST"][0][2]
    assert body["tokens"] == 12345

    calls = _stub_req(monkeypatch, pipeline_mod, _record_handler)
    pipeline_mod.cmd_record(_record_args(tokens=None))
    capsys.readouterr()
    body = [c for c in calls if c[0] == "POST"][0][2]
    assert "tokens" not in body, (
        "tokens must be omitted entirely when the runtime reported nothing "
        "(never null, never 0)"
    )


# ──────────────────────────────────────────────────────────────────────────────
# 2. Genuine machine events keep actor:"Orchestrator"
# ──────────────────────────────────────────────────────────────────────────────


def test_dispatch_entry_patch_is_orchestrator(pipeline_mod, monkeypatch, capsys):
    monkeypatch.setenv("SQUAD_MODEL_PROVIDER", "claude")
    monkeypatch.setattr(pipeline_mod.api, "resolve_project", lambda: "proj")

    def handler(method, path, body):
        if method == "GET" and "fields=status,level" in path:
            return 0, {"status": "todo", "level": 2}
        if method == "GET" and path.startswith("/projects/"):
            return 0, {"brief": ""}
        if method == "GET" and path.endswith("/relationships"):
            return 0, {"blocked_by": []}
        if method == "GET":
            return 0, {"title": "T", "description": "D"}
        return 0, {"success": True}

    calls = _stub_req(monkeypatch, pipeline_mod, handler)
    pipeline_mod.cmd_dispatch(SimpleNamespace(id="7", agent=None))
    capsys.readouterr()

    patches = [c for c in calls if c[0] == "PATCH"]
    assert patches, "dispatch must issue the entry PATCH"
    body = patches[0][2]
    assert body["actor"] == "Orchestrator", (
        "the entry PATCH is the orchestrator's own state write"
    )
    assert body["status"] == "plan" and body["current_agent"] == "Planner"


def test_advance_move_patch_is_orchestrator(pipeline_mod, monkeypatch, capsys):
    monkeypatch.setattr(pipeline_mod, "_emit_steering", lambda *a, **k: None)

    def handler(method, path, body):
        if method == "GET":
            return 0, {"status": "plan_review", "level": 3, "version": 2,
                       "plan_review_count": 1, "last_plan_review_status": "approved"}
        return 0, {"success": True}

    calls = _stub_req(monkeypatch, pipeline_mod, handler)
    pipeline_mod.cmd_advance(SimpleNamespace(
        id="7", human_reject=False, reason=None, cid=None, force=False))
    capsys.readouterr()

    patches = [c for c in calls if c[0] == "PATCH"]
    assert patches and patches[0][2] == {
        "status": "impl", "current_agent": None, "actor": "Orchestrator"}


def test_finalize_done_patch_and_commit_note_are_orchestrator(
        pipeline_mod, tmp_path, monkeypatch, capsys):
    repo = tmp_path / "repo"
    repo.mkdir()
    for cmd in (["git", "init", "-q"],
                ["git", "config", "user.email", "t@example.com"],
                ["git", "config", "user.name", "T"],
                ["git", "config", "commit.gpgsign", "false"]):
        subprocess.run(cmd, cwd=repo, check=True)
    (repo / "a.txt").write_text("x\n")
    monkeypatch.chdir(repo)

    def handler(method, path, body):
        if method == "GET":
            return 0, {"id": 7, "title": "t", "level": 2, "status": "impl_review"}
        return 0, {"success": True}

    calls = _stub_req(monkeypatch, pipeline_mod, handler)
    pipeline_mod.cmd_finalize(SimpleNamespace(id="7", approval_tree=None))
    capsys.readouterr()

    patches = [c for c in calls if c[0] == "PATCH"]
    assert patches and patches[0][2]["actor"] == "Orchestrator"
    posts = [c for c in calls if c[0] == "POST"]
    assert posts, "finalize must record the commit event"
    note = posts[0][2]
    assert note["actor"] == "Orchestrator" and note["model"] == "system", (
        "the commit note is a genuine machine event"
    )
    assert note["message"].startswith("Committed ")


def test_normalize_notes_are_orchestrator_system(pipeline_mod, tmp_path, monkeypatch, capsys):
    repo = tmp_path / "repo"
    repo.mkdir()
    for cmd in (["git", "init", "-q"],
                ["git", "config", "user.email", "t@example.com"],
                ["git", "config", "user.name", "T"]):
        subprocess.run(cmd, cwd=repo, check=True)
    (repo / "a.txt").write_text("x\n")
    monkeypatch.chdir(repo)
    monkeypatch.setattr(pipeline_mod, "FORMATTERS", [])
    calls = _stub_req(monkeypatch, pipeline_mod)

    pipeline_mod.cmd_normalize(SimpleNamespace(id="7"))
    capsys.readouterr()

    posts = [c for c in calls if c[0] == "POST"]
    assert posts, "the no-formatter skip must be logged"
    assert posts[0][2]["actor"] == "Orchestrator"
    assert posts[0][2]["model"] == "system"


# ──────────────────────────────────────────────────────────────────────────────
# 3. Field-write templates carry actor + model in the SAME PATCH body
# ──────────────────────────────────────────────────────────────────────────────


def test_field_write_templates_carry_actor_and_model(repo_root):
    missing = []
    for rel, nickname in _FIELD_WRITE_TEMPLATES.items():
        text = (repo_root / rel).read_text()
        has_actor = f"'actor': '{nickname}'" in text
        has_model = f"'model': '<MODEL_{nickname.upper()}>'" in text
        if not (has_actor and has_model):
            missing.append(rel)
    assert not missing, (
        f"these field-write templates must self-attribute their record-write "
        f"with actor+model: {missing}"
    )


def test_field_write_actor_model_in_same_body_as_domain_write(repo_root):
    """actor/model must land in the SAME json.dumps body as the domain field,
    not a separate follow-up write."""
    domain_field = {
        "skills/squad/templates/plan-agent.md": "'plan'",
        "skills/squad/templates/worker-agent.md": "'implementation_notes'",
        "skills/squad/templates/tdd-tester.md": "'implementation_notes'",
    }
    for rel, nickname in _FIELD_WRITE_TEMPLATES.items():
        text = (repo_root / rel).read_text()
        blocks = re.findall(r"```bash\n(.*?)```", text, re.DOTALL)
        patch_blocks = [b for b in blocks if "api PATCH /task/<ID>" in b]
        assert patch_blocks, f"{rel} must PATCH its record-write via the api helper"
        block = patch_blocks[-1]
        assert domain_field[rel] in block, (
            f"{rel}: the PATCH body must carry the domain field"
        )
        assert f"'actor': '{nickname}'" in block, (
            f"{rel}: actor must be in the same PATCH body as the domain write"
        )
        assert "MODEL_" in block, (
            f"{rel}: model must be in the same PATCH body as the domain write"
        )


# ──────────────────────────────────────────────────────────────────────────────
# 4. Verdict templates keep model, never self-guess tokens
# ──────────────────────────────────────────────────────────────────────────────


def test_verdict_templates_drop_token_estimate_keep_model(repo_root):
    for rel in _VERDICT_TEMPLATES:
        text = (repo_root / rel).read_text()
        assert "ESTIMATED_TOKENS" not in text, (
            f"{rel} must not carry a tokens self-guess"
        )
        assert "'tokens'" not in text and '"tokens"' not in text, (
            f"{rel}'s verdict POST body must not carry a tokens field at all "
            "(the engine's step event is the single source of truth)"
        )
        assert "'model'" in text, f"{rel} must still send model in its verdict POST"


def test_estimated_tokens_placeholder_gone_from_skills(repo_root):
    offenders = []
    for path in (repo_root / "skills").rglob("*"):
        if path.is_file() and "ESTIMATED_TOKENS" in path.read_text(encoding="utf-8", errors="ignore"):
            offenders.append(str(path.relative_to(repo_root)))
    assert not offenders, f"<ESTIMATED_TOKENS> self-guess must be gone from skills/**: {offenders}"


# ──────────────────────────────────────────────────────────────────────────────
# 5. schema.md token guidance stays runtime-sourced, portable
# ──────────────────────────────────────────────────────────────────────────────


def test_schema_token_guide_is_runtime_sourced_not_estimated(repo_root):
    text = (repo_root / SCHEMA_PATH).read_text()
    assert "Token Usage Guide" in text, "schema.md must keep the 'Token Usage Guide'"
    assert "Token Estimation Guide" not in text, (
        "schema.md must not resurrect the old 'Token Estimation Guide' heading"
    )
    lowered = text.lower()
    assert "estimate" not in lowered.split("token usage guide")[-1].split("## table")[0], (
        "schema.md's token guidance must not instruct estimating from context size"
    )
    assert "context size" not in lowered, (
        "schema.md must not reference estimating tokens from context size anywhere"
    )
    assert "runtime" in lowered and (
        "per-subagent usage" in lowered or "per-subagent" in lowered
    ), "schema.md's token guidance must source tokens from the runtime's reported usage"
    assert "tokens: null" in text or "`tokens: null`" in text, (
        "schema.md must still say never send tokens: null"
    )
    assert "tokens: 0" in text or "force `tokens: 0`" in text, (
        "schema.md must still say never force tokens: 0"
    )


# ──────────────────────────────────────────────────────────────────────────────
# 6. Portability guard: no runtime-specific token field name in skills/**
# ──────────────────────────────────────────────────────────────────────────────


_CC_SPECIFIC_TOKEN_PATTERNS = [
    re.compile(r"input_tokens", re.IGNORECASE),
    re.compile(r"output_tokens", re.IGNORECASE),
    re.compile(r"usage\.input", re.IGNORECASE),
    re.compile(r"usage\.output", re.IGNORECASE),
    re.compile(r"cache_creation_input_tokens", re.IGNORECASE),
    re.compile(r"cache_read_input_tokens", re.IGNORECASE),
]


def test_no_hardcoded_claude_code_token_field_names(repo_root):
    offenders = []
    for path in (repo_root / "skills").rglob("*"):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for pat in _CC_SPECIFIC_TOKEN_PATTERNS:
            if pat.search(text):
                offenders.append((str(path.relative_to(repo_root)), pat.pattern))
    assert not offenders, f"shipped skills/** must not hardcode CC-specific token fields: {offenders}"
