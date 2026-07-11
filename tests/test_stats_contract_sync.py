"""Contract guards for the /activity/stats doc + /squad stats consumer sync.

The wire contract: `/activity/stats` returns per-actor `{actor, model, events, tokens,
reported}` with per-actor `tokens` nullable and `totals.tokens` a coalesced number.

Locations after the shared-context split: the endpoint docs live in schema.md (the table
row) and skills/squad/references/api.md (the Activity & comments section — formerly
shared.md's Per-actor stats subsection). The `/squad stats` consumer is the packaged
script skills/squad/scripts/stats.py (formerly a SKILL.md heredoc) — a Tolerant Reader:
it extracts only the fields it uses via `.get()`, treats a null/missing per-actor
`tokens` as unknown (never crashes, never renders `0`), and ignores unknown fields.

Structural doc invariants plus behavioral tests that run stats.py's renderer against a
synthetic payload with its board reads stubbed — stdlib-only, hermetic.
"""
import re


SCHEMA_PATH = "skills/squad/schema.md"
STATS_DOC_PATH = "skills/squad/references/api.md"
CONSUMER_PATH = "skills/squad/scripts/stats.py"


def _stats_endpoint_row(text):
    """The schema.md table row documenting GET /api/activity/stats."""
    match = re.search(r"^\|.*GET /api/activity/stats.*\|\s*$", text, re.MULTILINE)
    assert match, "schema.md must have a table row documenting GET /api/activity/stats"
    return match.group(0)


def _stats_doc_section(text):
    """The references/api.md 'Activity & comments' section (owns the stats wire shape)."""
    match = re.search(r"## Activity & comments.*?(?=\n## |\Z)", text, re.DOTALL)
    assert match, "references/api.md must have an 'Activity & comments' section"
    return match.group(0)


def _schema_event_tokens_line(text):
    """The schema.md event-shape `tokens` bullet."""
    match = re.search(r"^- `tokens` is optional/`null`.*$", text, re.MULTILINE)
    assert match, "schema.md must have a `tokens` bullet in the event-shape section"
    return match.group(0)


def _schema_token_usage_guide(text):
    lowered = text.lower()
    assert "token usage guide" in lowered, "schema.md must have a 'Token Usage Guide' section"
    tail = text[lowered.index("token usage guide"):]
    lowered_tail = tail.lower()
    end = lowered_tail.find("## table")
    return tail if end == -1 else tail[:end]


def _run_stats(stats_mod, monkeypatch, capsys, stats_payload, board_payload=None):
    """Run stats.py's renderer with its board reads stubbed. Returns rendered stdout."""
    if board_payload is None:
        board_payload = {col: [] for col in [
            "todo", "plan", "plan_review", "impl", "impl_review", "test",
            "done", "cancelled",
        ]}

    def fake_api(path):
        if "activity/stats" in path:
            return stats_payload
        return board_payload

    monkeypatch.setattr(stats_mod, "_api", fake_api)
    stats_mod.main()
    return capsys.readouterr().out


# ──────────────────────────────────────────────────────────────────────────────
# 1. Docs shape — schema.md + references/api.md document the per-actor row with
#    `model` + `reported`, and mark per-actor `tokens` nullable.
# ──────────────────────────────────────────────────────────────────────────────


def test_schema_stats_row_documents_model_and_reported(repo_root):
    text = (repo_root / SCHEMA_PATH).read_text()
    row = _stats_endpoint_row(text)
    assert "model" in row, "stats row must name `model`"
    assert "reported" in row, "stats row must name `reported`"
    assert "actor" in row and "events" in row and "tokens" in row


def test_schema_stats_row_marks_per_actor_tokens_nullable(repo_root):
    text = (repo_root / SCHEMA_PATH).read_text()
    row = _stats_endpoint_row(text)
    assert re.search(r"tokens.{0,40}`?number`?\s*\|\s*`?null`?", row) or (
        "number" in row and "null" in row
    ), "stats row must mark per-actor `tokens` as `number | null`"


def test_stats_doc_section_documents_model_and_reported(repo_root):
    text = (repo_root / STATS_DOC_PATH).read_text()
    section = _stats_doc_section(text)
    assert "model" in section, "the stats doc section must name `model`"
    assert "reported" in section, "the stats doc section must name `reported`"


def test_stats_doc_section_marks_per_actor_tokens_nullable(repo_root):
    text = (repo_root / STATS_DOC_PATH).read_text()
    section = _stats_doc_section(text)
    assert "number" in section and "null" in section, (
        "the stats doc section must mark per-actor `tokens` as nullable"
    )


# ──────────────────────────────────────────────────────────────────────────────
# 2. No stale claims — tokens are not "estimated"; a missing value never
#    "counts as 0".
# ──────────────────────────────────────────────────────────────────────────────


def test_schema_event_tokens_line_not_estimated(repo_root):
    text = (repo_root / SCHEMA_PATH).read_text()
    line = _schema_event_tokens_line(text)
    assert "estimated" not in line.lower(), (
        "schema.md must not call tokens 'estimated' (contradicts runtime-sourced wording)"
    )


def test_schema_event_tokens_line_no_counts_as_zero_claim(repo_root):
    text = (repo_root / SCHEMA_PATH).read_text()
    line = _schema_event_tokens_line(text)
    assert "counts as 0" not in line.lower(), (
        "schema.md must not claim a missing token value counts as 0 in stats"
    )


def test_schema_token_usage_guide_no_counts_as_zero_claim(repo_root):
    text = (repo_root / SCHEMA_PATH).read_text()
    guide = _schema_token_usage_guide(text)
    assert "counts as 0" not in guide.lower(), (
        "schema.md Token Usage Guide must not claim a missing value counts as 0"
    )


def test_no_stale_counts_as_zero_claim_anywhere_in_schema(repo_root):
    text = (repo_root / SCHEMA_PATH).read_text()
    assert "missing counts as 0 in stats" not in text.lower()


# ──────────────────────────────────────────────────────────────────────────────
# 3. `totals.tokens` is NOT described as nullable — only the per-actor `tokens` is.
# ──────────────────────────────────────────────────────────────────────────────


def test_schema_totals_tokens_described_as_coalesced_not_nullable(repo_root):
    text = (repo_root / SCHEMA_PATH).read_text()
    row = _stats_endpoint_row(text)
    assert "totals.tokens" in row, "stats row must explicitly name `totals.tokens`"
    assert "coalesced" in row.lower(), (
        "stats row must describe `totals.tokens` as a coalesced (non-nullable) number"
    )
    totals_idx = row.lower().index("totals.tokens")
    after = row[totals_idx:totals_idx + 60].lower()
    assert "null" not in after, "`totals.tokens` must not be described as nullable"


def test_stats_doc_totals_tokens_described_as_coalesced_not_nullable(repo_root):
    text = (repo_root / STATS_DOC_PATH).read_text()
    section = _stats_doc_section(text)
    assert "totals.tokens" in section
    assert "coalesced" in section.lower()
    lowered = section.lower()
    totals_idx = lowered.index("totals.tokens")
    after = lowered[totals_idx:totals_idx + 60]
    assert "null" not in after, "`totals.tokens` must not be described as nullable"


# ──────────────────────────────────────────────────────────────────────────────
# 4. Tolerant Reader — stats.py, run against a synthetic payload with a
#    null-tokens row, a real-tokens row, and unknown extra fields, must not
#    raise, must render the null as unknown (never 0), must ignore the unknown
#    fields, and must surface `reported` coverage.
# ──────────────────────────────────────────────────────────────────────────────


def test_squad_stats_consumer_tolerates_null_tokens_and_unknown_fields(
        stats_mod, monkeypatch, capsys):
    synthetic_stats = {
        "stats": [
            {"actor": "Builder", "model": "opus", "events": 3, "tokens": None,
             "reported": 0, "future_field": "unexpected-value"},
            {"actor": "Shield", "model": "sonnet", "events": 2, "tokens": 4200,
             "reported": 2},
        ],
        "totals": {"events": 5, "tokens": 4200},
        "unknown_top_level_field": True,
    }

    output = _run_stats(stats_mod, monkeypatch, capsys, synthetic_stats)

    # Unknown fields ignored — never echoed.
    assert "future_field" not in output
    assert "unexpected-value" not in output
    assert "unknown_top_level_field" not in output

    # The null-tokens row renders as unknown (a dash), never 0.
    builder_line = next(
        (line for line in output.splitlines() if line.strip().startswith("| Builder")),
        None,
    )
    assert builder_line is not None, f"expected a Builder row in output:\n{output}"
    cells = [c.strip() for c in builder_line.strip().strip("|").split("|")]
    assert cells[0] == "Builder"
    assert cells[2] in ("—", "-", "unknown", "n/a", "N/A"), (
        f"null tokens must render as unknown/dash, not a number: got {cells[2]!r}"
    )
    assert cells[2] != "0"

    # Reported coverage surfaced for the row with an explicit count.
    shield_line = next(
        (line for line in output.splitlines() if line.strip().startswith("| Shield")),
        None,
    )
    assert shield_line is not None
    shield_cells = [c.strip() for c in shield_line.strip().strip("|").split("|")]
    assert shield_cells[1] == "2"
    assert "4,200" in shield_cells[2] or "4200" in shield_cells[2]
    assert "2" in shield_cells[3]


def test_squad_stats_consumer_does_not_crash_on_empty_stats(stats_mod, monkeypatch, capsys):
    output = _run_stats(stats_mod, monkeypatch, capsys, {"stats": [], "totals": {}})
    assert "no token data" in output.lower()


def test_squad_stats_consumer_totals_tokens_none_does_not_crash(stats_mod, monkeypatch, capsys):
    """Even totals.tokens (documented as coalesced) is defensively guarded — a future
    server bug returning totals.tokens: null must not crash the reader."""
    _run_stats(stats_mod, monkeypatch, capsys, {
        "stats": [
            {"actor": "Ranger", "model": "sonnet", "events": 1, "tokens": None, "reported": 0},
        ],
        "totals": {"events": 1, "tokens": None},
    })


# ──────────────────────────────────────────────────────────────────────────────
# 5. Negative regression — the consumer source must not reintroduce the crash
#    pattern: `.get('tokens', 0)` masking a null, or an "estimated" label.
# ──────────────────────────────────────────────────────────────────────────────


def _consumer_source(repo_root):
    return (repo_root / CONSUMER_PATH).read_text()


def test_squad_stats_consumer_has_no_tokens_zero_default_pattern(repo_root):
    code = _consumer_source(repo_root)
    offending = re.compile(r"""get\(\s*['"]tokens['"]\s*,\s*0\s*\)""")
    assert not offending.search(code), (
        "stats.py must not default a missing/null `tokens` to 0 via .get('tokens', 0)"
    )


def test_squad_stats_consumer_uses_is_none_guard_for_tokens(repo_root):
    code = _consumer_source(repo_root)
    assert re.search(r"tok\w*\s+is\s+None", code) or "is None" in code, (
        "stats.py must guard per-actor tokens with an `is None` check"
    )


def test_squad_stats_consumer_drops_estimated_label(repo_root):
    code = _consumer_source(repo_root)
    assert "Tokens (est.)" not in code, (
        "stats.py must not label tokens as estimated — they are runtime-reported"
    )
