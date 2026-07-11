"""Contract test for SQD-954 — Shell Safety / injection-defense in squad-run orchestration.

Bash command-substitutes backticks/`$(...)` in the *literal text* of a command **before** the
program runs. If rendered/board content (a task's `plan`, `spec`, `description`, `decision_log`,
`done_when`, a commit title, a human's override `reason`) is pasted directly into a double-quoted
`python3 -c "..."` program, a `--json "{...}"` body, or a `git commit -m "..."` message, any
backtick/`$(...)` the content carries fires as a shell command — silently corrupting the
prompt/artifact (observed: SQD-952, SQEV-476) AND executing whatever the content contains (an
OS-command-injection / RCE vector, since a card's fields are untrusted input). The fix is
parameterization (temp file, env var → `os.environ`, or the render pipe), not escaping.

This file asserts:
  1. squad-run/SKILL.md carries the authoritative Shell Safety box (non-brittle: several
     independent stable stems, not one exact phrase) — including the "capture is a sink too"
     paragraph added on the impl_review re-run (see class 5-6 below).
  2. Within the SCOPED file set (see below), no snippet interpolates a rendered-content
     placeholder into one of the three SINKS that hand a hand-built double-quoted string to an
     interpreter: a `python3 -c "..."` program, a raw hand-rolled `--json "{...}"` JSON literal
     (as opposed to the safe `--json "$VAR"` out-of-band form), or a `git commit -m "..."`
     message.
  3. The SINK guard is not vacuous: a synthetic bad string is flagged, and safe patterns already
     in the tree (env-var expansion, the mapping-table prose, the box's own `<rendered-content>`
     sentinel) are correctly left unflagged.
  4. The SINK guard is diff-sensitive: it WOULD have flagged the two real pre-Builder leaks
     (verified verbatim against `git show HEAD:skills/squad-run/SKILL.md`, commit 4a2779e — the
     last commit before Builder's uncommitted SQD-954 fix) and does NOT flag the fixed lines. The
     leak text is hardcoded rather than read live via git, so this stays stable once the branch
     merges and HEAD moves past the fix.
  5. (Re-run, closing the impl_review send-back) Within the SCOPED file set, no snippet assigns a
     rendered/free-text placeholder into a plain double-quoted CAPTURE `VAR="<placeholder>"` — a
     DIFFERENT sink than class 2 above: a backtick/`$(...)` in the placeholder text
     command-substitutes AT THE ASSIGNMENT LINE, before any downstream env/`json.dumps` handling
     can protect it. The prior fix closed class 2 but left this one open (the human-caught
     override-review `REASON="<the human's reason>"` leak). Safe capture forms — a single-quoted
     heredoc (`VAR=$(cat <<'EOF' ... EOF)`), a var-to-var expansion (`VAR="$OTHER"`), or a
     command-substitution capture (`VAR=$(... | jq -r ...)`) — must NOT be flagged.
  6. The CAPTURE guard is non-vacuous (synthetic planted-positive + safe-pattern sanity) and
     diff-sensitive (verified verbatim against `git show HEAD:skills/squad-run/SKILL.md`, commit
     4a2779e, the pre-Builder REASON capture leak).
  7. (Re-run #2, closing the Inspector's impl_review gap) The class-5 CAPTURE_RE above only
     matches a WHOLE line that is exactly one `NAME="<placeholder>"` assignment. It missed a real
     leak: `schema.md:195` (the Builder's first-pass fix, staged git blob `373fd41d`) was
     `NICKNAME="Planner" MODEL="opus" MESSAGE="…" TASK_ID="…" PROJECT="…" python3 -c "` — a KNOWN
     free-text field (`MESSAGE`) captured via a plain double-quoted assignment that (a) shares its
     line with several other assignments, so the whole-line anchor never matches, and (b) uses an
     ellipsis placeholder rather than an angle-bracket token, so the `<…>` token shape never
     matches either. The tightened KNOWN_FIELD_CAPTURE_RE guard targets this directly: it scans
     for a fixed set of known free-text field names (`MESSAGE`, `REASON`, `RUN_SUMMARY`,
     `TRAJECTORY`, `FRICTION_SIGNALS`, `STEP_MSG`) assigned a literal double-quoted value ANYWHERE
     on a line (not anchored to the whole line), so a shared-line capture is caught. The only SAFE
     value shape is a pure var-to-var re-expansion (`MESSAGE="$MESSAGE"`) or the box's own
     `<rendered-content>` sentinel; a single-quoted heredoc and a command-substitution capture
     never match the `="..."` shape at all (`=$(`, not `="`), so they're safe by construction.
     Comment/prose lines are excluded (bash never command-substitutes inside a `#` comment, and
     two real doc lines illustrate the anti-pattern in prose using these exact field names).

SCOPE (why exactly three files, not the whole skills/** tree): this card's evidenced target is
the squad-run ORCHESTRATOR's own shell-assembly surface — the bash the orchestrator itself
builds and runs turn-by-turn, documented across `skills/squad-run/SKILL.md` (the run loop:
override-review write-through, done-commit) and the two shared references it follows,
`skills/squad/schema.md` and `skills/squad/shared.md`. Scanning only these three keeps the guard
precise to that surface: it drops false-positive risk from unrelated prose elsewhere in the tree
(including this tests/ directory, which was never in scope) and it does NOT scan the agent
record-results TEMPLATES (the per-agent report-writing snippets, e.g. the tdd-tester template's
`api PATCH ... --json "{...}"` step). Those templates carry the exact same injection class —
free-text/rendered content pasted into a hand-built `--json "{...}"` or capture assignment — but
they are a KNOWN, DEFERRED surface: a separate architecture-strategy effort is deciding whether
agent-board access moves to a structured/MCP tool layer (in which case the template shell
assembly disappears entirely) or stays CLI-based (in which case a template-hardening pass follows
as its own piece of work, scoped and tested separately). Widening this guard to also cover the
templates now would mean testing — and freezing the shape of — a surface that may not exist in
its current form once that architecture decision lands.

Hermetic: reads committed skill files from disk only (the `repo_root` fixture), stdlib `re` only.
Lives under `tests/` — not shipped by `npx skills` and not itself scanned by the guards below.
"""
import re


# ── Scoped file set (see the SCOPE note above the module docstring's assertion list) ───
#
# The SINK guard and the CAPTURE guard both scan EXACTLY these three orchestrator files —
# not the whole skills/** tree. Deliberately excludes skills/squad/templates/*.md (the
# agent record-results templates): a distinct, deferred surface, see SCOPE above.
SCOPED_FILES = [
    "skills/squad-run/SKILL.md",
    "skills/squad/schema.md",
    "skills/squad/shared.md",
]


# ── The anti-pattern detector ───────────────────────────────────────────────────────
#
# A "sink" hands a hand-built double-quoted string straight to an interpreter:
#   - `python3 -c "..."`               — the program text itself
#   - `--json "{...}"`                 — a raw hand-rolled JSON literal (NOT `--json "$VAR"`,
#                                         which reads a pre-built body out-of-band — safe)
#   - `git commit -m "..."`            — the commit message text
# A "token" is a rendered/board-content placeholder that must never be pasted directly into one
# of those sinks. Angle-bracket placeholders are matched case-insensitively: the prompt-assembly
# mapping table uses lowercase `<title>`, while the pre-fix done-commit leak used uppercase
# `<TITLE>` for the very same class of content — the bracket form is load-bearing, not the case.
# Dollar-prefixed free-text vars follow the repo's uppercase convention ($REASON, $TITLE, $MESSAGE).
SINK = r'(?:python3\s+-c\s+"|--json\s+"\{|commit\s+-m\s+")'
ANGLE_TOKENS = [
    "spec", "plan", "description", "decision_log",
    "done_when", "implementation_notes", "title",
]
DOLLAR_TOKENS = ["REASON", "TITLE", "MESSAGE"]
TOKEN = (
    r'(?:<(?:' + "|".join(ANGLE_TOKENS) + r')>'
    r'|\$(?:' + "|".join(DOLLAR_TOKENS) + r')\b)'
)
# Sink, then (anywhere later on the SAME line) a token — line-scoped so the check can't wander
# into an unrelated later construction, and so it stays deterministic/grep-invariant.
VIOLATION_RE = re.compile(SINK + r'.*?' + TOKEN, re.IGNORECASE)


def _violations(text):
    """Return `[(lineno, line), ...]` for every line in `text` matching VIOLATION_RE."""
    return [
        (i, line) for i, line in enumerate(text.splitlines(), 1)
        if VIOLATION_RE.search(line)
    ]


# ── 1. The Shell Safety box is present in squad-run/SKILL.md ───────────────────────


def test_shell_safety_box_present(repo_root):
    """The doctrine moved from squad-run/SKILL.md's Shell Safety box to shared.md's
    'JSON safety (injection defense)' section (loaded by every skill), with the per-agent
    rule injected into every rendered prompt via templates/_shared.md. Non-brittle: assert
    several independent stable stems, not one exact phrase."""
    text = (repo_root / "skills/squad/shared.md").read_text(encoding="utf-8")

    assert re.search(r"JSON safety", text), (
        "shared.md must carry the 'JSON safety' section"
    )
    agent_rules = (repo_root / "skills/squad/templates/_shared.md").read_text(encoding="utf-8")
    assert re.search(r"data,\s*never\s*code", agent_rules), (
        "templates/_shared.md must carry the 'data, never code' rule for every agent prompt"
    )
    assert re.search(r"injection.defense", text, re.IGNORECASE), (
        "the box must frame itself as injection defense"
    )
    assert re.search(r"command.substitut", text, re.IGNORECASE), (
        "the box must explain the command-substitution mechanism (the WHY)"
    )
    assert re.search(r"data,\s*never\s*code", text, re.IGNORECASE) or re.search(
        r"out-of-band", text, re.IGNORECASE
    ), "the box must state the 'data, never code' rule / the out-of-band safe patterns"
    assert re.search(r"SILENT", text), (
        "the box must stress the failure is SILENT (no error surfaced)"
    )
    assert re.search(r"OWASP", text), (
        "the box must frame the defense per OWASP OS-command-injection guidance"
    )
    assert re.search(r"[Cc]apture is a sink", text), (
        "the box must name CAPTURE as a sink too (the impl_review send-back gap: a plain "
        "double-quoted VAR=\"<content>\" command-substitutes at the assignment line, before any "
        "downstream env/json.dumps handling can protect it)"
    )


# ── 2. The anti-pattern guard (the important one) ──────────────────────────────────


def test_no_rendered_content_placeholder_in_shell_sink(repo_root):
    """Within the SCOPED orchestrator file set (see module docstring), no snippet interpolates
    a rendered-content placeholder into a python3 -c "...", a raw --json "{...}", or a
    git commit -m "..." sink."""
    hits = []
    for rel_path in SCOPED_FILES:
        path = repo_root / rel_path
        text = path.read_text(encoding="utf-8")
        for lineno, line in _violations(text):
            hits.append(f"{rel_path}:{lineno}: {line.strip()}")
    assert not hits, (
        "rendered-content placeholder interpolated into a shell/python3/--json sink "
        "(board content is data, never code):\n" + "\n".join(hits)
    )


def test_scoped_files_exist_and_are_not_empty(repo_root):
    """Guard against a vacuous-pass: each scoped orchestrator file must actually exist and
    carry meaningful content, not be missing or trivially empty."""
    for rel_path in SCOPED_FILES:
        path = repo_root / rel_path
        assert path.is_file(), f"scoped file missing: {rel_path}"
        text = path.read_text(encoding="utf-8")
        assert len(text.splitlines()) >= 20, (
            f"{rel_path} has suspiciously few lines — either the file is unexpectedly "
            "empty/truncated or the repo_root fixture is broken"
        )


# ── 3. Planted-positive / non-vacuity ───────────────────────────────────────────────


def test_guard_flags_synthetic_violation():
    """Self-test: the detector must flag a placeholder inside python3 -c "..." and a
    free-text var inside --json "{...}", so it can never silently rot into a no-op."""
    bad_python = 'python3 -c "print(\'<spec>\')"'
    bad_json = r'  --json "{\"reason\": \"$REASON\"}"'
    bad_commit = r'  git commit -m "feat: <title> done"'

    assert VIOLATION_RE.search(bad_python), (
        "guard must flag a placeholder inside python3 -c \"...\""
    )
    assert VIOLATION_RE.search(bad_json), (
        "guard must flag a free-text var inside a raw --json \"{...}\" body"
    )
    assert VIOLATION_RE.search(bad_commit), (
        "guard must flag a placeholder inside git commit -m \"...\""
    )


def test_guard_does_not_flag_safe_patterns_or_prose():
    """Sanity: safe out-of-band patterns, mapping-table prose, and the box's own
    `<rendered-content>` sentinel must NOT trip the guard."""
    safe_lines = [
        # env var → os.environ, read INSIDE the program (safe pattern #2)
        ('BODY=$(MSG="$RENDERED" python3 -c "import json, os; '
         + 'print(json.dumps({\'message\': os.environ[\'MSG\']}))")'),
        # --json "$VAR" — a pre-built body passed out-of-band, not a raw literal
        'api POST /task/$ID/activity --json "$BODY"',
        # the step-④ placeholder-mapping TABLE — a token in prose, no sink on the line
        '     <spec>                   → rendered Refiner spec (Planner/Critic/Builder only)',
        # the box's own ❌ WRONG example — uses the <rendered-content> sentinel, not a real token
        r'#     api POST /task/$ID/activity --json "{\"message\": \"<rendered-content>\"}"',
        '#     python3 -c "print(\'<rendered-content>\')"',
        # the fixed done-commit line — $MSG variable expansion, not <title>/$TITLE
        'git commit -m "$MSG"',
    ]
    for line in safe_lines:
        assert not VIOLATION_RE.search(line), f"guard false-positived on a safe line: {line!r}"


# ── 4. Diff-sensitive: the guard would have flagged the real pre-Builder leaks ─────

# Verified verbatim against `git show HEAD:skills/squad-run/SKILL.md` (commit 4a2779e — the last
# commit before Builder's uncommitted SQD-954 fix) at test-authoring time. Hardcoded (not read
# live via git) so this assertion stays stable once the branch merges and HEAD moves past the fix.
PRE_BUILDER_OVERRIDE_REVIEW_LINE = (
    r'    --json "{\"gate\": \"$STATUS\", \"reason\": \"$REASON\", '
    r'\"expected_version\": $VER, \"correlation_id\": \"$CID\"}" 2>"$ERR"'
)
POST_BUILDER_OVERRIDE_REVIEW_LINE = (
    r'  api POST /task/$ID/override-review --json "$OVERRIDE_BODY" 2>"$ERR"'
)

PRE_BUILDER_DONE_COMMIT_LINE = r'  git commit -m "feat: <TITLE> [squad #<ID>]"'
POST_BUILDER_DONE_COMMIT_LINE = r'  git commit -m "$MSG"'


def test_guard_would_have_flagged_pre_builder_override_review_leak():
    """The override-review write-through used to interpolate the human's free-text $REASON
    directly into a raw --json "{...}" body — the guard must catch that, and must NOT catch
    the fixed line (which passes a pre-built $OVERRIDE_BODY out-of-band)."""
    assert VIOLATION_RE.search(PRE_BUILDER_OVERRIDE_REVIEW_LINE), (
        "guard must flag the pre-Builder override-review leak ($REASON inside a raw --json \"{...}\")"
    )
    assert not VIOLATION_RE.search(POST_BUILDER_OVERRIDE_REVIEW_LINE), (
        "guard must NOT flag the fixed override-review line (out-of-band $OVERRIDE_BODY)"
    )


def test_guard_would_have_flagged_pre_builder_done_commit_leak():
    """The done-commit step used to inline the literal <TITLE> placeholder straight into the
    git commit -m "..." message — the guard must catch that, and must NOT catch the fixed line
    (which builds $MSG as a variable first — expansion is inert)."""
    assert VIOLATION_RE.search(PRE_BUILDER_DONE_COMMIT_LINE), (
        "guard must flag the pre-Builder done-commit leak (<TITLE> inside git commit -m \"...\")"
    )
    assert not VIOLATION_RE.search(POST_BUILDER_DONE_COMMIT_LINE), (
        "guard must NOT flag the fixed done-commit line ($MSG variable expansion)"
    )


# ── 5. The CAPTURE guard (impl_review re-run — closes the send-back gap) ───────────
#
# A "capture" is a DIFFERENT sink than SINK/VIOLATION_RE above: it gets rendered/free-text
# content INTO a variable, not straight into an interpreter program. A plain double-quoted
# `VAR="<placeholder>"` assignment command-substitutes any backtick/`$(...)` in the placeholder
# text AT THE ASSIGNMENT LINE ITSELF — before any downstream env-var / json.dumps handling can
# protect it. This is exactly what the human-reject caught: the override-review REASON used to be
# `REASON="<the human's reason — required, non-empty>"`, and a reason containing a backtick or
# $(...) would have command-substituted right there, before the safe env → json.dumps handoff a
# few lines later. The safe capture form for orchestrator-emitted LITERAL free-text is a
# single-quoted heredoc (`VAR=$(cat <<'EOF' ... EOF)` — the quoted delimiter disables ALL
# expansion). A var-to-var expansion (`VAR="$OTHER"`) and a command-substitution capture
# (`VAR=$(... | jq -r ...)`) are also safe — neither re-substitutes a backtick/$(...) already
# inside the captured value; only a literal double-quoted capture of free-text is the sink.
#
# Anchored at line-start (`^\s*NAME="…"$`) so it only matches a genuine assignment statement —
# this naturally excludes prose/comment lines (`# REASON="..."`, `> #     REASON="..."`) without
# needing a separate comment-stripping pass, since those lines don't start with a bare identifier
# followed immediately by `=`. The box's own `<rendered-content>` ❌-example sentinel is excluded
# by name (reserved for illustrating the WRONG pattern; real placeholder/token names must never
# appear in a live double-quoted capture).
CAPTURE_RE = re.compile(
    r'^\s*[A-Za-z_][A-Za-z0-9_]*="[^"]*<(?!rendered-content>)[^">]+>[^"]*"\s*$'
)

# ── 5b. Tightened CAPTURE guard (class 7 above) — known free-text fields, ANY line position ──
#
# Not anchored to the whole line: a KNOWN free-text field name may share its line with other
# assignments (the schema.md:195 leak) or use an ellipsis/placeholder value instead of an
# angle-bracket token — CAPTURE_RE misses both. This guard is deliberately narrower in WHAT it
# matches (a fixed field-name allowlist, not any identifier) but broader in WHERE it matches
# (anywhere on the line), which is exactly the shape of the missed leak.
KNOWN_FREE_TEXT_FIELDS = [
    "MESSAGE", "REASON", "RUN_SUMMARY", "TRAJECTORY", "FRICTION_SIGNALS", "STEP_MSG",
]
KNOWN_FIELD_CAPTURE_RE = re.compile(
    r'\b(?:' + "|".join(KNOWN_FREE_TEXT_FIELDS) + r')="([^"]*)"'
)


def _is_comment_or_prose_line(line):
    """Bash never command-substitutes inside a `#` comment, so a doc line illustrating the
    anti-pattern in prose (`# ... a plain MESSAGE="<the text>" would command-substitute ...`) is
    not itself a violation. Strips leading blockquote `>` markers first (the Shell Safety box's
    own fenced examples are blockquoted), then checks for a `#`."""
    s = line.strip()
    while s.startswith(">"):
        s = s[1:].strip()
    return s.startswith("#")


def _is_safe_capture_value(value):
    """SAFE iff the captured value is a pure var-to-var re-expansion (`"$OTHER"` — bash never
    re-substitutes a variable's already-expanded value) or the box's own `<rendered-content>`
    ❌-example sentinel. Anything else double-quoted — an ellipsis, a real angle-bracket
    placeholder, actual free text — is a literal capture: the sink."""
    if value == "<rendered-content>":
        return True
    return bool(re.fullmatch(r'\$[A-Za-z_][A-Za-z0-9_]*', value))


def _known_field_capture_violations(text):
    """Return `[(lineno, line), ...]` for every line with a KNOWN free-text field captured via a
    literal (non-var, non-sentinel) double-quoted assignment, anywhere on the line."""
    hits = []
    for i, line in enumerate(text.splitlines(), 1):
        if _is_comment_or_prose_line(line):
            continue
        for m in KNOWN_FIELD_CAPTURE_RE.finditer(line):
            if not _is_safe_capture_value(m.group(1)):
                hits.append((i, line))
                break
    return hits


def _capture_violations(text):
    """Return `[(lineno, line), ...]` for every line in `text` matching either capture-guard
    shape: the original whole-line angle-token CAPTURE_RE, or the tightened
    known-field-anywhere-on-the-line KNOWN_FIELD_CAPTURE_RE (see both above)."""
    hits = []
    for i, line in enumerate(text.splitlines(), 1):
        if CAPTURE_RE.match(line):
            hits.append((i, line))
            continue
        if _is_comment_or_prose_line(line):
            continue
        for m in KNOWN_FIELD_CAPTURE_RE.finditer(line):
            if not _is_safe_capture_value(m.group(1)):
                hits.append((i, line))
                break
    return hits


def test_no_free_text_placeholder_in_capture_assignment(repo_root):
    """Within the SCOPED orchestrator file set (see module docstring), no snippet captures a
    rendered/free-text placeholder into a plain double-quoted VAR="<placeholder>" assignment
    (capture is a sink too: the backtick/$(...) command-substitutes AT THE ASSIGNMENT, before
    any downstream safe handling)."""
    hits = []
    for rel_path in SCOPED_FILES:
        path = repo_root / rel_path
        text = path.read_text(encoding="utf-8")
        for lineno, line in _capture_violations(text):
            hits.append(f"{rel_path}:{lineno}: {line.strip()}")
    assert not hits, (
        "rendered/free-text placeholder captured into a plain double-quoted VAR=\"<…>\" "
        "assignment (capture is a sink too — use a single-quoted heredoc, a var-to-var "
        "expansion, or a command-substitution capture instead):\n" + "\n".join(hits)
    )


def test_capture_guard_flags_synthetic_violation():
    """Self-test: the detector must flag a free-text placeholder captured via a plain
    double-quoted assignment, so it can never silently rot into a no-op."""
    bad_reason_capture = '  REASON="<the human\'s reason>"'
    assert CAPTURE_RE.match(bad_reason_capture), (
        "guard must flag a free-text placeholder captured into REASON=\"<…>\""
    )


def test_capture_guard_does_not_flag_safe_capture_forms():
    """Sanity: the three safe capture forms, and the box's own `<rendered-content>` ❌-example
    sentinel, must NOT trip the guard."""
    safe_lines = [
        # single-quoted heredoc opener — expansion fully disabled at capture
        "  REASON=$(cat <<'REASON_EOF'",
        # var-to-var expansion — no placeholder, `$OTHER` is inert on re-expansion
        'SOURCE_PROJECT="$PROJECT"',
        # command-substitution capture from a safe source (jq -r)
        "  VER=$(api GET /task/$ID?fields=version | jq -r '.version')",
        # the box's own ❌ WRONG capture example — comment-prefixed prose using the neutral
        # <rendered-content> sentinel, not a real token
        '> #     REASON="<rendered-content>"',
    ]
    for line in safe_lines:
        assert not CAPTURE_RE.match(line), f"guard false-positived on a safe capture line: {line!r}"


# ── 6. Diff-sensitive: the CAPTURE guard would have flagged the real pre-Builder leak ──

# Verified verbatim against `git show HEAD:skills/squad-run/SKILL.md` (commit 4a2779e — the last
# commit before Builder's uncommitted SQD-954 fix) at test-authoring time. Hardcoded (not read
# live via git) so this assertion stays stable once the branch merges and HEAD moves past the fix.
PRE_BUILDER_REASON_CAPTURE_LINE = '  REASON="<the human\'s reason — required, non-empty>"'
POST_BUILDER_REASON_CAPTURE_HEREDOC_OPENER = "  REASON=$(cat <<'REASON_EOF'"


def test_capture_guard_would_have_flagged_pre_builder_reason_capture_leak():
    """The override-review REASON used to be captured via a plain double-quoted assignment of
    free-text (`REASON="<the human's reason — required, non-empty>"`) — a backtick/$(...) in the
    human's actual reason would have command-substituted AT THAT LINE, before the safe env →
    json.dumps handoff further down. The guard must catch that, and must NOT catch the fixed
    single-quoted-heredoc capture opener (expansion fully disabled)."""
    assert CAPTURE_RE.match(PRE_BUILDER_REASON_CAPTURE_LINE), (
        "guard must flag the pre-Builder REASON capture leak (free text in REASON=\"<…>\")"
    )
    assert not CAPTURE_RE.match(POST_BUILDER_REASON_CAPTURE_HEREDOC_OPENER), (
        "guard must NOT flag the fixed REASON single-quoted-heredoc capture opener"
    )


# ── 7. Tightened CAPTURE guard (Inspector's impl_review re-run — closes the shared-line gap) ──


def test_no_known_field_literal_capture_in_scoped_files(repo_root):
    """Within the SCOPED orchestrator file set, no KNOWN free-text field (MESSAGE, REASON,
    RUN_SUMMARY, TRAJECTORY, FRICTION_SIGNALS, STEP_MSG) is captured via a literal double-quoted
    assignment — including one that shares its line with other assignments. This is the same
    scoped-file assertion as `test_no_free_text_placeholder_in_capture_assignment` (both guards
    feed the same `_capture_violations`); kept as its own test so a KNOWN_FIELD-only regression
    fails with an unambiguous name."""
    hits = []
    for rel_path in SCOPED_FILES:
        path = repo_root / rel_path
        text = path.read_text(encoding="utf-8")
        for lineno, line in _known_field_capture_violations(text):
            hits.append(f"{rel_path}:{lineno}: {line.strip()}")
    assert not hits, (
        "known free-text field captured via a literal double-quoted assignment, possibly "
        "sharing a line with other assignments (capture is a sink too):\n" + "\n".join(hits)
    )


def test_known_field_capture_guard_flags_synthetic_shared_line_violation():
    """Self-test (planted positive): a KNOWN free-text field captured via a plain double-quoted
    assignment that SHARES ITS LINE with other assignments, and uses an ellipsis placeholder
    rather than an angle-bracket token — exactly the shape CAPTURE_RE (class 5) missed. Also
    confirms CAPTURE_RE itself does NOT catch this shape (the whole point of the tightening)."""
    bad_shared_line = (
        'NICKNAME="Planner" MODEL="opus" MESSAGE="…" TASK_ID="$TASK_ID" '
        'PROJECT="$PROJECT" python3 -c "'
    )
    assert not CAPTURE_RE.match(bad_shared_line), (
        "sanity: the whole-line CAPTURE_RE was never supposed to catch this shared-line shape "
        "(that's exactly the gap this tightening closes)"
    )
    assert KNOWN_FIELD_CAPTURE_RE.search(bad_shared_line), (
        "KNOWN_FIELD_CAPTURE_RE must match the MESSAGE=\"…\" assignment on the shared line"
    )
    assert _known_field_capture_violations(bad_shared_line), (
        "tightened guard must flag a KNOWN field literal-captured on a line shared with other "
        "assignments"
    )
    assert _capture_violations(bad_shared_line), (
        "the unified _capture_violations (used by the scoped-file test) must also flag it"
    )


def test_known_field_capture_guard_does_not_flag_safe_forms_or_prose():
    """Sanity: var-to-var re-expansion (including on a shared line), heredoc openers,
    command-substitution captures, the `<rendered-content>` sentinel, and the two REAL doc lines
    that describe the anti-pattern in prose (comment-prefixed, using these exact field names)
    must NOT trip the tightened guard."""
    safe_lines = [
        # the fixed schema.md:204 form — MESSAGE="$MESSAGE" var-to-var, still on a shared line
        ('NICKNAME="Planner" MODEL="opus" MESSAGE="$MESSAGE" TASK_ID="$TASK_ID" '
         + 'PROJECT="$PROJECT" python3 -c "'),
        # the fixed SKILL.md:748 form — STEP_MSG="$STEP_MSG" var-to-var, shared line
        'BODY=$(AGENT_NICK="$AGENT_NICK" AGENT_MODEL="$AGENT_MODEL" STEP_MSG="$STEP_MSG" \\',
        # heredoc opener — `=$(cat <<'...'`, never matches the `="..."` capture shape at all
        "MESSAGE=$(cat <<'MESSAGE_EOF'",
        "RUN_SUMMARY=$(cat <<'RUN_SUMMARY_EOF'",
        # command-substitution capture from a safe source (jq -r)
        "  VER=$(api GET /task/$ID?fields=version | jq -r '.version')",
        # the box's own ❌ WRONG capture example — comment-prefixed, <rendered-content> sentinel
        '> #     REASON="<rendered-content>"',
        # REAL prose lines (schema.md, SKILL.md) illustrating the anti-pattern in a comment —
        # bash never command-substitutes inside a `#` comment, so these are not violations
        '# ALL expansion, so a backtick/$(…) in it stays inert AT THE ASSIGNMENT (a plain MESSAGE="<the text>"',
        '  #    REASON="<the reason>" would command-substitute right here, before the safe env handoff below).',
    ]
    for line in safe_lines:
        assert not _known_field_capture_violations(line), (
            f"tightened guard false-positived on a safe/prose line: {line!r}"
        )
        assert not _capture_violations(line), (
            f"unified _capture_violations false-positived on a safe/prose line: {line!r}"
        )


# ── 8. Diff-sensitive: the tightened guard catches the real Inspector-caught leak ──────────
#
# schema.md's shell-safety fix went through TWO stages on this branch: a first-pass fix (staged
# git blob `373fd41d988b211ecd0a0f25944715929d5747a8`, `git cat-file -p 373fd41d`) that closed the
# class-2 SINK gap (python3 -c body reads os.environ, not raw values) but left the class-7 CAPTURE
# gap open at line 195 — the exact leak the Inspector's impl_review re-run caught. Builder's
# second-pass fix (working tree, the single-quoted-heredoc MESSAGE capture) closes that too. `git
# show HEAD:skills/squad/schema.md` (commit 4a2779e) predates BOTH stages entirely (an older
# non-bash-capture form), so — unlike the class 4/6 SKILL.md assertions above — this is verified
# against the staged first-pass-fix blob, not HEAD. Hardcoded (not read live via git) so this
# assertion stays stable once the branch merges and the index moves past this intermediate state.
PRE_FIX_SCHEMA_MESSAGE_CAPTURE_LINE = (
    'NICKNAME="Planner" MODEL="opus" MESSAGE="…" TASK_ID="…" PROJECT="…" python3 -c "'
)
POST_FIX_SCHEMA_MESSAGE_CAPTURE_LINE = (
    'NICKNAME="Planner" MODEL="opus" MESSAGE="$MESSAGE" TASK_ID="$TASK_ID" '
    'PROJECT="$PROJECT" python3 -c "'
)


def test_known_field_capture_guard_would_have_flagged_inspector_caught_schema_leak():
    """The tightened guard must flag the exact line the Inspector's impl_review re-run caught
    (schema.md:195, staged pre-heredoc-fix), and must NOT flag Builder's actual fixed line
    (MESSAGE="$MESSAGE" var-to-var, still sharing the line with NICKNAME/MODEL/TASK_ID/PROJECT)."""
    assert _known_field_capture_violations(PRE_FIX_SCHEMA_MESSAGE_CAPTURE_LINE), (
        "guard must flag the Inspector-caught schema.md MESSAGE=\"…\" shared-line leak"
    )
    assert CAPTURE_RE.match(PRE_FIX_SCHEMA_MESSAGE_CAPTURE_LINE) is None, (
        "sanity: confirms the ORIGINAL class-5 guard genuinely missed this (whole-line anchor "
        "can't match a shared line) — this is the gap being closed, not a redundant check"
    )
    assert not _known_field_capture_violations(POST_FIX_SCHEMA_MESSAGE_CAPTURE_LINE), (
        "guard must NOT flag Builder's actual fixed schema.md line (var-to-var MESSAGE=\"$MESSAGE\")"
    )
    assert not _capture_violations(POST_FIX_SCHEMA_MESSAGE_CAPTURE_LINE), (
        "unified _capture_violations must also pass the fixed schema.md line"
    )
