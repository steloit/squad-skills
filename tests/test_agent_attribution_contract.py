"""Contract guards for agent-attributed writes + step events (#SQD-981).

Design A (client-only, builds on the shipped SQD-980 server contract): the AGENT that
does the work self-attributes its record-write (`actor:<Nickname>`, `model:<its model>`),
and the ORCHESTRATOR — the only component that sees a subagent's real runtime usage —
attributes the per-step activity event to that SAME agent (`actor:<Nickname>`,
`model:<agent model>`, `tokens:<runtime usage>`), never `actor:"Orchestrator"`. Only the
orchestrator's OWN machine events (status-move PATCHes, the format-normalize note, the
commit note) keep `actor:"Orchestrator"`. A step's tokens are recorded ONCE — on the
orchestrator's per-step event — so the verdict templates (Critic/Inspector/Ranger) drop
their self-guessed `tokens:<ESTIMATED_TOKENS>` (an agent cannot know its own usage) while
keeping `model`. The token source is described in portable, runtime-agnostic prose (never
a hardcoded Claude-Code field name) so any agent runtime can resolve its own equivalent.

These are deterministic grep/structural invariants (mirroring
test_activity_adoption.py / test_correlation_id_threading.py) — stdlib-only, hermetic,
using the shared `repo_root` fixture.
"""
import re


SKILL_PATH = "skills/squad-run/SKILL.md"
SCHEMA_PATH = "skills/squad/schema.md"

# Field-write templates: agent PATCHes its own work-product (plan / implementation_notes).
_FIELD_WRITE_TEMPLATES = {
    "skills/squad/templates/plan-agent.md": "Planner",
    "skills/squad/templates/worker-agent.md": "Builder",
    "skills/squad/templates/tdd-tester.md": "Shield",
}

# Verdict templates: agent POSTs a verdict; token estimate must be dropped, model kept.
_VERDICT_TEMPLATES = [
    "skills/squad/templates/review-agent.md",
    "skills/squad/templates/code-review-agent.md",
    "skills/squad/templates/test-runner.md",
]


def _step6_section(text):
    """Extract the '#### ⑥ Agent-attributed step event' subsection (heading through the
    next '#### ' heading) so assertions can be scoped away from the surrounding
    orchestrator machine-event snippets (format-normalize / commit note) that legitimately
    keep `actor:"Orchestrator"`."""
    match = re.search(
        r"#### ⑥ Agent-attributed step event(.*?)\n#### ",
        text,
        re.DOTALL,
    )
    assert match, "SKILL.md must have a '#### ⑥ Agent-attributed step event' subsection"
    return match.group(1)


def _step6_bash_block(text):
    """Extract just the ~~~bash ... ~~~ fenced snippet inside the step-⑥ section — the
    concrete, copy-pasteable POST body."""
    section = _step6_section(text)
    match = re.search(r"~~~bash(.*?)~~~", section, re.DOTALL)
    assert match, "step-⑥ section must contain a ~~~bash ... ~~~ snippet"
    return match.group(1)


# ──────────────────────────────────────────────────────────────────────────────
# 1. Step ⑥ activity POST is agent-attributed (actor/model/tokens/correlation_id),
#    scoped to the step-⑥ section so the file's other genuine actor:"Orchestrator"
#    lines (status moves / format-normalize / commit) don't collide.
# ──────────────────────────────────────────────────────────────────────────────


def test_step6_snippet_is_agent_attributed(repo_root):
    """The step-⑥ concrete snippet sets actor to the agent's nickname (a variable, not a
    literal 'Orchestrator'), carries the agent's model, sources tokens from the runtime's
    reported per-subagent usage, and threads correlation_id."""
    text = (repo_root / SKILL_PATH).read_text()
    snippet = _step6_bash_block(text)

    assert "os.environ['AGENT_NICK']" in snippet, (
        "step-⑥ snippet must set actor from the agent's own nickname (AGENT_NICK), "
        "not a hardcoded value"
    )
    assert "os.environ['AGENT_MODEL']" in snippet, (
        "step-⑥ snippet must set model from the agent's own resolved model (AGENT_MODEL)"
    )
    assert "STEP_TOKENS" in snippet, (
        "step-⑥ snippet must source tokens from the runtime's reported per-subagent usage "
        "(STEP_TOKENS), not a manual estimate"
    )
    assert "correlation_id" in snippet, "step-⑥ snippet must carry correlation_id"
    assert '"CID"' in snippet or "CID=" in snippet, (
        "step-⑥ snippet must thread the step's $CORRELATION_ID via CID"
    )

    # Negative: the concrete POST body itself must NOT hardcode actor:"Orchestrator".
    assert 'actor: "Orchestrator"' not in snippet and "actor:\"Orchestrator\"" not in snippet, (
        "step-⑥ agent-attributed snippet must NOT hardcode actor:\"Orchestrator\""
    )
    assert "'Orchestrator'" not in snippet, (
        "step-⑥ agent-attributed snippet must NOT reference 'Orchestrator' as the actor value"
    )


def test_step6_omits_tokens_when_runtime_reports_nothing(repo_root):
    """The step-⑥ snippet must omit the tokens key entirely (never null, never 0) when the
    runtime's usage signal is empty — an `if tok:` (or equivalent truthy) guard, not an
    unconditional assignment."""
    text = (repo_root / SKILL_PATH).read_text()
    snippet = _step6_bash_block(text)
    assert re.search(r"if\s+tok\s*:\s*b\[['\"]tokens['\"]\]", snippet), (
        "step-⑥ snippet must guard the 'tokens' key assignment so it's omitted when the "
        "runtime reports nothing (never null/0)"
    )
    assert "tokens'] = None" not in snippet and 'tokens"] = None' not in snippet, (
        "step-⑥ snippet must never send tokens: null"
    )


def test_step6_section_states_agent_vs_orchestrator_distinction(repo_root):
    """The step-⑥ section must explicitly distinguish this agent-attributed event from the
    orchestrator's own machine events (status moves / format-normalize / commit note)."""
    text = (repo_root / SKILL_PATH).read_text()
    section = _step6_section(text)
    assert "not" in section.lower() and "orchestrator" in section.lower(), (
        "step-⑥ section must explicitly say this event is NOT actor:'Orchestrator'"
    )
    assert "format-normalize" in section.lower() or "format normaliz" in section.lower(), (
        "step-⑆ section must name the format-normalize note as a genuine orchestrator event"
    )
    assert "commit" in section.lower(), (
        "step-⑥ section must name the commit note as a genuine orchestrator event"
    )


# ──────────────────────────────────────────────────────────────────────────────
# 2. Genuine machine events (status-move / format-normalize / commit note) still
#    carry actor:"Orchestrator" — the fix must not sweep these into agent attribution.
# ──────────────────────────────────────────────────────────────────────────────


def test_format_normalize_note_still_orchestrator(repo_root):
    """The Impl-Step Format Normalization block's two activity notes (no-formatter-resolved
    skip, and non-zero-exit) must both still be actor:"Orchestrator", model:"system" — these
    are genuine machine events, not agent work."""
    text = (repo_root / SKILL_PATH).read_text()
    match = re.search(
        r"#### Impl-Step Format Normalization(.*?)\n#### ",
        text,
        re.DOTALL,
    )
    assert match, "SKILL.md must have the 'Impl-Step Format Normalization' section"
    section = match.group(1)
    occurrences = len(re.findall(r'actor:"Orchestrator",\s*model:"system"', section))
    assert occurrences >= 2, (
        "format-normalize section must keep both its activity notes as "
        f"actor:\"Orchestrator\", model:\"system\" (found {occurrences})"
    )


def test_commit_note_still_orchestrator(repo_root):
    """The done-transition commit-hash activity event must stay actor: "Orchestrator" — a
    genuine machine event recording what the orchestrator committed, not agent work."""
    text = (repo_root / SKILL_PATH).read_text()
    match = re.search(r"→ Done Transition(.*?)$", text, re.DOTALL)
    assert match, "SKILL.md must have the '→ Done Transition' section"
    section = match.group(1)
    assert re.search(r"""['"]?actor['"]?:\s*['"]Orchestrator['"]""", section), (
        "the commit-hash activity event under Done Transition must carry actor: \"Orchestrator\""
    )
    assert re.search(r"""['"]?model['"]?:\s*['"]system['"]""", section), (
        "the commit-hash activity event under Done Transition must carry model: \"system\""
    )


def test_status_move_patches_still_orchestrator(repo_root):
    """The done-commit and impl_review-commit status-move PATCHes must keep
    actor:"Orchestrator" — these are the orchestrator's own state-transition writes."""
    text = (repo_root / SKILL_PATH).read_text()
    assert 'api PATCH /task/$ID --json \'{"status": "impl_review", "current_agent": null, "actor": "Orchestrator"}\'' in text
    assert 'api PATCH /task/$ID --json \'{"status": "done", "current_agent": null, "actor": "Orchestrator"}\'' in text


# ──────────────────────────────────────────────────────────────────────────────
# 3. Field-write templates (Planner/Builder/Shield) carry actor + model in their
#    PATCH bodies.
# ──────────────────────────────────────────────────────────────────────────────


def test_field_write_templates_carry_actor_and_model(repo_root):
    missing = []
    for rel, nickname in _FIELD_WRITE_TEMPLATES.items():
        text = (repo_root / rel).read_text()
        has_actor = f'"actor": "{nickname}"' in text or f"\\\"actor\\\": \\\"{nickname}\\\"" in text
        has_model = re.search(r'\\?"model\\?":\s*\\?"<MODEL_' + nickname.upper() + r'>\\?"', text)
        if not (has_actor and has_model):
            missing.append(rel)
    assert not missing, (
        f"these field-write templates must carry actor+model in their PATCH body: {missing}"
    )


def test_field_write_templates_actor_model_in_same_patch_body(repo_root):
    """actor/model must land in the SAME PATCH call as the domain write (plan /
    implementation_notes), not a separate follow-up write."""
    for rel, nickname in _FIELD_WRITE_TEMPLATES.items():
        text = (repo_root / rel).read_text()
        patch_lines = [ln for ln in text.splitlines() if "api PATCH /task/<ID>" in ln]
        assert patch_lines, f"{rel} must have an `api PATCH /task/<ID>` line"
        line = patch_lines[0]
        assert f'\\"actor\\": \\"{nickname}\\"' in line, (
            f"{rel}: actor:\"{nickname}\" must be in the same PATCH body as the domain write"
        )
        assert "MODEL_" in line, f"{rel}: model must be in the same PATCH body as the domain write"


# ──────────────────────────────────────────────────────────────────────────────
# 4. Verdict templates (Critic/Inspector/Ranger) drop the self-guessed tokens
#    estimate but keep model.
# ──────────────────────────────────────────────────────────────────────────────


def test_verdict_templates_drop_token_estimate_keep_model(repo_root):
    for rel in _VERDICT_TEMPLATES:
        text = (repo_root / rel).read_text()
        assert "ESTIMATED_TOKENS" not in text, (
            f"{rel} must no longer carry a tokens:<ESTIMATED_TOKENS> self-guess"
        )
        assert not re.search(r'"tokens":\s*<?\d*ESTIMATED', text)
        assert '"tokens"' not in text, (
            f"{rel}'s verdict POST body must not carry a tokens field at all "
            "(the orchestrator's step-⑥ event is the single source of truth)"
        )
        assert '"model"' in text, f"{rel} must still send model in its verdict POST"


# ──────────────────────────────────────────────────────────────────────────────
# 5. schema.md's token guidance sources the runtime's reported usage (portable),
#    not a manual context-size estimate.
# ──────────────────────────────────────────────────────────────────────────────


def test_schema_token_guide_is_runtime_sourced_not_estimated(repo_root):
    text = (repo_root / SCHEMA_PATH).read_text()
    assert "Token Usage Guide" in text, "schema.md must rename to 'Token Usage Guide'"
    assert "Token Estimation Guide" not in text, (
        "schema.md must drop the old 'Token Estimation Guide' heading"
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
# 6. Portability guard: no shipped skills/** file hardcodes a Claude-Code-specific
#    token field name; the token source stays prose-portable.
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
    """No shipped skills/** file may hardcode a Claude-Code/Anthropic-specific usage field
    name (e.g. input_tokens/output_tokens) — the guidance must stay portable prose so
    Codex and other runtimes can resolve their own equivalent."""
    offenders = []
    for path in (repo_root / "skills").rglob("*"):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for pat in _CC_SPECIFIC_TOKEN_PATTERNS:
            if pat.search(text):
                offenders.append((str(path.relative_to(repo_root)), pat.pattern))
    assert not offenders, f"shipped skills/** must not hardcode CC-specific token fields: {offenders}"


def test_estimated_tokens_placeholder_gone_from_skills(repo_root):
    """The old <ESTIMATED_TOKENS> self-guess placeholder must be gone from every shipped
    skills/** file (not just the three verdict templates)."""
    offenders = []
    for path in (repo_root / "skills").rglob("*"):
        if path.is_file() and "ESTIMATED_TOKENS" in path.read_text(encoding="utf-8", errors="ignore"):
            offenders.append(str(path.relative_to(repo_root)))
    assert not offenders, f"<ESTIMATED_TOKENS> self-guess must be gone from skills/**: {offenders}"
