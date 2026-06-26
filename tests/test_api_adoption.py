"""Structural guard for the curl→api.py migration.

Before the migration every skill assembled its own curl command with inline
AUTH_HEADER arrays, manual Content-Type headers, and a raw $BASE_URL reference.
After the migration every board call flows through the api.py helper, which owns
auth, transport, JSON encoding, and Content-Type internally.

These deterministic grep/scan invariants fail immediately if any raw board curl,
inline auth-header array, or manual Content-Type header is reintroduced into a
skill or template file — keeping the migration from silently regressing.

Guard structure
---------------
  test_detector_fires_on_raw_board_curl   — negative-control: proves detectors
  test_detector_ignores_presigned_fetch      actually catch/skip what they should
  test_no_raw_board_curl_remains          — primary fence: no curl hitting board
  test_no_inline_auth_header_array        — no per-skill AUTH_HEADER=( plumbing
  test_no_manual_content_type             — no -H 'Content-Type:…' by hand
  test_api_helper_is_adopted              — positive check api.py is in active use
"""
import re


# ────────────────────────────────────────────────────────────────────────────
# File helpers
# ────────────────────────────────────────────────────────────────────────────


def _skill_files(repo_root):
    """All authored skill sources (markdown + python) under skills/."""
    skills_dir = repo_root / "skills"
    return list(skills_dir.rglob("*.md")) + list(skills_dir.rglob("*.py"))


def _skill_md_files(repo_root):
    """Markdown skill files only — the agent-facing instruction files.
    Used for the Content-Type check: python scripts may legitimately set
    Content-Type internally (api.py line 334) and are excluded here.
    """
    return list((repo_root / "skills").rglob("*.md"))


# ────────────────────────────────────────────────────────────────────────────
# Detection patterns
# ────────────────────────────────────────────────────────────────────────────

# A raw board curl: a line that contains `curl` as a command word AND references
# a board URL via $BASE_URL / $SQUAD_BASE_URL, an explicit /api/orgs/ segment,
# or a flat board-resource path after /api/.
#
# Correctly NOT matched:
#   curl -s "$url" -o …          ← presigned attachment fetch; $url is not
#                                   $BASE_URL and there is no /api/orgs/ on
#                                   that line — self-authenticating, not a board call
#   `curl` in prose / backticks  ← no board URL on the same line
#   api.py docstring line 5      ← "curl + auth + JSON" — no board URL
#   "curl-friendly fallback"     ← prose in shared.md, no board URL
_BOARD_CURL_RE = re.compile(
    r"\bcurl\b"
    r".*"
    r"(?:"
    r"\$(?:BASE_URL|SQUAD_BASE_URL)"                    # shell variable board-URL
    r"|/api/orgs/"                                       # explicit org-scoped path
    r"|/api/(?:task|board|projects|run-audit|run-audits|activity)\b"  # flat board resource
    r")"
)

# Inline auth-header array: the old per-skill auth plumbing that api.py replaced.
_AUTH_HEADER_ARRAY_RE = re.compile(
    r"AUTH_HEADER=\("                  # array declaration: AUTH_HEADER=("…")
    r"|"
    r"\$\{AUTH_HEADER\[@\]\}"          # array expansion: "${AUTH_HEADER[@]}"
)

# Manual Content-Type header — the pattern api.py made obsolete.
# Scoped to .md files (see _skill_md_files); api.py legitimately sets the
# header internally via req.add_header() and is excluded from this scan.
_MANUAL_CT_RE = re.compile(r"Content-Type:\s*application/json")

# skills/squad/scripts/api.md is the api.py contract doc.  It legitimately
# states "Content-Type: application/json is set once" as a feature description,
# not as an instruction to set the header by hand.  All other skill .md files
# must have zero such references.
_CT_ALLOWLIST = {"skills/squad/scripts/api.md"}


# ────────────────────────────────────────────────────────────────────────────
# Negative-control tests — prove detectors are live, not vacuously passing
# ────────────────────────────────────────────────────────────────────────────


def test_detector_fires_on_raw_board_curl():
    """Self-test: the board-curl detector MUST match known pre-migration patterns.
    If this test fails the guard has been weakened and cannot catch regressions."""
    # Canonical pre-migration form: AUTH_HEADER array + $BASE_URL.
    assert _BOARD_CURL_RE.search(
        'curl -sL "${AUTH_HEADER[@]}" "$BASE_URL/api/orgs/$SQUAD_ORG/task/SQD-1"'
    ), "detector must match curl with $BASE_URL"

    # Explicit /api/orgs/ without $BASE_URL (e.g. hardcoded host).
    assert _BOARD_CURL_RE.search(
        'curl -sL -H "Authorization: Bearer $TOKEN" "https://host/api/orgs/myorg/task"'
    ), "detector must match curl with /api/orgs/"

    # Flat board path (pre-org-scoping era).
    assert _BOARD_CURL_RE.search(
        'curl -sL "${AUTH_HEADER[@]}" "$BASE_URL/api/task/$TASK_ID"'
    ), "detector must match curl with flat /api/task/ path"

    # Auth-header array declaration.
    assert _AUTH_HEADER_ARRAY_RE.search(
        'AUTH_HEADER=("-H" "Authorization: Bearer $TOKEN")'
    ), "auth-header detector must match old array declaration"

    # Array expansion in a curl call.
    assert _AUTH_HEADER_ARRAY_RE.search(
        'curl -sL "${AUTH_HEADER[@]}" "$BASE_URL/api/orgs/$ORG/board"'
    ), "auth-header detector must match array expansion"

    # Manual Content-Type header flag.
    assert _MANUAL_CT_RE.search(
        "-H 'Content-Type: application/json'"
    ), "content-type detector must match manual -H flag form"

    assert _MANUAL_CT_RE.search(
        '-H "Content-Type: application/json"'
    ), "content-type detector must match double-quoted -H flag form"


def test_detector_ignores_presigned_fetch_and_prose():
    """Self-test: the board-curl detector must NOT fire on the presigned
    attachment fetch or on prose mentions of curl — these are NOT board calls."""
    # Presigned attachment download — $url is a short-TTL signed URL, not
    # $BASE_URL; there is no /api/orgs/ in the line.
    assert not _BOARD_CURL_RE.search(
        "while IFS=$'\\t' read -r url fn; do curl -s \"$url\" -o \"$DIR/$fn\"; done"
    ), "detector must not match the presigned attachment fetch (no board URL marker)"

    # api.py docstring prose — "curl + auth + JSON" without any board URL.
    assert not _BOARD_CURL_RE.search(
        "curl + auth + JSON. It owns, internally and opaquely to the calling agent:"
    ), "detector must not match prose 'curl + auth + JSON' in api.py docstring"

    # shared.md prose — "curl-friendly fallback" (no board URL on this line).
    assert not _BOARD_CURL_RE.search(
        '"expected_version": <version> in the JSON body (curl-friendly fallback)'
    ), "detector must not match prose 'curl-friendly fallback' in shared.md"

    # api.md prose — mentions curl in description without a board URL.
    assert not _BOARD_CURL_RE.search(
        "hand-assembling `curl` + auth + JSON. It owns auth (opaque token), transport,"
    ), "detector must not match api.md prose description of curl"


# ────────────────────────────────────────────────────────────────────────────
# Structural guards (the regression fence)
# ────────────────────────────────────────────────────────────────────────────


def test_no_raw_board_curl_remains(repo_root):
    """No skill or template file issues a raw board curl command.
    All board calls must flow through the api.py helper (api GET …, api POST …).

    Intentionally excluded from flagging:
      - curl -s "$url" in shared.md — presigned attachment fetch; it targets a
        self-authenticating signed URL (not the board API) and carries no
        $BASE_URL / /api/orgs/ / board-resource marker, so _BOARD_CURL_RE
        does not match it. No allowlist entry needed.
      - Prose mentions of curl in api.py/api.md docstrings — no board URL.
    """
    offenders = []
    for p in _skill_files(repo_root):
        for i, line in enumerate(p.read_text().splitlines(), 1):
            if _BOARD_CURL_RE.search(line):
                offenders.append(f"{p.relative_to(repo_root)}:{i}: {line.strip()}")
    assert not offenders, (
        "raw board curls must be replaced by api.py invocations (api GET/POST/PATCH/DELETE):\n"
        + "\n".join(offenders)
    )


def test_no_inline_auth_header_array(repo_root):
    """No skill file declares or expands an AUTH_HEADER=() array.
    Auth token resolution is owned by api.py; skills must never assemble
    auth headers by hand."""
    offenders = []
    for p in _skill_files(repo_root):
        for i, line in enumerate(p.read_text().splitlines(), 1):
            if _AUTH_HEADER_ARRAY_RE.search(line):
                offenders.append(f"{p.relative_to(repo_root)}:{i}: {line.strip()}")
    assert not offenders, (
        "inline AUTH_HEADER=() plumbing must be removed — api.py owns auth:\n"
        + "\n".join(offenders)
    )


def test_no_manual_content_type(repo_root):
    """No skill markdown file manually specifies 'Content-Type: application/json'.
    api.py sets the header once internally; skills must not pass it by hand.

    Allowlist: skills/squad/scripts/api.md — the api.py contract doc legitimately
    states 'Content-Type: application/json is set once' as a feature description,
    not as an instruction to manually set the header. This is the ONLY permitted
    occurrence outside of api.py itself (which is a python script, not a markdown
    skill, and is excluded from this scan by _skill_md_files).
    """
    offenders = []
    for p in _skill_md_files(repo_root):
        rel = str(p.relative_to(repo_root))
        if rel in _CT_ALLOWLIST:
            continue  # contract doc — legitimately documents what api.py does
        for i, line in enumerate(p.read_text().splitlines(), 1):
            if _MANUAL_CT_RE.search(line):
                offenders.append(f"{rel}:{i}: {line.strip()}")
    assert not offenders, (
        "manual 'Content-Type: application/json' must be removed — api.py sets it:\n"
        + "\n".join(offenders)
    )


def test_api_helper_is_adopted(repo_root):
    """Positive guard: the api.py helper is actively in use across the skills.

    shared.md must define the sourced api() wrapper and show real board calls
    via 'api GET' / 'api POST'. Representative per-skill SKILL.md files must
    also invoke the helper. This catches a scenario where all raw curls are
    deleted but the board calls are simply gone rather than migrated.
    """
    shared = (repo_root / "skills" / "squad" / "shared.md").read_text()
    assert "api() { python3 ../squad/scripts/api.py" in shared, (
        "shared.md must define the sourced api() wrapper for board access"
    )
    assert "api GET " in shared and "api POST " in shared, (
        "shared.md must show real board calls through the helper (api GET / api POST)"
    )

    # At least 4 of the 5 core writer skills must actively use the api wrapper.
    writer_skills = ("squad-run", "squad-refine", "squad-heartbeat", "squad-init", "squad-kickstart")
    adopters = []
    for skill in writer_skills:
        text = (repo_root / "skills" / skill / "SKILL.md").read_text()
        if "api GET " in text or "api POST " in text or "api PATCH " in text:
            adopters.append(skill)
    assert len(adopters) >= 4, (
        f"Expected ≥4 of {list(writer_skills)} to use api.py in their SKILL.md; "
        f"found {len(adopters)}: {adopters}. Migration may be incomplete."
    )
