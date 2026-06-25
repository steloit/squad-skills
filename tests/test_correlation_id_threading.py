"""Structural guards for per-step correlation_id threading (#SQD-900).

squad-run mints ONE uuid-v4 `correlation_id` per agent step occurrence and threads the
SAME id through (a) that step's record-results write AND (b) the orchestrator's
`POST /activity` for that step — so the board groups a step's writes + agent_log into
one timeline entry. A fresh id is minted per occurrence (a reject re-run gets a new id).

These are deterministic invariants (mirroring test_activity_adoption.py): all 6 agent
templates carry the `<correlation_id>` placeholder in their Record Results write;
squad-run/SKILL.md mints the id, lists the placeholder, passes it to BOTH the template
render AND the step-⑥ activity POST; schema.md/shared.md document the wire field; and a
render_agent_prompt.py dry-run proves `<correlation_id>` resolves via the existing
`--set` mechanism with no script change.
"""
import subprocess
import sys


# The 6 pipeline agent templates and the Record-Results write each one performs.
_TEMPLATES = [
    "skills/squad/templates/plan-agent.md",
    "skills/squad/templates/worker-agent.md",
    "skills/squad/templates/tdd-tester.md",
    "skills/squad/templates/review-agent.md",
    "skills/squad/templates/code-review-agent.md",
    "skills/squad/templates/test-runner.md",
]


def test_all_six_templates_carry_correlation_id(repo_root):
    """Each of the 6 agent templates' Record Results body must include the
    `<correlation_id>` placeholder (fed by the orchestrator) so its write is tagged."""
    missing = []
    for rel in _TEMPLATES:
        text = (repo_root / rel).read_text()
        if "<correlation_id>" not in text or "correlation_id" not in text:
            missing.append(rel)
    assert not missing, (
        f"these templates are missing the correlation_id / <correlation_id> placeholder "
        f"in their Record Results write: {missing}"
    )


def test_skill_mints_fresh_uuid_per_step(repo_root):
    """squad-run/SKILL.md must mint a fresh per-step uuid via uuid.uuid4() in the
    dispatch procedure (not cached), and state reject re-dispatches get a new id."""
    text = (repo_root / "skills" / "squad-run" / "SKILL.md").read_text()
    assert "uuid.uuid4()" in text, "SKILL.md must mint the id with uuid.uuid4()"
    assert "CORRELATION_ID=$(python3 -c 'import uuid;print(uuid.uuid4())')" in text, (
        "SKILL.md must mint CORRELATION_ID with the standard inline-python bash"
    )
    # Fresh-per-occurrence guarantee — reject re-dispatches must be called out.
    assert "reject re-dispatch" in text.lower(), (
        "SKILL.md must state reject re-dispatches mint a fresh correlation id"
    )
    assert "never cache" in text.lower() or "never reuse" in text.lower(), (
        "SKILL.md must state the id is never cached/reused across the loop"
    )


def test_skill_lists_placeholder_and_passes_to_render(repo_root):
    """SKILL.md must list <correlation_id> in the step-④ placeholder fill and pass it
    to render_agent_prompt.py via --set correlation_id=."""
    text = (repo_root / "skills" / "squad-run" / "SKILL.md").read_text()
    assert "<correlation_id>" in text, "SKILL.md must list the <correlation_id> placeholder"
    assert '--set correlation_id="$CORRELATION_ID"' in text, (
        "SKILL.md must pass --set correlation_id=\"$CORRELATION_ID\" to the render helper"
    )


def test_skill_threads_same_id_to_activity_post(repo_root):
    """The threading guarantee: the SAME $CORRELATION_ID feeds both the template render
    (--set) AND the step-⑥ orchestrator POST /activity body."""
    text = (repo_root / "skills" / "squad-run" / "SKILL.md").read_text()
    # The step-⑥ activity POST line must include correlation_id fed by $CORRELATION_ID.
    assert "correlation_id:$CORRELATION_ID" in text, (
        "SKILL.md step-⑥ POST /activity body must carry correlation_id:$CORRELATION_ID"
    )
    # Both consumers reference the one variable.
    assert text.count("$CORRELATION_ID") >= 3, (
        "expected $CORRELATION_ID referenced at mint + --set + activity POST (>=3)"
    )


def test_schema_documents_correlation_id(repo_root):
    """schema.md must document correlation_id on the task PATCH, the activity append,
    and the 3 verdict endpoints (plan-review / review / test-result)."""
    text = (repo_root / "skills" / "squad" / "schema.md").read_text()
    assert "correlation_id" in text, "schema.md must mention correlation_id"
    # Activity append body contract gains the optional field.
    assert "tokens?, correlation_id?" in text, (
        "schema.md activity append body contract must list correlation_id?"
    )
    # The dedicated section covering PATCH + activity + the 3 verdict endpoints.
    assert "Optional `correlation_id` on writes" in text, (
        "schema.md must have the 'Optional correlation_id on writes' section"
    )
    for ep in ("/plan-review", "/review", "/test-result", "/activity"):
        assert ep in text, f"schema.md must reference {ep}"


def test_shared_documents_correlation_id(repo_root):
    """shared.md example snippets (3 verdict POSTs + activity append) must show
    correlation_id and note that squad-run threads one per step."""
    text = (repo_root / "skills" / "squad" / "shared.md").read_text()
    # All three verdict snippet bodies + the activity body contract carry the field.
    assert text.count('"correlation_id": "<correlation_id>"') >= 3, (
        "shared.md must show correlation_id in the 3 verdict POST example bodies"
    )
    assert "tokens?, correlation_id?" in text, (
        "shared.md activity append body contract must list correlation_id?"
    )
    assert "fresh id per agent step" in text or "ONE fresh id per agent step" in text, (
        "shared.md must note squad-run threads one fresh id per step"
    )


def test_render_resolves_correlation_id_via_set(repo_root, tmp_path):
    """Dry-run proof: render_agent_prompt.py resolves <correlation_id> via the existing
    generic --set mechanism — no script change needed. Under --strict, no leftover
    <correlation_id> remains."""
    models = repo_root / "skills" / "squad" / "models.json"
    script = repo_root / "skills" / "squad" / "scripts" / "render_agent_prompt.py"
    fixed_uuid = "11111111-2222-4333-8444-555566667777"

    template = tmp_path / "tpl.md"
    template.write_text('{"correlation_id": "<correlation_id>"}\n')

    res = subprocess.run(
        [sys.executable, str(script), "--template", str(template),
         "--models", str(models), "--provider", "claude",
         "--set", f"correlation_id={fixed_uuid}", "--strict"],
        capture_output=True, text=True,
    )
    assert res.returncode == 0, f"render failed: {res.stderr}"
    assert fixed_uuid in res.stdout, "rendered output must contain the supplied uuid"
    assert "<correlation_id>" not in res.stdout, (
        "the <correlation_id> placeholder must be fully resolved by --set"
    )
