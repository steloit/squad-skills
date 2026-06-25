"""Shield gap tests for squad-refine step ⑦ Save correlation_id threading (#SQD-907).

Builder's test_refine_correlation.py verifies presence of key strings anywhere in SKILL.md.
These tests tighten the structural and ordering invariants that file-wide grep cannot assert:

1. Mint-before-use ordering: CORRELATION_ID= assignment precedes BOTH the /spec curl body
   AND the /activity line within step ⑦ (not just somewhere in the file).
2. Both writes scoped to step ⑦: the mint AND both correlation_id references live inside
   step ⑦'s text block, not in another step.
3. Variable linkage: --arg cid "$CORRELATION_ID" and correlation_id:$cid appear together
   in the same jq invocation — confirming $cid IS $CORRELATION_ID on the /spec body.
4. 412-retry stability: the retry comment explicitly says KEEP the same $CORRELATION_ID
   (not re-mint), preventing a split-timeline bug.
5. API-contract-only: no platform internals (@squad/*, packages/db, drizzle, apps/api,
   uuidv7, internal column names) leaked into any skill doc.
6. schema.md spec-field row itself (not just the section header) names /spec.
"""

import re


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _step7_text(repo_root) -> str:
    """Extract the text of step ⑦ Save from SKILL.md (up to the next ## heading)."""
    text = (repo_root / "skills" / "squad-refine" / "SKILL.md").read_text()
    # The step marker is "⑦ Save"; cut until the next heading (### or ##) or EOF.
    m = re.search(r"⑦ Save(.*?)(?=\n##|\Z)", text, re.DOTALL)
    assert m, "SKILL.md must contain a '⑦ Save' section"
    return m.group(0)


# ---------------------------------------------------------------------------
# 1. Mint precedes /spec write in step ⑦
# ---------------------------------------------------------------------------

def test_mint_precedes_spec_write_in_step7(repo_root):
    """CORRELATION_ID= assignment must appear before the /spec curl invocation inside
    step ⑦ — so the variable is defined before it is used."""
    block = _step7_text(repo_root)
    mint_pos = block.find("CORRELATION_ID=$(python3 -c 'import uuid;print(uuid.uuid4())')")
    spec_pos = block.find("correlation_id:$cid")
    assert mint_pos != -1, "step ⑦ must mint CORRELATION_ID before the /spec write"
    assert spec_pos != -1, "step ⑦ must contain correlation_id:$cid on the /spec body"
    assert mint_pos < spec_pos, (
        "CORRELATION_ID mint must precede the /spec body's correlation_id:$cid in step ⑦"
    )


# ---------------------------------------------------------------------------
# 2. Mint precedes /activity note in step ⑦
# ---------------------------------------------------------------------------

def test_mint_precedes_activity_note_in_step7(repo_root):
    """CORRELATION_ID= assignment must appear before the /activity note body inside
    step ⑦ — so the variable is defined before it is used on the second write."""
    block = _step7_text(repo_root)
    mint_pos = block.find("CORRELATION_ID=$(python3 -c 'import uuid;print(uuid.uuid4())')")
    activity_pos = block.find('"correlation_id": "$CORRELATION_ID"')
    assert mint_pos != -1, "step ⑦ must mint CORRELATION_ID"
    assert activity_pos != -1, (
        'step ⑦ must contain "correlation_id": "$CORRELATION_ID" on the /activity body'
    )
    assert mint_pos < activity_pos, (
        "CORRELATION_ID mint must precede the /activity note's correlation_id in step ⑦"
    )


# ---------------------------------------------------------------------------
# 3. /spec write precedes /activity note in step ⑦ (correct ordering)
# ---------------------------------------------------------------------------

def test_spec_write_precedes_activity_note_in_step7(repo_root):
    """The /spec curl write must appear before the /activity note inside step ⑦
    (spec snapshot first, then the Refiner note — matches the stated board grouping)."""
    block = _step7_text(repo_root)
    spec_pos = block.find("correlation_id:$cid")
    activity_pos = block.find('"correlation_id": "$CORRELATION_ID"')
    assert spec_pos != -1 and activity_pos != -1
    assert spec_pos < activity_pos, (
        "In step ⑦, the /spec write (correlation_id:$cid) must precede "
        "the /activity note (\"correlation_id\": \"$CORRELATION_ID\")"
    )


# ---------------------------------------------------------------------------
# 4. Variable linkage: --arg cid "$CORRELATION_ID" and correlation_id:$cid
#    appear in the same jq invocation in step ⑦
# ---------------------------------------------------------------------------

def test_cid_arg_and_field_in_same_jq_invocation(repo_root):
    """--arg cid \"$CORRELATION_ID\" and correlation_id:$cid must appear in the
    same jq -n ... invocation inside step ⑦, confirming $cid IS $CORRELATION_ID
    on the /spec body (not an unrelated variable)."""
    block = _step7_text(repo_root)
    # Find the jq invocation block that writes the spec body.
    # It starts with "jq -n" and spans until the closing "')" — capture it.
    jq_match = re.search(
        r"jq -n.*?--arg cid.*?correlation_id:\$cid.*?'[)]",
        block, re.DOTALL
    )
    assert jq_match, (
        "step ⑦ must have a single jq -n invocation containing both "
        "--arg cid \"$CORRELATION_ID\" and correlation_id:$cid"
    )
    jq_text = jq_match.group(0)
    assert '--arg cid "$CORRELATION_ID"' in jq_text, (
        "--arg cid must bind $CORRELATION_ID (not another variable) in the /spec jq body"
    )
    assert "correlation_id:$cid" in jq_text, (
        "the /spec jq body must use $cid (the bound alias for $CORRELATION_ID)"
    )


# ---------------------------------------------------------------------------
# 5. 412 retry comment says KEEP the same id (no re-mint on retry)
# ---------------------------------------------------------------------------

def test_412_retry_keeps_same_correlation_id(repo_root):
    """The 412-retry comment in step ⑦ must explicitly say to KEEP the same
    $CORRELATION_ID on retry — a re-mint on retry would split one save into two
    timeline groups, breaking the board's grouping guarantee."""
    block = _step7_text(repo_root)
    # Look for the 412 retry comment that mentions KEEP and CORRELATION_ID.
    has_keep = re.search(
        r"412.*?KEEP.*?\$CORRELATION_ID|KEEP.*?\$CORRELATION_ID.*?412",
        block, re.DOTALL | re.IGNORECASE
    )
    assert has_keep, (
        "step ⑦ must have a 412-retry comment explicitly saying KEEP the same "
        "$CORRELATION_ID (preventing a re-mint that would split the timeline group)"
    )


# ---------------------------------------------------------------------------
# 6. No platform internals in any touched skill doc
# ---------------------------------------------------------------------------

_INTERNALS = [
    "@squad/db",
    "@squad/auth",
    "@squad/services",
    "@squad/jobs",
    "@squad/schemas",
    "@squad/integrations",
    "@squad/config",
    "@squad/types",
    "packages/db",
    "apps/api",
    "drizzle",
    "uuidv7",
    "squad_app",   # runtime DB role — internal
]

def test_no_platform_internals_in_skill_md(repo_root):
    """SKILL.md must not reference backend-internal symbols; API wire shapes only."""
    text = (repo_root / "skills" / "squad-refine" / "SKILL.md").read_text()
    leaked = [s for s in _INTERNALS if s in text]
    assert not leaked, f"SKILL.md leaked platform internals: {leaked}"


def test_no_platform_internals_in_schema_md(repo_root):
    """schema.md must not reference backend-internal symbols."""
    text = (repo_root / "skills" / "squad" / "schema.md").read_text()
    leaked = [s for s in _INTERNALS if s in text]
    assert not leaked, f"schema.md leaked platform internals: {leaked}"


def test_no_platform_internals_in_shared_md(repo_root):
    """shared.md must not reference backend-internal symbols."""
    text = (repo_root / "skills" / "squad" / "shared.md").read_text()
    leaked = [s for s in _INTERNALS if s in text]
    assert not leaked, f"shared.md leaked platform internals: {leaked}"


# ---------------------------------------------------------------------------
# 7. schema.md spec-field row itself names /spec (not just the section header)
# ---------------------------------------------------------------------------

def test_schema_spec_field_row_names_spec_endpoint(repo_root):
    """The spec-field row in schema.md's task-fields table must reference the
    /spec endpoint — confirming the field description (not just the correlation_id
    section) calls out POST /task/:id/spec as the write path."""
    text = (repo_root / "skills" / "squad" / "schema.md").read_text()
    # The spec field row contains "| `spec` |" — grab that line.
    spec_row_match = re.search(r"\|\s*`spec`\s*\|.*", text)
    assert spec_row_match, "schema.md must have a | `spec` | field row"
    spec_row = spec_row_match.group(0)
    assert "/spec" in spec_row or "POST /task" in spec_row, (
        "The `spec` field row in schema.md must name the /spec write endpoint "
        f"(got: {spec_row!r})"
    )
