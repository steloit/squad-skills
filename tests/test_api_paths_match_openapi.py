"""Doc-contract guard: every `/api/…` path in the skills docs is a real platform endpoint.

The skills docs hand-write board API calls (`curl … $BASE_URL/api/orgs/$SQUAD_ORG/task/…`)
and endpoint prose (`POST /api/orgs/{org}/run-audit`). Nothing machine-checks that those
paths still exist server-side, so a renamed/removed/unscoped endpoint drifts silently until
an agent hits a 404 at runtime. This guard closes that gap: it extracts every `/api/…` token
from the authored docs and asserts each one resolves to a path in a *vendored* OpenAPI
snapshot (tests/fixtures/openapi.json), failing — naming the offending doc:line + path — on
drift. It is hermetic (reads the committed snapshot, no network); refresh the snapshot
explicitly with scripts/refresh-openapi.sh when the platform spec changes.

Concrete contract this enforces (the run-audit org-scoping acceptance case): the org-scoping migration moved
run-audit under the org path, so a bare `POST /api/run-audit` (unscoped → 404) must FAIL the
guard while `POST /api/orgs/{org}/run-audit` (200) must PASS.

Normalization is parameter-name-agnostic: doc placeholders ($VAR, :param, <VAR>, {var}) and the
spec's own `{param}` segments all collapse to a single `{}` sentinel, so we compare *path shape*,
not the names doc authors happen to pick.
"""
import json
import pathlib
import re

# A collapsed parameter segment. Doc placeholders and spec `{param}` segments both map here.
PARAM = "{}"

# Spec server base. The spec's path KEYS are server-relative (e.g. `/orgs/{org}/task`); the docs
# write them under the `/api` mount (e.g. `/api/orgs/$ORG/task`). We strip `/api` before matching.
_API_PREFIX = "/api"

# Bare-resource shorthands that historically appear WITHOUT the `/api/orgs/<org>/` prefix in prose
# (legacy endpoint-shorthand, e.g. `/api/task/:id/relationships`). For these families ONLY we also
# accept the path with `/orgs/{}` prepended. This is a deliberate POLICY subset of the spec
# vocabulary — NOT every resource. `run-audit`/`run-audits` are intentionally EXCLUDED so a bare
# `/api/run-audit` fails the guard (it was never exposed unscoped; org-scoped is the only 200 form).
SHORTHAND_FAMILIES = frozenset({"task", "board", "projects", "activity"})

# Docs the guard scans (authored surface that hand-writes API paths).
_DOC_GLOBS = (
    "skills/squad/shared.md",
    "skills/squad/schema.md",
    "skills/squad/templates/*.md",
    "skills/*/SKILL.md",
)

# Capture `/api/…` runs up to the first whitespace / quote / backtick / bracket / paren. Query
# string and trailing punctuation are stripped in _normalize.
_API_TOKEN_RE = re.compile(r"/api/[^\s`\"'()\[\]<>]*(?:<[^>\s]+>[^\s`\"'()\[\]<>]*)*")
# Note: the inner group lets a `<placeholder>` (which contains no whitespace) stay inside the token,
# e.g. `/api/orgs/$ORG/task/<ID>/review` is captured whole.


def _doc_files(repo_root):
    files = []
    for pattern in _DOC_GLOBS:
        files += sorted(repo_root.glob(pattern))
    # De-dup while preserving order (a path can match two globs in principle).
    seen, out = set(), []
    for f in files:
        if f not in seen:
            seen.add(f)
            out.append(f)
    return out


def _is_param_segment(seg: str) -> bool:
    """A path segment is a parameter if it carries any placeholder marker:
    `$VAR` (shell), `:param` (express), `<VAR>` (angle prose), `{var}` (openapi/prose)."""
    return bool(re.search(r"[$:<{]", seg))


def _collapse(path: str):
    """Server-relative path string → tuple of segments with params collapsed to PARAM.

    `/orgs/{org}/task/{id}/comment` → ('orgs', '{}', 'task', '{}', 'comment')
    """
    segs = []
    for seg in path.strip("/").split("/"):
        if not seg:
            continue
        segs.append(PARAM if _is_param_segment(seg) else seg)
    return tuple(segs)


def _normalize_ref(token: str):
    """A raw `/api/…` doc token → collapsed server-relative segment tuple (params → PARAM).

    Strips the `/api` mount, the query string, and trailing prose punctuation (incl. the `…`/`...`
    ellipsis docs use for "and the rest of the org surface"). Returns () for a bare `/api` token.
    """
    s = token.split("?", 1)[0].split("#", 1)[0]  # drop query / fragment
    s = s.rstrip("`\"'.,;:)/ \t")                 # drop trailing punctuation, slashes, ellipsis dots
    if not s.startswith(_API_PREFIX):
        return ()
    rel = s[len(_API_PREFIX):]                    # server-relative remainder ('' or '/orgs/…')
    return _collapse(rel)


def _load_spec_keys(repo_root):
    spec = json.loads((repo_root / "tests" / "fixtures" / "openapi.json").read_text())
    return [_collapse(p) for p in spec["paths"]]


def _derive_vocabulary(spec_keys):
    """First-segment vocabulary derived FROM the spec (never hand-maintained).

    A doc `/api/<first>/…` reference is only checked when <first> is a real entry point:
      * the literal first segment of any spec key  → `onboarding`, `orgs`
      * the resource segment that sits directly under the `/orgs/{org}/` PARAM
        → `activity, artifacts, board, pats, projects, run-audit, run-audits, task, uploads`
    We take ONLY the segment immediately after the org PARAM (index 2), never deeper segments,
    so sub-routes like `detail`/`plan-review`/`relationships` are NOT mistaken for first segments.
    `/orgs/check-slug` & `/orgs/resolve` have a literal (non-PARAM) 2nd segment, so they contribute
    only `orgs` here — correct, since no doc references them as a bare first segment.
    Anything outside this vocabulary (e.g. the illustrative `POST /api/items`) is IGNORED, not failed.
    """
    vocab = set()
    for segs in spec_keys:
        if not segs:
            continue
        vocab.add(segs[0])
        if segs[0] == "orgs" and len(segs) >= 3 and segs[1] == PARAM:
            vocab.add(segs[2])
    return vocab


def _matches_spec(candidate, spec_keys):
    """True iff `candidate` equals a spec key OR is a segment-prefix of one (an ancestor path,
    e.g. the prose org-root `/orgs/{}` is an ancestor of `/orgs/{}/task`). Extra/typo'd trailing
    segments are NOT a prefix, so they still fail."""
    n = len(candidate)
    return any(len(k) >= n and k[:n] == candidate for k in spec_keys)


def _classify(ref_segs, spec_keys, vocabulary):
    """('ignore' | 'valid' | 'invalid') for a normalized reference."""
    if not ref_segs:
        return "ignore"  # bare `/api` or `/api/` — nothing to check
    if ref_segs[0] not in vocabulary:
        return "ignore"  # not a board entry point (e.g. /api/items)
    if _matches_spec(ref_segs, spec_keys):
        return "valid"
    if ref_segs[0] in SHORTHAND_FAMILIES and _matches_spec((("orgs", PARAM) + ref_segs), spec_keys):
        return "valid"
    return "invalid"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_doc_api_paths_match_openapi(repo_root):
    """Every `/api/…` path referenced in the authored skills docs resolves to a path in the
    vendored OpenAPI snapshot (param-name-agnostic). Fails naming each offending doc:line + path."""
    spec_keys = _load_spec_keys(repo_root)
    vocabulary = _derive_vocabulary(spec_keys)

    offenders = []
    for p in _doc_files(repo_root):
        for i, line in enumerate(p.read_text().splitlines(), 1):
            for m in _API_TOKEN_RE.finditer(line):
                token = m.group(0)
                ref = _normalize_ref(token)
                if _classify(ref, spec_keys, vocabulary) == "invalid":
                    rel = p.relative_to(repo_root)
                    offenders.append(f"{rel}:{i}: {token}  (normalized {'/'.join(ref)})")

    assert not offenders, (
        "doc references an /api path that is not in the OpenAPI snapshot "
        "(tests/fixtures/openapi.json) — fix the doc or refresh the snapshot "
        "(scripts/refresh-openapi.sh):\n" + "\n".join(offenders)
    )


def test_snapshot_present_and_not_truncated(repo_root):
    """Snapshot floor: ≥25 paths (a path-count floor, NOT a byte-equal assertion — robust to the
    server adding response fields). Guards against a fixture truncated to a handful of paths."""
    spec_keys = _load_spec_keys(repo_root)
    assert len(spec_keys) >= 25, (
        f"OpenAPI snapshot has only {len(spec_keys)} paths (<25) — looks truncated; "
        "refresh it with scripts/refresh-openapi.sh"
    )


def test_vocabulary_derived_from_spec(repo_root):
    """The first-segment vocabulary is derived from the spec and the shorthand families are a
    subset of it (no hand-list drift)."""
    spec_keys = _load_spec_keys(repo_root)
    vocab = _derive_vocabulary(spec_keys)
    assert {"orgs", "task", "run-audit", "run-audits"} <= vocab, (
        f"expected core resources in the derived vocabulary; got {sorted(vocab)}"
    )
    assert SHORTHAND_FAMILIES <= vocab, (
        "shorthand families must be a subset of the spec-derived vocabulary"
    )


def test_classifier_catches_fabricated_org_paths(repo_root):
    """Adversarial false-PASS guard: syntactically valid org-scoped paths that reference
    nonexistent endpoints must be classified 'invalid', not silently passed.

    This covers the primary drift scenario: a doc author adds a new endpoint reference
    (e.g. /api/orgs/$ORG/new-endpoint or /api/orgs/$ORG/task/$ID/new-sub) before the
    snapshot is refreshed. The classifier must reject them even though the org prefix
    and param placeholders are perfectly formed.

    Also covers a typo'd leaf (/api/orgs/$ORG/task/$ID/activityy → invalid) to guard
    against _matches_spec being accidentally loosened to a substring match.
    """
    spec_keys = _load_spec_keys(repo_root)
    vocab = _derive_vocabulary(spec_keys)

    fabricated_top = _normalize_ref("/api/orgs/$ORG/nonexistent")
    assert _classify(fabricated_top, spec_keys, vocab) == "invalid", (
        "/api/orgs/$ORG/nonexistent must be caught — no such top-level org endpoint in spec"
    )

    fabricated_sub = _normalize_ref("/api/orgs/$ORG/task/$ID/nonexistent-sub")
    assert _classify(fabricated_sub, spec_keys, vocab) == "invalid", (
        "/api/orgs/$ORG/task/$ID/nonexistent-sub must be caught — no such sub-resource in spec"
    )

    typo_leaf = _normalize_ref("/api/orgs/$ORG/task/$ID/activityy")  # extra 'y'
    assert _classify(typo_leaf, spec_keys, vocab) == "invalid", (
        "typo'd leaf /api/orgs/$ORG/task/$ID/activityy must be caught — prefix match must not degrade to substring"
    )


def test_run_audit_contract(repo_root):
    """The run-audit org-scoping acceptance case, asserted on the classifier directly:
    bare `/api/run-audit` is INVALID (unscoped → 404) while `/api/orgs/{org}/run-audit` is VALID
    (org-scoped → 200). Also a positive sanity check that a known org path is recognized."""
    spec_keys = _load_spec_keys(repo_root)
    vocab = _derive_vocabulary(spec_keys)

    bare = _normalize_ref("/api/run-audit?project=squad")
    scoped = _normalize_ref("/api/orgs/{org}/run-audit?project=squad")
    assert _classify(bare, spec_keys, vocab) == "invalid", (
        "bare /api/run-audit must FAIL the guard (unscoped endpoint is a 404)"
    )
    assert _classify(scoped, spec_keys, vocab) == "valid", (
        "/api/orgs/{org}/run-audit must PASS the guard (org-scoped is the 200 form)"
    )
    # A known good shorthand and a known org path both classify valid.
    assert _classify(_normalize_ref("/api/task/:id/relationships"), spec_keys, vocab) == "valid"
    assert _classify(_normalize_ref("/api/orgs/$ORG/board?project=p"), spec_keys, vocab) == "valid"
    # The illustrative non-board example is ignored, not failed.
    assert _classify(_normalize_ref("/api/items"), spec_keys, vocab) == "ignore"
