"""Structural guards for squad-refine's step ⑦ Save correlation_id threading (#SQD-907).

squad-refine mints ONE uuid-v4 `correlation_id` per Save occasion and threads the SAME
id through (a) the `POST /spec` write AND (b) the Refiner `POST /activity` note — so the
board groups the spec snapshot + the Refiner note into one timeline stage. A re-refine is
a new save → a fresh id (never cached/reused across saves).

These are deterministic invariants (mirroring test_correlation_id_threading.py): step ⑦
mints the id via uuid.uuid4(), `correlation_id` rides BOTH the /spec write body and the
Refiner /activity note body fed by the one `$CORRELATION_ID`, and schema.md/shared.md
document /spec as an accepting surface.
"""


def test_refine_mints_one_uuid_at_save(repo_root):
    """squad-refine/SKILL.md step ⑦ must mint the id with the standard inline-python bash
    (uuid.uuid4()), the SQD-900 idiom verbatim."""
    text = (repo_root / "skills" / "squad-refine" / "SKILL.md").read_text()
    assert "uuid.uuid4()" in text, "SKILL.md must mint the id with uuid.uuid4()"
    assert "CORRELATION_ID=$(python3 -c 'import uuid;print(uuid.uuid4())')" in text, (
        "SKILL.md must mint CORRELATION_ID with the standard inline-python bash"
    )
    # Fresh-per-save guarantee — re-refine must be called out as a new id.
    assert "never cache" in text.lower() or "never reuse" in text.lower(), (
        "SKILL.md must state the id is never cached/reused across saves"
    )


def test_spec_write_carries_correlation_id(repo_root):
    """The `POST /spec` jq body (the `jq -n … '{spec:$spec, …}'`) must carry correlation_id,
    fed by the minted $CORRELATION_ID via --arg cid."""
    text = (repo_root / "skills" / "squad-refine" / "SKILL.md").read_text()
    assert "--arg cid \"$CORRELATION_ID\"" in text, (
        "the /spec jq body must pass --arg cid \"$CORRELATION_ID\""
    )
    assert "correlation_id:$cid" in text, (
        "the /spec jq body object must include correlation_id:$cid"
    )


def test_refiner_activity_note_carries_correlation_id(repo_root):
    """The Refiner `/activity` note body must carry correlation_id fed by $CORRELATION_ID."""
    text = (repo_root / "skills" / "squad-refine" / "SKILL.md").read_text()
    assert '"correlation_id": "$CORRELATION_ID"' in text, (
        "the Refiner /activity note body must include \"correlation_id\": \"$CORRELATION_ID\""
    )


def test_same_id_on_both_writes(repo_root):
    """The threading guarantee: ONE $CORRELATION_ID feeds the mint + the /spec write +
    the Refiner /activity note (>=3 references)."""
    text = (repo_root / "skills" / "squad-refine" / "SKILL.md").read_text()
    assert text.count("$CORRELATION_ID") >= 3, (
        "expected $CORRELATION_ID referenced at mint + /spec write + /activity note (>=3)"
    )


def test_schema_documents_spec_correlation_id(repo_root):
    """schema.md must name POST /spec as a correlation_id-accepting endpoint and note it
    on the spec-field row."""
    text = (repo_root / "skills" / "squad" / "schema.md").read_text()
    assert "Optional `correlation_id` on writes" in text, (
        "schema.md must have the 'Optional correlation_id on writes' section"
    )
    # The section must now name the /spec write as a fourth accepting surface.
    assert "POST /api/task/:id/spec" in text or "/task/:id/spec" in text, (
        "schema.md correlation_id section / spec-field row must name the /spec write"
    )
    assert "squad-refine" in text, (
        "schema.md must note squad-refine threads correlation_id on the spec write"
    )


def test_shared_documents_spec_correlation_id(repo_root):
    """The shared correlation_id doc (now references/api.md) must note squad-refine threads
    one id through the spec write + Refiner note."""
    text = (repo_root / "skills" / "squad" / "references" / "api.md").read_text()
    assert "squad-refine" in text and "correlation_id" in text, (
        "shared.md must mention squad-refine and correlation_id"
    )
    assert "/spec" in text, (
        "shared.md correlation_id prose must name the /spec write as a threading surface"
    )
