"""Structural guards for the human gate-override write-through adoption (SQD-958).

At a default-mode squad-run review gate a human may **reject** — *including after an agent recorded
`approved`*. SQD-958 makes that send-back a durable, attributable server record rather than a
terminal-scrollback note: squad-run prompts for a mandatory `reason`, then `POST`s
`/task/:id/override-review` (record-only — appends a superseding `changes_requested`/`fail` verdict,
flips the derived `last_*_status`) BEFORE running its existing verdict→move table, which now computes
the backward move SQD-955 made legal. Attribution is delegation: the body carries `actor_kind=human`
even though it is relayed over the run's user-scoped PAT.

These are deterministic grep invariants (mirroring test_complete_adoption.py / test_cancel_adoption.py)
that keep the authored docs encoding the contract so the adoption can't silently regress — a dropped
reason prompt, a move that skips the override record, a lost `actor_kind=human` delegation marker, or
an endpoint that falls out of either the Move Protocol or API Endpoints section of shared.md.

Hermetic: reads the committed skill files only, no network.
"""
import re


def _read(repo_root, rel):
    return (repo_root / rel).read_text()


def _section(text, heading):
    """Return the body of a `### <heading>` section (up to the next `### ` heading or EOF)."""
    m = re.search(
        r"^###\s+" + re.escape(heading) + r"\b.*?(?=^###\s|\Z)",
        text,
        re.MULTILINE | re.DOTALL,
    )
    return m.group(0) if m else ""


# ── squad-run/SKILL.md: the gate-reject write-through block ────────────────────


def test_skill_gate_reject_prompts_reason_and_posts_override_before_move(repo_root):
    """The squad-run gate-reject block prompts for a mandatory reason AND `POST`s
    `/task/$ID/override-review` — and does so BEFORE the verdict→move (records the override, then
    re-reads the flipped verdict and falls through to the move table)."""
    text = _read(repo_root, "skills/squad-run/SKILL.md")

    # The override write-through is gated on a human REJECT.
    assert re.search(r"GATE_DECISION.*=\s*reject", text), (
        "SKILL.md must gate the override write-through on a human reject (GATE_DECISION = reject)"
    )

    # (a) Mandatory reason prompt.
    reason_idx = text.find("REASON=")
    assert reason_idx != -1, "SKILL.md gate-reject block must prompt for a REASON"
    assert re.search(r"[Mm]andatory reason|reason[^\n]*required", text), (
        "SKILL.md must state the reason is mandatory/required"
    )

    # (a) POSTs the override endpoint.
    post_idx = text.find("api POST /task/$ID/override-review")
    assert post_idx != -1, (
        "SKILL.md gate-reject block must `api POST /task/$ID/override-review`"
    )

    # The reason is prompted BEFORE the override POST.
    assert reason_idx < post_idx, (
        "SKILL.md must prompt for the reason BEFORE POSTing the override"
    )

    # BEFORE the move: the override is recorded, then the verdict is re-read and the move table runs.
    assert re.search(r"override[^\n]*BEFORE the\s+move|BEFORE the\s+\n?#?\s*move", text, re.IGNORECASE) or \
        re.search(r"record(?:ed)?[^\n]*BEFORE the[^\n]*move", text, re.IGNORECASE), (
        "SKILL.md must state the override is recorded BEFORE the move"
    )
    # The re-read of the now-flipped verdict comes AFTER the POST (so the move table sees the flip).
    reread_idx = text.find("Re-read the now-flipped", post_idx)
    assert reread_idx != -1 and reread_idx > post_idx, (
        "SKILL.md must re-read the flipped verdict AFTER the override POST, before falling through to the move table"
    )


def test_skill_references_actor_kind_human_and_delegation(repo_root):
    """The gate-reject block records the override with `actor_kind=human` (delegation, not
    impersonation) relayed over the run's user-scoped PAT."""
    text = _read(repo_root, "skills/squad-run/SKILL.md")
    assert "actor_kind=human" in text, (
        "SKILL.md must record the override with actor_kind=human (delegation attribution)"
    )
    assert re.search(r"delegation", text, re.IGNORECASE), (
        "SKILL.md must frame the override as delegation (not impersonation)"
    )
    # A 403 (PAT lacks the elevated scope) is surfaced, never downgraded to a silent fix-in-place.
    assert re.search(r"task:override-review", text), (
        "SKILL.md must name the elevated task:override-review scope"
    )
    assert re.search(r"fix-in-place|fix in place", text, re.IGNORECASE), (
        "SKILL.md must state a 403 is surfaced, NOT downgraded to a silent fix-in-place"
    )


# ── squad/shared.md: endpoint documented in BOTH Move Protocol AND API Endpoints ─


def test_shared_move_protocol_documents_override(repo_root):
    """shared.md's Move Protocol section documents the human gate-override: record the override
    (`/override-review`, mandatory reason, record-only) BEFORE the standard read→move runs against
    the flipped derived status."""
    text = _read(repo_root, "skills/squad/shared.md")
    move = _section(text, "Move Protocol")
    assert move, "shared.md must have a `### Move Protocol` section"
    assert "override-review" in move, (
        "shared.md Move Protocol must document the /override-review endpoint"
    )
    assert re.search(r"reason", move, re.IGNORECASE), (
        "shared.md Move Protocol must mention the mandatory reason"
    )
    assert re.search(r"record-only|never changes? `?status`?", move, re.IGNORECASE), (
        "shared.md Move Protocol must state the override is record-only (never changes status)"
    )
    assert re.search(r"SQD-955", move), (
        "shared.md Move Protocol must tie the backward move to SQD-955 (now legal)"
    )


def test_shared_api_endpoints_documents_override(repo_root):
    """shared.md's API Endpoints section documents the executable `api POST /task/$ID/override-review`
    call with the required reason, the elevated task:override-review scope, and delegation attribution."""
    text = _read(repo_root, "skills/squad/shared.md")
    endpoints = _section(text, "API Endpoints")
    assert endpoints, "shared.md must have a `### API Endpoints` section"
    assert re.search(r"api POST /task/\$ID/override-review", endpoints), (
        "shared.md API Endpoints must document the executable `api POST /task/$ID/override-review` call"
    )
    assert re.search(r"reason[^\n]*REQUIRED|REQUIRED[^\n]*reason|reason.*→\s*400", endpoints, re.IGNORECASE), (
        "shared.md API Endpoints must state reason is REQUIRED (omit/empty → 400)"
    )
    assert "task:override-review" in endpoints, (
        "shared.md API Endpoints must name the elevated task:override-review scope"
    )
    assert "actor_kind=human" in endpoints, (
        "shared.md API Endpoints must document the actor_kind=human delegation marker"
    )


def test_shared_documents_override_in_both_sections(repo_root):
    """Belt-and-suspenders: the endpoint is present in BOTH the Move Protocol and API Endpoints
    sections (the done_when explicitly requires both), not just one."""
    text = _read(repo_root, "skills/squad/shared.md")
    move = _section(text, "Move Protocol")
    endpoints = _section(text, "API Endpoints")
    assert "override-review" in move and "override-review" in endpoints, (
        "shared.md must document /override-review in BOTH Move Protocol AND API Endpoints sections"
    )
