"""Contract guards for the token-honesty rule.

The contract survived the skills-efficiency re-architecture but its touch
points moved: the SKILL.md step-⑥ prose was replaced by (a) one orchestrator
instruction in squad-run/SKILL.md — ``--tokens`` is passed ONLY when the
runtime itself reported per-subagent usage, never estimated — and (b) the
engine's omission behavior in ``pipeline.py`` (``record``/``event`` include a
``tokens`` key only for a truthy reported figure: never null, never a forced
0). schema.md's Token Usage Guide (unchanged location) still carries the full
honesty contract: OPTIONAL / best-effort, runtime-sourced, never
orchestrator-derived, not a guaranteed or complete accounting.

The maintainer-only capability note (Claude Code background-Task usage
exposure, Codex unverified, OTel ``gen_ai.usage.*``) stays in the repo's own
AGENTS.md and out of shipped ``skills/**``.

Deleted from the old suite (structurally obsolete): the SKILL.md step-⑥
section assertions (OPTIONAL/best-effort/never-orchestrator-estimated/
not-guaranteed wording) — that section no longer exists; the instruction
survives as the one-line ``--tokens`` rule asserted here, the behavior is
unit-tested against the engine, and the full wording lives in schema.md
(still asserted).

Hermetic: ``_req`` stubbed; no network.
"""
import re
from types import SimpleNamespace


SKILL_PATH = "skills/squad-run/SKILL.md"
SCHEMA_PATH = "skills/squad/schema.md"
AGENTS_PATH = "AGENTS.md"


def _stub_req(monkeypatch, pipeline_mod, handler=None):
    calls = []

    def fake_req(method, path, body=None):
        calls.append((method, path, body))
        if handler:
            return handler(method, path, body)
        return 0, {}

    monkeypatch.setattr(pipeline_mod, "_req", fake_req)
    return calls


def _record_handler(method, path, body):
    if method == "GET":
        return 0, {"status": "impl", "level": 2}
    return 0, {"success": True}


def _schema_token_guide(text):
    lowered = text.lower()
    assert "token usage guide" in lowered, "schema.md must have a 'Token Usage Guide' section"
    tail = text[lowered.index("token usage guide"):]
    lowered_tail = tail.lower()
    end = lowered_tail.find("## table")
    return tail if end == -1 else tail[:end]


# ──────────────────────────────────────────────────────────────────────────────
# 1. The orchestrator instruction: tokens only from runtime-reported usage
# ──────────────────────────────────────────────────────────────────────────────


def test_skill_passes_tokens_only_from_runtime_reported_usage(repo_root):
    text = (repo_root / SKILL_PATH).read_text()
    m = re.search(r"`--tokens`[^\n]*", text)
    assert m, "squad-run/SKILL.md must carry the --tokens instruction"
    line = m.group(0)
    assert re.search(r"runtime reported per-subagent usage", line), (
        "--tokens must be sourced from the runtime's own reported per-subagent usage"
    )
    assert "never estimate" in line, (
        "squad-run/SKILL.md must forbid estimating tokens — an orchestrator "
        "only sees a subagent's final result, so any local figure undercounts"
    )


# ──────────────────────────────────────────────────────────────────────────────
# 2. Engine omission behavior: never null, never a forced 0
# ──────────────────────────────────────────────────────────────────────────────


def test_record_omits_tokens_when_unreported(pipeline_mod, monkeypatch, capsys):
    monkeypatch.setenv("SQUAD_MODEL_PROVIDER", "claude")
    calls = _stub_req(monkeypatch, pipeline_mod, _record_handler)
    pipeline_mod.cmd_record(SimpleNamespace(
        id="7", agent="ranger", message="ran checks", tokens=None, cid=None))
    capsys.readouterr()
    body = [c for c in calls if c[0] == "POST"][0][2]
    assert "tokens" not in body, "unreported usage must omit the tokens key entirely"
    assert None not in body.values(), "no field may be sent as null"


def test_record_never_forces_zero_tokens(pipeline_mod, monkeypatch, capsys):
    monkeypatch.setenv("SQUAD_MODEL_PROVIDER", "claude")
    calls = _stub_req(monkeypatch, pipeline_mod, _record_handler)
    pipeline_mod.cmd_record(SimpleNamespace(
        id="7", agent="ranger", message="ran checks", tokens=0, cid=None))
    capsys.readouterr()
    body = [c for c in calls if c[0] == "POST"][0][2]
    assert "tokens" not in body, (
        "a zero/absent runtime figure must never be forced into tokens: 0"
    )


def test_event_applies_the_same_omission_guard(pipeline_mod, monkeypatch, capsys):
    calls = _stub_req(monkeypatch, pipeline_mod)
    pipeline_mod.cmd_event(SimpleNamespace(
        id="7", actor="Orchestrator", message="note", model="system",
        cid=None, tokens=None))
    capsys.readouterr()
    body = [c for c in calls if c[0] == "POST"][0][2]
    assert "tokens" not in body

    calls = _stub_req(monkeypatch, pipeline_mod)
    pipeline_mod.cmd_event(SimpleNamespace(
        id="7", actor="Orchestrator", message="note", model="system",
        cid=None, tokens=4200))
    capsys.readouterr()
    body = [c for c in calls if c[0] == "POST"][0][2]
    assert body["tokens"] == 4200, "a genuinely reported figure is forwarded"


# ──────────────────────────────────────────────────────────────────────────────
# 3. schema.md keeps the full honesty wording (location unchanged)
# ──────────────────────────────────────────────────────────────────────────────


def test_schema_token_guide_states_optional_best_effort(repo_root):
    text = (repo_root / SCHEMA_PATH).read_text()
    guide = _schema_token_guide(text)
    assert "OPTIONAL" in guide, "schema.md Token Usage Guide must state tokens is OPTIONAL"
    assert "best-effort" in guide, "schema.md Token Usage Guide must state tokens is best-effort"
    assert "runtime" in guide.lower() and "per-subagent" in guide.lower(), (
        "schema.md Token Usage Guide must source tokens from the runtime's own per-subagent usage"
    )
    assert "tokens: null" in guide or "`tokens: null`" in guide, (
        "schema.md Token Usage Guide must still say never send tokens: null"
    )
    assert "tokens: 0" in guide or "force `tokens: 0`" in guide, (
        "schema.md Token Usage Guide must still say never force tokens: 0"
    )


def test_schema_token_guide_uses_portable_not_estimated_phrasing(repo_root):
    text = (repo_root / SCHEMA_PATH).read_text()
    guide = _schema_token_guide(text)
    lowered = guide.lower()
    assert "orchestrator-derived" in lowered or "locally computed" in lowered, (
        "schema.md Token Usage Guide must state tokens are not orchestrator-derived / "
        "not locally computed (portable phrasing for 'not estimated')"
    )
    assert "estimate" not in lowered, (
        "schema.md Token Usage Guide must not reintroduce the forbidden literal 'estimate'"
    )
    assert "context size" not in lowered, (
        "schema.md Token Usage Guide must not reintroduce the forbidden literal 'context size'"
    )


def test_schema_token_guide_does_not_claim_guaranteed_complete(repo_root):
    text = (repo_root / SCHEMA_PATH).read_text()
    guide = _schema_token_guide(text)
    lowered = guide.lower()
    assert "not a guaranteed or complete accounting" in lowered or (
        "not" in lowered and "guaranteed" in lowered and "complete" in lowered
    ), "schema.md Token Usage Guide must say tokens are not a guaranteed or complete accounting"
    assert "guaranteed and complete" not in lowered


# ──────────────────────────────────────────────────────────────────────────────
# 4. Portability guard: no runtime-specific token field name in skills/**
# ──────────────────────────────────────────────────────────────────────────────


_RUNTIME_SPECIFIC_TOKEN_PATTERNS = [
    re.compile(r"input_tokens", re.IGNORECASE),
    re.compile(r"output_tokens", re.IGNORECASE),
    re.compile(r"usage\.input", re.IGNORECASE),
    re.compile(r"usage\.output", re.IGNORECASE),
    re.compile(r"cache_creation_input_tokens", re.IGNORECASE),
    re.compile(r"cache_read_input_tokens", re.IGNORECASE),
]


def test_no_hardcoded_runtime_token_field_names_in_token_guidance(repo_root):
    offenders = []
    for path in (repo_root / "skills").rglob("*"):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for pat in _RUNTIME_SPECIFIC_TOKEN_PATTERNS:
            if pat.search(text):
                offenders.append((str(path.relative_to(repo_root)), pat.pattern))
    assert not offenders, (
        f"shipped skills/** must not hardcode a runtime-specific token field name: {offenders}"
    )


# ──────────────────────────────────────────────────────────────────────────────
# 5. The empirical capability note stays maintainer-only (AGENTS.md, not shipped)
# ──────────────────────────────────────────────────────────────────────────────


def test_agents_md_has_maintainer_token_capability_note(repo_root):
    text = (repo_root / AGENTS_PATH).read_text()
    lowered = text.lower()
    assert "claude code" in lowered and "background" in lowered, (
        "AGENTS.md must document that Claude Code exposes per-subagent usage on "
        "background Task completions"
    )
    assert "codex" in lowered and "unverified" in lowered, (
        "AGENTS.md must note Codex's capability is unverified"
    )
    assert "gen_ai.usage" in text, (
        "AGENTS.md must name the OTel GenAI gen_ai.usage.* model as the portable target"
    )


def test_cc_background_capability_detail_not_in_shipped_skills(repo_root):
    offenders = []
    for path in (repo_root / "skills").rglob("*"):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        lowered = text.lower()
        if "background task completion" in lowered or "background subagent_tokens" in lowered:
            offenders.append(str(path.relative_to(repo_root)))
        if "gen_ai.usage" in text:
            offenders.append(str(path.relative_to(repo_root)))
    assert not offenders, (
        f"empirical CC-background capability detail / gen_ai.usage must stay out of "
        f"shipped skills/**: {offenders}"
    )
