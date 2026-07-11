"""Contract guards for per-step correlation_id threading.

The contract survived the skills-efficiency re-architecture but the minting
moved into the engine: ``pipeline.py dispatch`` mints ONE fresh uuid-v4 per
agent-step occurrence and threads the SAME id into (a) the rendered agent
prompt (the ``<correlation_id>`` placeholder in the template's Record Results
write) and (b) the META JSON line the orchestrator reads; the orchestrator
then passes ``--cid <META.correlation_id>`` to ``record`` (and ``advance`` on
human reject), and ``pipeline.py record`` forwards it into the ``/activity``
body — so the board groups a step's record-write + activity event into one
timeline entry. A fresh id is minted per occurrence (each dispatch call mints
anew; a reject re-dispatch is a new dispatch).

Doc surfaces: templates carry the ``<correlation_id>`` placeholder in their
Record Results write; ``templates/_shared.md`` instructs agents to pass the
pre-filled value through unchanged; ``references/api.md`` documents the wire
field on the verdict/activity examples; ``schema.md`` (unchanged) documents
the field on every write surface.

Deleted from the old suite (structurally obsolete):
- the SKILL.md bash-mint assertions (``CORRELATION_ID=$(python3 -c …)``,
  ``--set correlation_id=…``, never-cache prose) — minting is engine-owned
  now and is asserted behaviorally against cmd_dispatch;
- the render_agent_prompt.py ``--set`` dry-run — the pipeline renders agent
  prompts via ``_render``, asserted directly.

Hermetic: ``_req`` stubbed; no network.
"""
import json
import re
import uuid
from types import SimpleNamespace


# The 6 pipeline agent templates and the Record-Results write each performs.
_TEMPLATES = [
    "skills/squad/templates/plan-agent.md",
    "skills/squad/templates/worker-agent.md",
    "skills/squad/templates/tdd-tester.md",
    "skills/squad/templates/review-agent.md",
    "skills/squad/templates/code-review-agent.md",
    "skills/squad/templates/test-runner.md",
]


def _stub_req(monkeypatch, pipeline_mod, handler=None):
    calls = []

    def fake_req(method, path, body=None):
        calls.append((method, path, body))
        if handler:
            return handler(method, path, body)
        return 0, {}

    monkeypatch.setattr(pipeline_mod, "_req", fake_req)
    return calls


def _dispatch_handler(method, path, body):
    if method == "GET" and "fields=status,level" in path:
        return 0, {"status": "plan", "level": 2}
    if method == "GET" and path.startswith("/projects/"):
        return 0, {"brief": "Brief"}
    if method == "GET" and path.endswith("/relationships"):
        return 0, {"blocked_by": []}
    if method == "GET":
        return 0, {"title": "T", "description": "D", "spec": None,
                   "plan_review_comments": None}
    return 0, {"success": True}


def _run_dispatch(pipeline_mod, monkeypatch, capsys, task_id="7"):
    monkeypatch.setenv("SQUAD_MODEL_PROVIDER", "claude")
    monkeypatch.setattr(pipeline_mod.api, "resolve_project", lambda: "proj")
    _stub_req(monkeypatch, pipeline_mod, _dispatch_handler)
    pipeline_mod.cmd_dispatch(SimpleNamespace(id=task_id, agent=None))
    out = capsys.readouterr().out
    meta_line, _, prompt = out.partition("-----PROMPT-----")
    meta = json.loads(meta_line.strip().splitlines()[-1])
    return meta, prompt


# ---------------------------------------------------------------------------
# 1. dispatch mints a fresh uuid-v4 and threads it into META AND the prompt
# ---------------------------------------------------------------------------

def test_dispatch_mints_uuid4_and_threads_into_meta_and_prompt(
        pipeline_mod, monkeypatch, capsys):
    meta, prompt = _run_dispatch(pipeline_mod, monkeypatch, capsys)
    cid = meta["correlation_id"]
    assert uuid.UUID(cid).version == 4, "the correlation id must be a uuid-v4"
    assert cid in prompt, (
        "the SAME id must be embedded in the rendered prompt's Record Results "
        "write (the <correlation_id> placeholder)"
    )
    assert "<correlation_id>" not in prompt, (
        "the placeholder must be fully resolved"
    )


def test_dispatch_mints_a_fresh_id_per_occurrence(pipeline_mod, monkeypatch, capsys):
    """Two dispatches (e.g. a reject re-dispatch) must mint DIFFERENT ids —
    never cached/reused across the loop."""
    meta1, _ = _run_dispatch(pipeline_mod, monkeypatch, capsys)
    meta2, _ = _run_dispatch(pipeline_mod, monkeypatch, capsys)
    assert meta1["correlation_id"] != meta2["correlation_id"], (
        "each dispatch occurrence must mint a fresh correlation id"
    )


# ---------------------------------------------------------------------------
# 2. record forwards --cid into the activity body (the threading guarantee)
# ---------------------------------------------------------------------------

def test_record_forwards_cid_into_activity_body(pipeline_mod, monkeypatch, capsys):
    monkeypatch.setenv("SQUAD_MODEL_PROVIDER", "claude")

    def handler(method, path, body):
        if method == "GET":
            return 0, {"status": "impl", "level": 2}
        return 0, {"success": True}

    calls = _stub_req(monkeypatch, pipeline_mod, handler)
    pipeline_mod.cmd_record(SimpleNamespace(
        id="7", agent="builder", message="m", tokens=None, cid="cid-from-meta"))
    capsys.readouterr()
    body = [c for c in calls if c[0] == "POST"][0][2]
    assert body["correlation_id"] == "cid-from-meta", (
        "record must forward the dispatch-minted cid so the board can group "
        "the step's record-write + activity event into one timeline entry"
    )


# ---------------------------------------------------------------------------
# 3. SKILL.md threads META.correlation_id to record and advance
# ---------------------------------------------------------------------------

def test_skill_threads_meta_cid_to_record_and_advance(repo_root):
    text = (repo_root / "skills/squad-run/SKILL.md").read_text()
    assert "correlation_id" in text, "SKILL.md must name the META correlation_id"
    assert re.search(r"record \$ID --agent <META\.agent> --cid <META\.correlation_id>", text), (
        "SKILL.md must pass --cid <META.correlation_id> to record"
    )
    assert re.search(r"advance \$ID --cid <META\.correlation_id>", text), (
        "SKILL.md must pass --cid <META.correlation_id> to advance"
    )


# ---------------------------------------------------------------------------
# 4. All six templates carry the placeholder; _shared.md documents passthrough
# ---------------------------------------------------------------------------

def test_all_six_templates_carry_correlation_id(repo_root):
    missing = []
    for rel in _TEMPLATES:
        text = (repo_root / rel).read_text()
        if "<correlation_id>" not in text or "correlation_id" not in text:
            missing.append(rel)
    assert not missing, (
        f"these templates are missing the correlation_id / <correlation_id> "
        f"placeholder in their Record Results write: {missing}"
    )


def test_shared_rules_document_cid_passthrough(repo_root):
    text = (repo_root / "skills/squad/templates/_shared.md").read_text()
    assert "correlation_id" in text, "_shared.md must document correlation_id"
    assert re.search(r"pre-filled by the orchestrator", text), (
        "_shared.md must say the cid is pre-filled by the orchestrator"
    )
    assert re.search(r"pass it through unchanged", text), (
        "_shared.md must instruct passing the cid through unchanged"
    )


# ---------------------------------------------------------------------------
# 5. references/api.md + schema.md document the wire field
# ---------------------------------------------------------------------------

def test_api_reference_documents_cid_on_writes(repo_root):
    """The wire-doc surface moved from shared.md to references/api.md: the
    verdict POST examples + the activity append + the grouping semantics."""
    text = (repo_root / "skills/squad/references/api.md").read_text()
    assert text.count('"correlation_id"') >= 4, (
        "references/api.md must show correlation_id in the verdict POST "
        "examples (plan-review / review / test-result) AND the activity append"
    )
    assert re.search(r"groups a step.s verdict write \+ activity event", text), (
        "references/api.md must document the grouping semantics (one timeline entry)"
    )


def test_schema_documents_correlation_id(repo_root):
    text = (repo_root / "skills/squad/schema.md").read_text()
    assert "correlation_id" in text, "schema.md must mention correlation_id"
    assert "tokens?, correlation_id?" in text, (
        "schema.md activity append body contract must list correlation_id?"
    )
    assert "Optional `correlation_id` on writes" in text, (
        "schema.md must have the 'Optional correlation_id on writes' section"
    )
    for ep in ("/plan-review", "/review", "/test-result", "/activity"):
        assert ep in text, f"schema.md must reference {ep}"


# ---------------------------------------------------------------------------
# 6. _render resolves the placeholder (the mechanism the dispatch uses)
# ---------------------------------------------------------------------------

def test_render_resolves_correlation_id_placeholder(pipeline_mod, monkeypatch):
    monkeypatch.setenv("SQUAD_MODEL_PROVIDER", "claude")
    fixed = "11111111-2222-4333-8444-555566667777"
    rendered = pipeline_mod._render("plan-agent.md", {"correlation_id": fixed})
    assert fixed in rendered, "the supplied uuid must land in the rendered prompt"
    assert "<correlation_id>" not in rendered, (
        "the <correlation_id> placeholder must be fully resolved"
    )
