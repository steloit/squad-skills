"""Shield's gap tests for per-step correlation_id threading (#SQD-900).

Builder's 7 tests (test_correlation_id_threading.py) verify presence and high-level
structure. These tests cover gaps Builder's suite left open:

1. Per-template `<correlation_id>` in the actual curl -d payload (Record Results body),
   not just anywhere in the file.
2. Mint-before-use ordering in SKILL.md — step ② mint precedes step ④ --set, which
   precedes step ⑥ activity POST.
3. shared.md activity-append JSON body shows correlation_id (the 4th distinct surface,
   beyond the 3 verdict POSTs already checked by Builder).
4. No platform internals (backend file paths, @squad/, drizzle, uuidv7) leaked into
   the new doc text added for this feature.
5. schema.md "Optional correlation_id on writes" section explicitly names PATCH as
   one of the surfaces (the section covers PATCH + activity + 3 verdicts).
"""
import re


# The 6 pipeline agent templates.
_TEMPLATES = {
    "plan-agent":        "skills/squad/templates/plan-agent.md",
    "worker-agent":      "skills/squad/templates/worker-agent.md",
    "tdd-tester":        "skills/squad/templates/tdd-tester.md",
    "review-agent":      "skills/squad/templates/review-agent.md",
    "code-review-agent": "skills/squad/templates/code-review-agent.md",
    "test-runner":       "skills/squad/templates/test-runner.md",
}

# Backend internals that must never appear in the skill docs.
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


def test_per_template_correlation_id_in_record_results_payload(repo_root):
    """Each template's Record Results curl -d body must contain `correlation_id` —
    not just in a comment but in the actual data payload sent to the API.

    Builder's test checks that 'correlation_id' appears anywhere in the file.
    This test checks it appears specifically in the Record Results section (after
    '## Record Results'), so a doc regression (removing it from the payload but
    leaving it in a comment elsewhere) would be caught.

    Note: PATCH templates use shell-escaped JSON (-d "{\\\"correlation_id\\\":\\\"...\\\"}"),
    while POST/verdict templates use multi-line JSON blocks with unescaped quotes.
    Both forms are accepted — the key invariant is 'correlation_id' appears somewhere
    in the Record Results block, not just in a trailing prose comment.
    """
    missing = []
    for name, rel in _TEMPLATES.items():
        text = (repo_root / rel).read_text()
        # Find the Record Results section heading.
        results_idx = text.find("## Record Results")
        assert results_idx != -1, f"{name}: no '## Record Results' section found"
        results_section = text[results_idx:]
        # The bash code block (``` ... ```) within the section must contain correlation_id.
        # Extract code blocks only (between ``` fences).
        code_blocks = re.findall(r'```bash\n(.*?)```', results_section, re.DOTALL)
        code_blocks += re.findall(r'```\n(.*?)```', results_section, re.DOTALL)
        combined_code = "\n".join(code_blocks)
        # Match either escaped (\") or unescaped (") form of correlation_id key.
        has_it = (
            "correlation_id" in combined_code
            and "<correlation_id>" in combined_code
        )
        if not has_it:
            missing.append(name)
    assert not missing, (
        f"these templates do NOT have `correlation_id` + `<correlation_id>` in their "
        f"Record Results code block (the curl -d payload): {missing}"
    )


def test_per_template_correlation_id_placeholder_in_record_results_payload(repo_root):
    """The `correlation_id` value in each Record Results body must be the
    `<correlation_id>` placeholder (filled by the orchestrator), not a hard-coded
    string or omitted value.

    Confirms the placeholder wire-up — the orchestrator substitutes it at runtime.
    """
    missing = []
    for name, rel in _TEMPLATES.items():
        text = (repo_root / rel).read_text()
        results_idx = text.find("## Record Results")
        assert results_idx != -1, f"{name}: no '## Record Results' section"
        results_section = text[results_idx:]
        # The placeholder must appear: "<correlation_id>" as a value in the section.
        if "<correlation_id>" not in results_section:
            missing.append(name)
    assert not missing, (
        f"these templates do NOT have the `<correlation_id>` placeholder in their "
        f"Record Results section: {missing}"
    )


def test_skill_mint_before_set_before_activity(repo_root):
    """SKILL.md must define $CORRELATION_ID (step ②) BEFORE the --set call (step ④)
    and BEFORE the activity POST reference (step ⑥). This ordering invariant ensures
    the id is always available when it's first consumed — a regression where the mint
    moves below its first use would be caught here.
    """
    text = (repo_root / "skills" / "squad-run" / "SKILL.md").read_text()
    mint_pos = text.find("CORRELATION_ID=$(python3 -c 'import uuid;print(uuid.uuid4())')")
    set_pos = text.find('--set correlation_id="$CORRELATION_ID"')
    activity_pos = text.find("correlation_id:$CORRELATION_ID")

    assert mint_pos != -1, "SKILL.md: CORRELATION_ID mint not found"
    assert set_pos != -1, "SKILL.md: --set correlation_id= not found"
    assert activity_pos != -1, "SKILL.md: activity POST correlation_id reference not found"

    assert mint_pos < set_pos, (
        "SKILL.md: CORRELATION_ID must be minted (step ②) before --set passes it to "
        "the template render (step ④) — mint appears after --set in the document"
    )
    assert set_pos < activity_pos, (
        "SKILL.md: the --set render call (step ④) must appear before the step-⑥ "
        "activity POST reference — ordering violation detected"
    )


def test_shared_md_activity_append_body_carries_correlation_id(repo_root):
    """shared.md must show correlation_id in the /activity append JSON example body
    (the 4th surface beyond the 3 verdict POST snippets).

    Builder's test asserts >= 3 occurrences of '"correlation_id": "<correlation_id>"',
    which covers the 3 verdict bodies. This test specifically checks the activity
    append body JSON block, making the count unambiguous.
    """
    text = (repo_root / "skills" / "squad" / "shared.md").read_text()
    # Find the activity append section.
    activity_idx = text.find("Append an event")
    assert activity_idx != -1, "shared.md: no 'Append an event' section found"
    activity_section = text[activity_idx:]
    # The JSON block in that section must include correlation_id.
    assert '"correlation_id"' in activity_section, (
        "shared.md: the activity append JSON example body must show 'correlation_id' — "
        "it was present in the diff but this section is missing it"
    )


def test_schema_md_patch_endpoint_named_in_correlation_id_section(repo_root):
    """schema.md's 'Optional correlation_id on writes' section must explicitly name
    PATCH as one of the surfaces (alongside /activity and the 3 verdict endpoints).

    Builder's test checks the section heading exists and /plan-review + /review +
    /test-result + /activity are referenced. This test checks PATCH is also called
    out in that same section — a future edit removing PATCH from the section would
    be caught here.
    """
    text = (repo_root / "skills" / "squad" / "schema.md").read_text()
    section_idx = text.find("### Optional `correlation_id` on writes")
    assert section_idx != -1, "schema.md: '### Optional correlation_id on writes' section not found"
    # Find end of section (next ### heading or end of file).
    next_heading = text.find("\n###", section_idx + 1)
    section = text[section_idx:next_heading] if next_heading != -1 else text[section_idx:]
    assert "PATCH" in section, (
        "schema.md 'Optional correlation_id on writes' section must name PATCH as one "
        "of the surfaces that accepts the field"
    )
    for ep in ("/plan-review", "/review", "/test-result", "/activity"):
        assert ep in section, (
            f"schema.md 'Optional correlation_id on writes' section must mention {ep}"
        )


def test_no_platform_internals_in_new_doc_text(repo_root):
    """New documentation text for correlation_id must not leak platform internals
    (backend package names, Drizzle references, internal file paths, uuidv7, etc.).
    Only the wire-contract surface is public; backend implementation details are
    forbidden in skill docs.
    """
    # Collect all skill docs that were modified by this feature.
    modified_files = [
        repo_root / "skills" / "squad-run" / "SKILL.md",
        repo_root / "skills" / "squad" / "schema.md",
        repo_root / "skills" / "squad" / "shared.md",
    ] + [repo_root / rel for rel in _TEMPLATES.values()]

    leaks = []
    for path in modified_files:
        text = path.read_text()
        for internal in _INTERNALS:
            if internal in text:
                leaks.append(f"{path.name}: contains '{internal}'")
    assert not leaks, (
        f"platform internals must never appear in skill docs (API-contract-only rule): "
        f"{leaks}"
    )
