"""Gap-coverage tests for per-step correlation_id threading.

Companion to ``test_correlation_id_threading.py`` — covers gaps rather than
duplicating it. Post-re-architecture the id is minted inside
``pipeline.py::cmd_dispatch`` and rendered by ``_render``.

Gaps covered here:

1. Per-template ``<correlation_id>`` inside the actual Record Results code
   block (the request payload), not just anywhere in the file.
2. Single-mint invariant — ONE ``uuid.uuid4()`` call per dispatch feeds BOTH
   the META line and the rendered prompt (replaces the old SKILL.md
   mint-before-use text-ordering check).
3. ``advance --human-reject`` forwards the SAME --cid into the override-review
   body (the human-gate write is part of the step's timeline group).
4. No platform internals (backend package names, Drizzle, uuidv7, internal
   file paths) leaked into the shipped docs that carry the correlation_id
   contract — extended to the new hub/reference/template-shared files.
5. schema.md's "Optional correlation_id on writes" section still names PATCH
   as one of the surfaces.

Deleted (structurally obsolete): the shared.md activity-append JSON example
check — the activity/verdict wire examples moved to references/api.md, covered
by the companion file.

Hermetic: ``_req`` stubbed; no network.
"""
import json
import re
import uuid
from types import SimpleNamespace


# The 6 pipeline agent templates.
_TEMPLATES = {
    "plan-agent":        "skills/squad/templates/plan-agent.md",
    "worker-agent":      "skills/squad/templates/worker-agent.md",
    "tdd-tester":        "skills/squad/templates/tdd-tester.md",
    "review-agent":      "skills/squad/templates/review-agent.md",
    "code-review-agent": "skills/squad/templates/code-review-agent.md",
    "test-runner":       "skills/squad/templates/test-runner.md",
}

# Backend internals that must never appear in the shipped skill docs.
_INTERNALS = [
    "@squad/",
    "drizzle",
    "uuidv7",
    "packages/db",
    "packages/auth",
    "packages/services",
    "apps/api",
    "apps/worker",
    "src/server.ts",
    "src/worker.ts",
]

_DOC_FILES = [
    "skills/squad-run/SKILL.md",
    "skills/squad/SKILL.md",
    "skills/squad/schema.md",
    "skills/squad/shared.md",
    "skills/squad/templates/_shared.md",
    "skills/squad/references/api.md",
] + list(_TEMPLATES.values())


def _stub_req(monkeypatch, pipeline_mod, handler=None):
    calls = []

    def fake_req(method, path, body=None):
        calls.append((method, path, body))
        if handler:
            return handler(method, path, body)
        return 0, {}

    monkeypatch.setattr(pipeline_mod, "_req", fake_req)
    return calls


# ---------------------------------------------------------------------------
# 1. <correlation_id> lives in the Record Results code block itself
# ---------------------------------------------------------------------------

def test_per_template_correlation_id_in_record_results_payload(repo_root):
    """The placeholder must be in the Record Results request payload (the
    fenced code block), not just a prose comment elsewhere in the file."""
    missing = []
    for name, rel in _TEMPLATES.items():
        text = (repo_root / rel).read_text()
        results_idx = text.find("## Record Results")
        assert results_idx != -1, f"{name}: no '## Record Results' section found"
        results_section = text[results_idx:]
        code_blocks = re.findall(r"```bash\n(.*?)```", results_section, re.DOTALL)
        code_blocks += re.findall(r"```\n(.*?)```", results_section, re.DOTALL)
        combined = "\n".join(code_blocks)
        if "correlation_id" not in combined or "<correlation_id>" not in combined:
            missing.append(name)
    assert not missing, (
        f"these templates do NOT carry `correlation_id` + `<correlation_id>` in "
        f"their Record Results code block: {missing}"
    )


# ---------------------------------------------------------------------------
# 2. single-mint invariant: one uuid4 call feeds META AND the prompt
# ---------------------------------------------------------------------------

def test_dispatch_single_mint_feeds_meta_and_prompt(pipeline_mod, monkeypatch, capsys):
    monkeypatch.setenv("SQUAD_MODEL_PROVIDER", "claude")
    monkeypatch.setattr(pipeline_mod.api, "resolve_project", lambda: "proj")

    def handler(method, path, body):
        if method == "GET" and "fields=status,level" in path:
            return 0, {"status": "plan", "level": 2}
        if method == "GET" and path.startswith("/projects/"):
            return 0, {"brief": ""}
        if method == "GET" and path.endswith("/relationships"):
            return 0, {"blocked_by": []}
        if method == "GET":
            return 0, {"title": "T", "description": "D"}
        return 0, {"success": True}

    _stub_req(monkeypatch, pipeline_mod, handler)

    fixed = uuid.UUID("11111111-2222-4333-8444-555566667777")
    mints = []

    def counting_uuid4():
        mints.append(1)
        return fixed

    monkeypatch.setattr(pipeline_mod.uuid, "uuid4", counting_uuid4)
    pipeline_mod.cmd_dispatch(SimpleNamespace(id="7", agent=None))
    out = capsys.readouterr().out

    assert len(mints) == 1, "dispatch must mint exactly ONE id per occurrence"
    meta_line, _, prompt = out.partition("-----PROMPT-----")
    meta = json.loads(meta_line.strip().splitlines()[-1])
    assert meta["correlation_id"] == str(fixed)
    assert str(fixed) in prompt, (
        "the one minted id must feed BOTH the META line and the rendered prompt"
    )


# ---------------------------------------------------------------------------
# 3. human-reject override carries the same --cid
# ---------------------------------------------------------------------------

def test_human_reject_override_carries_the_step_cid(pipeline_mod, monkeypatch, capsys):
    monkeypatch.setattr(pipeline_mod, "_emit_steering", lambda *a, **k: None)
    reads = {"n": 0}

    def handler(method, path, body):
        if method == "GET":
            reads["n"] += 1
            if reads["n"] == 1:
                return 0, {"status": "impl_review", "level": 2, "version": 7,
                           "impl_review_count": 1, "last_review_status": "approved"}
            return 0, {"status": "impl_review", "level": 2,
                       "impl_review_count": 1,
                       "last_review_status": "changes_requested"}
        return 0, {"success": True}

    calls = _stub_req(monkeypatch, pipeline_mod, handler)
    pipeline_mod.cmd_advance(SimpleNamespace(
        id="7", human_reject=True, reason="wrong shape", cid="step-cid", force=False))
    capsys.readouterr()

    overrides = [c for c in calls if c[0] == "POST" and "override-review" in c[1]]
    assert overrides, "the human reject must POST /override-review"
    assert overrides[0][2]["correlation_id"] == "step-cid", (
        "the override write must join the step's timeline group via the same cid"
    )


# ---------------------------------------------------------------------------
# 4. no platform internals in the shipped docs carrying this contract
# ---------------------------------------------------------------------------

def test_no_platform_internals_in_doc_text(repo_root):
    leaks = []
    for rel in _DOC_FILES:
        text = (repo_root / rel).read_text()
        for internal in _INTERNALS:
            if internal in text:
                leaks.append(f"{rel}: contains '{internal}'")
    assert not leaks, (
        f"platform internals must never appear in shipped skill docs "
        f"(API-contract-only rule): {leaks}"
    )


# ---------------------------------------------------------------------------
# 5. schema.md's correlation_id section still names PATCH
# ---------------------------------------------------------------------------

def test_schema_md_patch_endpoint_named_in_correlation_id_section(repo_root):
    text = (repo_root / "skills" / "squad" / "schema.md").read_text()
    section_idx = text.find("### Optional `correlation_id` on writes")
    assert section_idx != -1, (
        "schema.md: '### Optional correlation_id on writes' section not found"
    )
    next_heading = text.find("\n###", section_idx + 1)
    section = text[section_idx:next_heading] if next_heading != -1 else text[section_idx:]
    assert "PATCH" in section, (
        "schema.md 'Optional correlation_id on writes' section must name PATCH "
        "as one of the surfaces that accepts the field"
    )
    for ep in ("/plan-review", "/review", "/test-result", "/activity"):
        assert ep in section, (
            f"schema.md 'Optional correlation_id on writes' section must mention {ep}"
        )
