"""Contract guards for the /activity/stats doc + /squad stats consumer sync (#SQD-984).

Companion to the shipped SQD-982 server change (`/activity/stats` now returns
per-actor `{actor, model, events, tokens, reported}` with per-actor `tokens` nullable
and `totals.tokens` a coalesced number) and the SQD-983 token-honesty reframe. This
card:

1. Syncs the two wire-contract docs (`skills/squad/schema.md:161`,
   `skills/squad/shared.md:~577`) to the shipped shape — naming `model` + `reported`
   and marking per-actor `tokens` nullable, while `totals.tokens` stays a plain
   coalesced number (not described as nullable).
2. Removes the now-FALSE "missing counts as 0 in stats" claim
   (`schema.md:144`, `schema.md:206`) and the SQD-983 leftover "estimated total
   tokens" wording (`schema.md:144`).
3. Rewrites the `/squad stats` consumer (`skills/squad/SKILL.md`) as a Tolerant
   Reader (Postel's law): extract only the fields it uses via `.get()`, treat a
   null/missing per-actor `tokens` as unknown (never crash, never render `0`),
   and ignore unknown/extra fields.

These are deterministic grep/structural invariants plus one behavioral test that
extracts and `exec`s the `/squad stats` heredoc against a synthetic payload —
stdlib-only, hermetic, using the shared `repo_root` fixture (mirrors
test_token_honesty_contract.py / test_activity_adoption.py).
"""
import contextlib
import io
import json
import os
import re


SCHEMA_PATH = "skills/squad/schema.md"
SHARED_PATH = "skills/squad/shared.md"
SKILL_PATH = "skills/squad/SKILL.md"


def _stats_endpoint_row(text):
    """The schema.md table row documenting GET /api/activity/stats (line 161)."""
    match = re.search(r"^\|.*GET /api/activity/stats.*\|\s*$", text, re.MULTILINE)
    assert match, "schema.md must have a table row documenting GET /api/activity/stats"
    return match.group(0)


def _shared_stats_section(text):
    """The shared.md 'Per-actor stats' subsection (heading through the next '#### ')."""
    match = re.search(
        r"#### Per-actor stats.*?(?=\n#### |\Z)",
        text,
        re.DOTALL,
    )
    assert match, "shared.md must have a '#### Per-actor stats' subsection"
    return match.group(0)


def _schema_event_tokens_line(text):
    """The schema.md event-shape `tokens` bullet (line 144)."""
    match = re.search(r"^- `tokens` is optional/`null`.*$", text, re.MULTILINE)
    assert match, "schema.md must have a `tokens` bullet in the event-shape section"
    return match.group(0)


def _schema_token_usage_guide(text):
    """The schema.md Token Usage Guide paragraph (line 206), scoped like the sibling
    honesty-contract test."""
    lowered = text.lower()
    assert "token usage guide" in lowered, "schema.md must have a 'Token Usage Guide' section"
    tail = text[lowered.index("token usage guide"):]
    lowered_tail = tail.lower()
    end = lowered_tail.find("## table")
    return tail if end == -1 else tail[:end]


def _extract_squad_stats_heredoc(text):
    """Extract the python heredoc body inside the `/squad stats` fenced bash block."""
    match = re.search(
        r"### `/squad stats`.*?python3 << 'PY'\n(.*?)\nPY\n```",
        text,
        re.DOTALL,
    )
    assert match, "SKILL.md must have a `/squad stats` python3 << 'PY' heredoc"
    return match.group(1)


# ──────────────────────────────────────────────────────────────────────────────
# 1. Docs shape — schema.md:161 + shared.md:~577 document the per-actor row with
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


def test_shared_stats_section_documents_model_and_reported(repo_root):
    text = (repo_root / SHARED_PATH).read_text()
    section = _shared_stats_section(text)
    assert "model" in section, "shared.md Per-actor stats section must name `model`"
    assert "reported" in section, "shared.md Per-actor stats section must name `reported`"


def test_shared_stats_section_marks_per_actor_tokens_nullable(repo_root):
    text = (repo_root / SHARED_PATH).read_text()
    section = _shared_stats_section(text)
    assert "number" in section and "null" in section, (
        "shared.md Per-actor stats section must mark per-actor `tokens` as nullable"
    )


# ──────────────────────────────────────────────────────────────────────────────
# 2. No stale claims — schema.md:144 no longer calls tokens "estimated"; neither
#    schema.md:144 nor :206 claims a missing value counts as 0 in stats.
# ──────────────────────────────────────────────────────────────────────────────


def test_schema_event_tokens_line_not_estimated(repo_root):
    text = (repo_root / SCHEMA_PATH).read_text()
    line = _schema_event_tokens_line(text)
    assert "estimated" not in line.lower(), (
        "schema.md:144 must no longer call tokens 'estimated total tokens' "
        "(SQD-983 leftover, contradicts the runtime-sourced wording at line 206)"
    )


def test_schema_event_tokens_line_no_counts_as_zero_claim(repo_root):
    text = (repo_root / SCHEMA_PATH).read_text()
    line = _schema_event_tokens_line(text)
    assert "counts as 0" not in line.lower(), (
        "schema.md:144 must not claim a missing token value counts as 0 in stats"
    )


def test_schema_token_usage_guide_no_counts_as_zero_claim(repo_root):
    text = (repo_root / SCHEMA_PATH).read_text()
    guide = _schema_token_usage_guide(text)
    assert "counts as 0" not in guide.lower(), (
        "schema.md:206 must not claim a missing token value counts as 0 in stats"
    )


def test_no_stale_counts_as_zero_claim_anywhere_in_schema(repo_root):
    """Belt-and-suspenders: the exact stale phrase must be gone from the whole file,
    not just the two scoped locations (guards against it surviving elsewhere)."""
    text = (repo_root / SCHEMA_PATH).read_text()
    assert "missing counts as 0 in stats" not in text.lower()


# ──────────────────────────────────────────────────────────────────────────────
# 3. `totals.tokens` is NOT described as nullable — only the per-actor `tokens` is.
#    The docs must explicitly distinguish the two.
# ──────────────────────────────────────────────────────────────────────────────


def test_schema_totals_tokens_described_as_coalesced_not_nullable(repo_root):
    text = (repo_root / SCHEMA_PATH).read_text()
    row = _stats_endpoint_row(text)
    assert "totals.tokens" in row, "stats row must explicitly name `totals.tokens`"
    assert "coalesced" in row.lower(), (
        "stats row must describe `totals.tokens` as a coalesced (non-nullable) number"
    )
    # It must not say totals.tokens itself is nullable — scope the null claim to what
    # immediately precedes it (the per-actor tokens field), not to totals.
    totals_idx = row.lower().index("totals.tokens")
    # There must be no "null" token within a short window AFTER "totals.tokens" that
    # would suggest totals.tokens is nullable.
    after = row[totals_idx:totals_idx + 60].lower()
    assert "null" not in after, "`totals.tokens` must not be described as nullable"


def test_shared_totals_tokens_described_as_coalesced_not_nullable(repo_root):
    text = (repo_root / SHARED_PATH).read_text()
    section = _shared_stats_section(text)
    assert "totals.tokens" in section
    assert "coalesced" in section.lower()
    lowered = section.lower()
    totals_idx = lowered.index("totals.tokens")
    after = lowered[totals_idx:totals_idx + 60]
    assert "null" not in after, "`totals.tokens` must not be described as nullable"


# ──────────────────────────────────────────────────────────────────────────────
# 4. Tolerant Reader — the `/squad stats` heredoc, exec'd against a synthetic
#    payload with a null-tokens row, a real-tokens row, and an unknown extra
#    field, must not raise, must render the null as unknown (never 0), must
#    ignore the unknown field, and must surface `reported` coverage.
# ──────────────────────────────────────────────────────────────────────────────


def _run_squad_stats_heredoc(code, stats_payload, board_payload=None):
    if board_payload is None:
        board_payload = {
            col: []
            for col in [
                "todo", "plan", "plan_review", "impl", "impl_review", "test",
                "done", "cancelled",
            ]
        }
    old_board = os.environ.get("BOARD")
    old_stats = os.environ.get("STATS")
    os.environ["BOARD"] = json.dumps(board_payload)
    os.environ["STATS"] = json.dumps(stats_payload)
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            exec(compile(code, "<squad-stats-heredoc>", "exec"), {})
    finally:
        if old_board is None:
            os.environ.pop("BOARD", None)
        else:
            os.environ["BOARD"] = old_board
        if old_stats is None:
            os.environ.pop("STATS", None)
        else:
            os.environ["STATS"] = old_stats
    return buf.getvalue()


def test_squad_stats_consumer_tolerates_null_tokens_and_unknown_fields(repo_root):
    text = (repo_root / SKILL_PATH).read_text()
    code = _extract_squad_stats_heredoc(text)

    synthetic_stats = {
        "stats": [
            {
                "actor": "Builder",
                "model": "opus",
                "events": 3,
                "tokens": None,
                "reported": 0,
                "future_field": "unexpected-value",
            },
            {
                "actor": "Shield",
                "model": "sonnet",
                "events": 2,
                "tokens": 4200,
                "reported": 2,
            },
        ],
        "totals": {"events": 5, "tokens": 4200},
        "unknown_top_level_field": True,
    }

    # (a) must not raise.
    output = _run_squad_stats_heredoc(code, synthetic_stats)

    # (b) unknown fields ignored — never echoed anywhere in the rendered output.
    assert "future_field" not in output
    assert "unexpected-value" not in output
    assert "unknown_top_level_field" not in output

    # (c) the null-tokens row renders as unknown (an em/en dash), never a literal 0
    #     in its Tokens cell.
    builder_line = next(
        (line for line in output.splitlines() if line.strip().startswith("| Builder")),
        None,
    )
    assert builder_line is not None, f"expected a Builder row in output:\n{output}"
    cells = [c.strip() for c in builder_line.strip().strip("|").split("|")]
    # cells: Actor | Events | Tokens | Coverage
    assert cells[0] == "Builder"
    tokens_cell = cells[2]
    assert tokens_cell in ("—", "-", "unknown", "n/a", "N/A"), (
        f"null tokens must render as unknown/dash, not a number: got {tokens_cell!r}"
    )
    assert tokens_cell != "0"

    # (d) reported coverage is surfaced (a Coverage-style column/value distinct from
    #     Events/Tokens) for the row with an explicit reported count.
    shield_line = next(
        (line for line in output.splitlines() if line.strip().startswith("| Shield")),
        None,
    )
    assert shield_line is not None
    shield_cells = [c.strip() for c in shield_line.strip().strip("|").split("|")]
    assert shield_cells[1] == "2"  # events
    assert "4,200" in shield_cells[2] or "4200" in shield_cells[2]  # tokens
    # coverage cell references the reported count (2) — full coverage for Shield.
    assert "2" in shield_cells[3]


def test_squad_stats_consumer_does_not_crash_on_empty_stats(repo_root):
    text = (repo_root / SKILL_PATH).read_text()
    code = _extract_squad_stats_heredoc(text)

    empty_stats = {"stats": [], "totals": {}}
    output = _run_squad_stats_heredoc(code, empty_stats)
    assert "No token data" in output or "no token data" in output.lower()


def test_squad_stats_consumer_totals_tokens_none_does_not_crash(repo_root):
    """Even totals.tokens (documented as a coalesced number) is defensively guarded
    in the consumer — a future server bug returning totals.tokens: null must not
    crash the reader."""
    text = (repo_root / SKILL_PATH).read_text()
    code = _extract_squad_stats_heredoc(text)

    stats_with_null_totals = {
        "stats": [
            {"actor": "Ranger", "model": "sonnet", "events": 1, "tokens": None, "reported": 0},
        ],
        "totals": {"events": 1, "tokens": None},
    }
    # Must not raise.
    _run_squad_stats_heredoc(code, stats_with_null_totals)


# ──────────────────────────────────────────────────────────────────────────────
# 5. Negative regression — the consumer source must not reintroduce the crash
#    pattern this card fixes: `.get('tokens', 0)` (or `.get("tokens", 0)`)
#    immediately formatted with `:,` (a `None` default masking a real crash, or a
#    0-default lying about an unreported total).
# ──────────────────────────────────────────────────────────────────────────────


def test_squad_stats_consumer_has_no_tokens_zero_default_pattern(repo_root):
    text = (repo_root / SKILL_PATH).read_text()
    code = _extract_squad_stats_heredoc(text)
    offending = re.compile(r"""get\(\s*['"]tokens['"]\s*,\s*0\s*\)""")
    assert not offending.search(code), (
        "the /squad stats consumer must not default a missing/null `tokens` to 0 "
        "via .get('tokens', 0) — an unreported total must render as unknown, not 0"
    )


def test_squad_stats_consumer_uses_is_none_guard_for_tokens(repo_root):
    text = (repo_root / SKILL_PATH).read_text()
    code = _extract_squad_stats_heredoc(text)
    assert re.search(r"tok\w*\s+is\s+None", code) or "is None" in code, (
        "the /squad stats consumer must guard per-actor tokens with an `is None` "
        "check (a .get(..., 0) default does not catch an explicit JSON null)"
    )


def test_squad_stats_consumer_drops_estimated_label(repo_root):
    text = (repo_root / SKILL_PATH).read_text()
    code = _extract_squad_stats_heredoc(text)
    assert "Tokens (est.)" not in code, (
        "the /squad stats consumer must drop the misleading 'Tokens (est.)' label "
        "now that tokens are runtime-reported, not estimated"
    )
