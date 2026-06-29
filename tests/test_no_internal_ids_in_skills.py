"""Regression guard: shipped skills/** files carry NO internal board IDs or backend paths.

The skills/** tree is installed on user machines (`npx skills add …`) and run by
their coding agents. Internal board-tracking IDs (the team's `<KEY>-<seq>` tickets,
whose real key is `SQD`) and backend source paths (`packages/<lib>`, the `@squad/`
npm scope) are meaningless to end users and leak internal tracking. This test scans
every shipped file (`.md`, `.py`, any extension) and fails on a match, so the leak
cannot silently regress.

This file lives under `tests/` — which is NOT shipped by `npx skills` and is NOT
self-scanned — so it may freely hold the literal patterns and a planted reference.
Stdlib only (`re`, `pathlib`); uses the existing `repo_root` session fixture.
"""
import re

# The real internal board key is SQD; an internal ticket is `SQD-<digits>`.
SQD_ID = re.compile(r"SQD-[0-9]+")
# Backend source leaks: the monorepo `packages/<lowercase-lib>` path and the
# `@squad/` npm scope. `package.json` (capital-free but no slash+letter) does not
# match `packages/[a-z]`; this is intentionally scoped to the source-tree path.
BACKEND_PATH = re.compile(r"packages/[a-z]|@squad/")


def scan(text):
    """Return the list of offending substrings for both patterns (empty ⇒ clean)."""
    return SQD_ID.findall(text) + BACKEND_PATH.findall(text)


def _offending_lines(path, pattern):
    """Yield `path:lineno: line` for every line in `path` matching `pattern`."""
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, ValueError):
        return  # skip undecodable binaries
    for i, line in enumerate(text.splitlines(), 1):
        if pattern.search(line):
            yield f"{path}:{i}: {line.strip()}"


def test_no_internal_board_ids_in_shipped_skills(repo_root):
    """No shipped skills/** file contains an internal `SQD-<n>` board id."""
    hits = []
    for path in sorted((repo_root / "skills").rglob("*")):
        if path.is_file():
            hits.extend(_offending_lines(path, SQD_ID))
    assert not hits, "internal board IDs found in shipped skills/**:\n" + "\n".join(hits)


def test_no_backend_paths_in_shipped_skills(repo_root):
    """No shipped skills/** file leaks a backend source path (`packages/<lib>`, `@squad/`)."""
    hits = []
    for path in sorted((repo_root / "skills").rglob("*")):
        if path.is_file():
            hits.extend(_offending_lines(path, BACKEND_PATH))
    assert not hits, "backend source paths found in shipped skills/**:\n" + "\n".join(hits)


def test_guard_detects_planted_refs():
    """Self-test: the scanner flags a synthetic id + both backend-path forms, so it
    can never rot into a silent no-op."""
    matches = scan("see SQD-123 and packages/types/x.ts and @squad/db")
    assert "SQD-123" in matches
    # BACKEND_PATH captures the first 10 chars (`packages/t`) — assert by prefix so
    # the check survives a regex tweak that changes capture width.
    assert any(m.startswith("packages/") for m in matches), (
        "BACKEND_PATH regex did not match 'packages/...' — regex may be broken"
    )
    assert "@squad/" in matches


def test_skills_tree_is_not_empty(repo_root):
    """Guard against a vacuous-pass: the skills/ tree must have enough shipped files
    that a clean scan is meaningful, not trivially empty."""
    files = [p for p in (repo_root / "skills").rglob("*") if p.is_file()]
    assert len(files) >= 15, (
        f"skills/ has only {len(files)} file(s) — suspiciously few; "
        "either the tree is unexpectedly empty or the repo_root fixture is broken"
    )


def test_guard_file_io_path_via_tmp(tmp_path):
    """End-to-end proof that _offending_lines() reads actual files on disk.
    The self-test above only exercises scan(); this test exercises the file I/O
    path so a regression there cannot silently skip the disk check."""
    # ── SQD ref ──────────────────────────────────────────────────────────────
    planted_sqd = tmp_path / "planted_sqd.md"
    planted_sqd.write_text("# OK\nSee SQD-999 below.\n# end\n", encoding="utf-8")
    hits_sqd = list(_offending_lines(planted_sqd, SQD_ID))
    assert len(hits_sqd) == 1, f"expected 1 hit, got {hits_sqd}"
    assert "SQD-999" in hits_sqd[0]
    assert "planted_sqd.md" in hits_sqd[0]

    # ── backend path ref ─────────────────────────────────────────────────────
    planted_path = tmp_path / "planted_path.md"
    planted_path.write_text("source lives in packages/types/activity.ts\n", encoding="utf-8")
    hits_path = list(_offending_lines(planted_path, BACKEND_PATH))
    assert len(hits_path) == 1, f"expected 1 hit, got {hits_path}"
    assert "packages/" in hits_path[0]

    # ── clean file ────────────────────────────────────────────────────────────
    clean = tmp_path / "clean.md"
    clean.write_text("# Nothing to see here\nAll ABC-99 examples only.\n", encoding="utf-8")
    assert list(_offending_lines(clean, SQD_ID)) == []
    assert list(_offending_lines(clean, BACKEND_PATH)) == []
