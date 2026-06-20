"""Structural guards for the path-based org-scoping adoption.

The board's org-scoped surface moved every org-scoped board call from the flat
`$BASE_URL/api/<resource>` to `$BASE_URL/api/orgs/$SQUAD_ORG/<resource>` (org in the PATH,
`?project=` stays in the QUERY). Hard-cut, no back-compat: the flat mounts are gone server-side.

These deterministic grep/import invariants (mirroring test_activity_adoption.py and
test_relationship_adoption.py) keep the migration from silently regressing — a re-inlined flat
`$BASE_URL/api/task` curl, a python helper that forgets the org segment, a board curl that drops
`-L` (so a former-slug 308 isn't followed), or a relaxed SQUAD_ORG-required contract.

SQUAD_ORG is REQUIRED everywhere: unset → a fail-fast pre-flight error pointing at the mint
dialog's `SQUAD_ORG=<slug>` line / `.squadrc` (resolution order env > `.squadrc`).
"""
import re


def _skill_files(repo_root):
    """Authored skill + eval sources (markdown + python), excluding this test dir."""
    files = []
    for d in ("skills", "evals"):
        base = repo_root / d
        if base.exists():
            files += list(base.rglob("*.md")) + list(base.rglob("*.py"))
    return files


# Executable board-call markers (NOT prose endpoint-shorthand, which has no $BASE_URL/{base_url}).
# A "flat" org-scoped call is one of these resources reached WITHOUT the /api/orgs/<org>/ prefix.
_BASE_TOKENS = (r"\$BASE_URL", r"\$SQUAD_BASE_URL_FOR_REPORTS", r"\{base_url\}")
_FLAT_RE = re.compile(
    r"(?:" + "|".join(_BASE_TOKENS) + r")/api/"
    r"(?!orgs/)"          # already org-scoped → fine
    r"(?!auth\b)"         # non-org: auth stays flat
    r"(?!openapi\b)"      # non-org: openapi stays flat
    r"(?!docs\b)"
    r"(?!api-keys\b)"
    r"(?:healthz|readyz)?"  # non-org liveness (no resource after) stays flat
    r"(task|board|projects|run-audit|run-audits|activity)\b"
)


def test_no_flat_orgscoped_board_call_remains(repo_root):
    """Every executable org-scoped board call ($BASE_URL/{base_url}-prefixed) carries the
    /api/orgs/<org>/ prefix. No flat $BASE_URL/api/(task|board|projects|run-audit|activity)
    survives. Prose endpoint-shorthand (`/api/task/:id/...` with no $BASE_URL) is untouched."""
    offenders = []
    for p in _skill_files(repo_root):
        for i, line in enumerate(p.read_text().splitlines(), 1):
            if _FLAT_RE.search(line):
                offenders.append(f"{p.relative_to(repo_root)}:{i}: {line.strip()}")
    assert not offenders, (
        "flat (non-org) board calls remain — must be /api/orgs/$SQUAD_ORG/<resource>:\n"
        + "\n".join(offenders)
    )


def test_org_scoped_calls_use_org_path(repo_root):
    """Sanity: the migrated calls actually use the org path (the rewrite happened, not just the
    flat calls being deleted). At least one /api/orgs/$SQUAD_ORG/ curl exists in shared.md."""
    text = (repo_root / "skills" / "squad" / "shared.md").read_text()
    assert "/api/orgs/$SQUAD_ORG/" in text, (
        "shared.md must issue org-scoped board curls (/api/orgs/$SQUAD_ORG/<resource>)"
    )


def test_board_curls_carry_dash_L(repo_root):
    """Every board curl follows a former-slug 308 redirect via -L. No `curl -s`/`curl -sf`
    (without L) targets an org-scoped board URL in the same statement/line."""
    # Match a curl whose flag cluster lacks L on a line that also contains an org-scoped URL.
    bad = re.compile(r"\bcurl\s+-s(?:[a-km-zA-KM-Z]+)?(?:\s|\")")  # -s... without an 'L'
    offenders = []
    for p in _skill_files(repo_root):
        for i, line in enumerate(p.read_text().splitlines(), 1):
            if "/api/orgs/" not in line:
                continue
            if "curl" not in line:
                continue
            m = re.search(r"\bcurl\s+(-s[a-zA-Z]*)", line)
            if m and "L" not in m.group(1):
                offenders.append(f"{p.relative_to(repo_root)}:{i}: {line.strip()}")
    assert not offenders, (
        "board curls must carry -L (follow the former-slug 308):\n" + "\n".join(offenders)
    )


def test_plan_batch_fetch_task_builds_org_path(repo_root, plan_batch):
    """plan_batch.fetch_task builds an /api/orgs/{org}/task/... URL and requires an `org` arg."""
    import inspect

    sig = inspect.signature(plan_batch.fetch_task)
    assert "org" in sig.parameters, "fetch_task must take an `org` parameter"
    src = inspect.getsource(plan_batch.fetch_task)
    assert "/api/orgs/" in src, "fetch_task must build an /api/orgs/{org}/ URL"
    assert "/api/task/" not in src.replace("/api/orgs/", ""), (
        "fetch_task must not build a flat /api/task/ URL"
    )


def test_plan_batch_main_requires_squad_org(repo_root, plan_batch):
    """plan_batch.main fails fast (SystemExit) when SQUAD_ORG is unset — every call is org-scoped."""
    import inspect

    src = inspect.getsource(plan_batch.main)
    assert "SQUAD_ORG" in src, "main must read SQUAD_ORG"
    assert "SystemExit" in src and "SQUAD_ORG is not set" in src, (
        "main must fail fast with an actionable error when SQUAD_ORG is unset"
    )


def test_plan_batch_main_fails_fast_at_runtime_when_squad_org_unset(plan_batch, monkeypatch):
    """Runtime guard: plan_batch.main() raises SystemExit with the actionable error when
    SQUAD_ORG is missing from the environment.  Source-inspection alone (the sibling test above)
    would still pass if the error string were refactored into a helper; this test exercises the
    real fail-fast path end-to-end, no board call required."""
    import sys
    import pytest

    monkeypatch.delenv("SQUAD_ORG", raising=False)
    # Provide the required argparse args so the parser doesn't fail first.
    monkeypatch.setattr(sys, "argv", ["plan_batch.py", "--project", "test", "--tasks", "1"])
    with pytest.raises(SystemExit) as exc_info:
        plan_batch.main()
    msg = str(exc_info.value)
    assert "SQUAD_ORG is not set" in msg, (
        f"fail-fast message must say 'SQUAD_ORG is not set'; got: {msg!r}"
    )


def test_shared_documents_squad_org_required(repo_root):
    """shared.md fails fast (exit 1) on an unset SQUAD_ORG with the actionable, id-free error
    pointing at the mint dialog's SQUAD_ORG=<slug> line / .squadrc. Resolution order env > .squadrc."""
    text = (repo_root / "skills" / "squad" / "shared.md").read_text()
    assert "ERROR: SQUAD_ORG is not set" in text, "shared.md must fail-fast on unset SQUAD_ORG"
    assert "/api/orgs/" in text, "shared.md error must reference the org-scoped surface"
    assert "SQUAD_ORG=<slug>" in text, "error must point at the mint dialog's SQUAD_ORG=<slug> line"
    assert ".squadrc" in text, "error must point at .squadrc"
    assert "env > .squadrc" in text, "resolution order (env > .squadrc) must be documented"


def test_squad_init_always_writes_squad_org(repo_root):
    """squad-init ALWAYS writes SQUAD_ORG=<slug> to .squadrc (REQUIRED, not optional) and errors
    id-free if no slug can be resolved (does not register without one)."""
    text = (repo_root / "skills" / "squad-init" / "SKILL.md").read_text()
    assert "REQUIRED" in text, "squad-init must mark SQUAD_ORG required"
    assert "ERROR: SQUAD_ORG is not set" in text, (
        "squad-init must fail fast (id-free) when no slug is resolvable"
    )
    assert "/api/orgs/$SQUAD_ORG/projects" in text, (
        "squad-init's own POST /projects must be org-scoped"
    )
    # The old 'only when supplied / optional' contract must be gone.
    assert "OPTIONAL — only when the user supplies" not in text, (
        "squad-init must no longer treat SQUAD_ORG as optional"
    )
