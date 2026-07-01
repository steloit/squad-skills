"""Contract guards for the token-honesty reframe (#SQD-983).

Builder reworded the per-agent `tokens` guidance (squad-run/SKILL.md step ⑥ +
squad/schema.md Token Usage Guide) from a flat "the orchestrator captures the runtime's
reported usage" statement to an explicit honesty contract: `tokens` is OPTIONAL and
best-effort, populated only from the runtime's OWN reported per-subagent usage when the
runtime exposes one at Task completion, omitted otherwise (never null, never forced 0),
and NEVER orchestrator-estimated (an orchestrator only sees a subagent's final result,
not its internal LLM/tool calls, so any local estimate would structurally undercount).
Per-agent token stats are therefore not presented as a guaranteed or complete accounting.

`actor` + `model` (the reliable per-agent attribution landed by SQD-981) are unchanged
and out of scope here — see test_agent_attribution_contract.py.

A companion maintainer-only capability note (Claude Code exposes usage on background
Task completions, undocumented; Codex unverified; OTel `gen_ai.usage.*` as the portable
target) was added to the repo's own AGENTS.md — it must stay out of shipped `skills/**`,
per the instruction-only / no-runtime-internals constraint.

These are deterministic grep/structural invariants (mirroring
test_agent_attribution_contract.py) — stdlib-only, hermetic, using the shared
`repo_root` fixture.
"""
import re


SKILL_PATH = "skills/squad-run/SKILL.md"
SCHEMA_PATH = "skills/squad/schema.md"
AGENTS_PATH = "AGENTS.md"


def _step6_section(text):
    """Extract the '#### ⑥ Agent-attributed step event' subsection (heading through the
    next '#### ' heading), same scoping used by test_agent_attribution_contract.py."""
    match = re.search(
        r"#### ⑥ Agent-attributed step event(.*?)\n#### ",
        text,
        re.DOTALL,
    )
    assert match, "SKILL.md must have a '#### ⑥ Agent-attributed step event' subsection"
    return match.group(1)


def _schema_token_guide(text):
    """Extract the schema.md 'Token Usage Guide' paragraph, scoped away from the rest of
    the file (mirrors the '## Table' boundary used by the attribution-contract test)."""
    lowered = text.lower()
    assert "token usage guide" in lowered, "schema.md must have a 'Token Usage Guide' section"
    tail = text[lowered.index("token usage guide"):]
    lowered_tail = tail.lower()
    end = lowered_tail.find("## table")
    return tail if end == -1 else tail[:end]


# ──────────────────────────────────────────────────────────────────────────────
# 1. Both touch-points state tokens is OPTIONAL / best-effort, runtime-per-subagent
#    sourced when exposed, omitted (never null/0) otherwise.
# ──────────────────────────────────────────────────────────────────────────────


def test_skill_step6_states_tokens_optional_best_effort(repo_root):
    text = (repo_root / SKILL_PATH).read_text()
    section = _step6_section(text)
    assert "OPTIONAL" in section, (
        "step-⑥ section must state tokens is OPTIONAL"
    )
    assert "best-effort" in section, (
        "step-⑥ section must state tokens is best-effort"
    )
    assert "runtime" in section.lower() and "per-subagent" in section.lower(), (
        "step-⑥ section must source tokens from the runtime's own per-subagent usage"
    )
    assert re.search(r"never\s+(send\s+)?null.{0,20}never.{0,20}0|omit(ted)?.{0,60}never null", section, re.IGNORECASE) or (
        "omit" in section.lower() and "null" in section.lower()
    ), "step-⑥ section must say tokens is omitted (never null/0) when unavailable"


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


# ──────────────────────────────────────────────────────────────────────────────
# 2. Both touch-points say tokens is NOT orchestrator-estimated. SKILL.md has no
#    guard on the word "estimate"; schema.md's existing
#    test_schema_token_guide_is_runtime_sourced_not_estimated forbids "estimate" /
#    "context size" there, so schema.md must instead use the portable phrasing the
#    Builder chose ("never orchestrator-derived, never locally computed").
# ──────────────────────────────────────────────────────────────────────────────


def test_skill_step6_states_not_orchestrator_estimated(repo_root):
    text = (repo_root / SKILL_PATH).read_text()
    section = _step6_section(text)
    assert "orchestrator-estimated" in section.lower(), (
        "step-⑥ section must explicitly say tokens are never orchestrator-estimated"
    )


def test_schema_token_guide_uses_portable_not_estimated_phrasing(repo_root):
    text = (repo_root / SCHEMA_PATH).read_text()
    guide = _schema_token_guide(text)
    lowered = guide.lower()
    # Portable phrasing required, NOT the literal words forbidden by
    # test_schema_token_guide_is_runtime_sourced_not_estimated.
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


# ──────────────────────────────────────────────────────────────────────────────
# 3. Neither touch-point claims per-agent token stats are guaranteed/complete.
# ──────────────────────────────────────────────────────────────────────────────


def test_skill_step6_does_not_claim_guaranteed_complete(repo_root):
    text = (repo_root / SKILL_PATH).read_text()
    section = _step6_section(text)
    lowered = section.lower()
    assert "not guaranteed or complete" in lowered or (
        "not" in lowered and "guaranteed" in lowered and "complete" in lowered
    ), "step-⑥ section must say per-agent token stats are not guaranteed or complete"
    # Negative: no bare affirmative claim of completeness/guarantee.
    assert "guaranteed and complete" not in lowered
    assert re.search(r"(?<!not )(?<!nor )guaranteed accounting", lowered) is None


def test_schema_token_guide_does_not_claim_guaranteed_complete(repo_root):
    text = (repo_root / SCHEMA_PATH).read_text()
    guide = _schema_token_guide(text)
    lowered = guide.lower()
    assert "not a guaranteed or complete accounting" in lowered or (
        "not" in lowered and "guaranteed" in lowered and "complete" in lowered
    ), "schema.md Token Usage Guide must say tokens are not a guaranteed or complete accounting"
    assert "guaranteed and complete" not in lowered


# ──────────────────────────────────────────────────────────────────────────────
# 4. Portability guard: no shipped skills/** file hardcodes a runtime-specific
#    token field name.
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
# 5. The empirical capability note (CC background-only exposure, Codex unverified,
#    OTel gen_ai.usage.* target) lives in the repo's own AGENTS.md, never shipped.
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
    """The empirical 'background Task completions' capability detail is maintainer-only
    (AGENTS.md) — it must not leak into shipped skills/** as a runtime-specific hack."""
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
