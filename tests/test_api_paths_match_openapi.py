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
# Executable consumer surface: the `api <METHOD> <resource-path>` calls.
#
# Post-919 the skills issue board calls through the api.py helper rather than raw
# curl, e.g. `api GET /task/$ID/spec`. api.py's build_url prepends the org mount
# (`<base>/api/orgs/<org>` + resource-path) and merges project=<project> into the
# query, so the SERVER path is `/api/orgs/<org>/task/<id>/spec`. After the `/api`
# mount is stripped (the spec keys are server-relative) the comparison shape is
# `/orgs/{}/task/{}/spec`. We mirror build_url EXACTLY here: ensure the leading
# slash it adds, strip the query string (project is a query param, not a path
# segment), collapse param segments to PARAM, and prepend ('orgs', PARAM).
#
# Unlike the prose check there is NO "ignore" tier: every api() call is a real
# intended endpoint, so an unresolved call is always a failure — including the
# EDGE case of an api() call to a genuinely non-org-scoped endpoint, which api.py
# still org-scopes and so resolves to a path absent from the spec (a real 404).
# ---------------------------------------------------------------------------

# `api <METHOD> <token>`. `\bapi ` + a METHOD word excludes the `api()` wrapper
# DEFINITION line in shared.md (`api() { … }` — no METHOD follows). The token runs
# to the first whitespace; its query string + trailing prose punctuation (e.g. the
# closing paren in `api GET /projects)`) are stripped in _normalize_call.
_API_CALL_RE = re.compile(r"\bapi (GET|POST|PATCH|DELETE) (\S+)")


def _normalize_call(resource_path: str):
    """A raw api.py resource-path → collapsed SERVER-relative segment tuple, mirroring
    api.py build_url (`/api/orgs/<org>` + resource-path). Strips the query string and
    trailing prose punctuation, applies the leading slash build_url adds, collapses
    params to PARAM, and prepends ('orgs', PARAM) for the org mount.

    `/task/$ID/spec` → ('orgs', '{}', 'task', '{}', 'spec')
    """
    s = resource_path.lstrip("`\"'")                     # drop a leading quote (api GET "/task…")
    s = s.split("?", 1)[0].split("#", 1)[0]              # drop query / fragment
    s = s.rstrip("`\"'.,;:)/ \t")                         # drop trailing prose punctuation
    if not s.startswith("/"):
        s = "/" + s                                       # build_url prepends the slash
    return ("orgs", PARAM) + _collapse(s)


def _iter_api_calls(files):
    """Yield (file, line_no, method, raw_path, normalized_segs) for every executable
    `api <METHOD> <resource-path>` call across `files`."""
    for f in files:
        for i, line in enumerate(f.read_text().splitlines(), 1):
            for m in _API_CALL_RE.finditer(line):
                method, raw = m.group(1), m.group(2)
                yield f, i, method, raw, _normalize_call(raw)


def _api_call_offenders(files, spec_keys, repo_root):
    """List of 'skill:line: api METHOD raw (normalized …)' for executable calls whose
    normalized server path is absent from the snapshot."""
    offenders = []
    for f, i, method, raw, segs in _iter_api_calls(files):
        if not _matches_spec(segs, spec_keys):
            try:
                rel = f.relative_to(repo_root)
            except ValueError:
                rel = f
            offenders.append(f"{rel}:{i}: api {method} {raw}  (normalized /{'/'.join(segs)})")
    return offenders


def build_consumer_contract(repo_root):
    """The deduped, sorted {method, path} consumer surface the skills call — the
    bi-directional-CT 'consumer publishes its subset' artifact (tests/fixtures/
    consumer-contract.json). `path` is the server-relative shape (params → `{}`).
    Regenerate the committed file with scripts/refresh-consumer-contract.py."""
    seen = set()
    for _f, _i, method, _raw, segs in _iter_api_calls(_doc_files(repo_root)):
        seen.add((method, "/" + "/".join(segs)))
    return [{"method": m, "path": p} for m, p in sorted(seen)]


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


def test_executable_api_calls_match_openapi(repo_root):
    """Every executable `api <METHOD> <resource-path>` call in the skills resolves to a path
    in the OpenAPI snapshot once normalized through api.py's org mount. This is the real
    runtime surface (post-919) the prose check was blind to. Fails naming skill:line + the
    resolved server path."""
    spec_keys = _load_spec_keys(repo_root)
    files = _doc_files(repo_root)
    calls = list(_iter_api_calls(files))
    assert len(calls) >= 25, (
        f"the api() extractor found only {len(calls)} calls — it looks broken (a vacuous "
        "guard); the skills issue ~40 explicit `api <METHOD> <path>` calls (most board I/O "
        "now lives inside the packaged scripts, which have their own path coverage via "
        "the consumer contract)"
    )
    offenders = _api_call_offenders(files, spec_keys, repo_root)
    assert not offenders, (
        "an executable `api <METHOD> <path>` call resolves to a path not in the OpenAPI "
        "snapshot (tests/fixtures/openapi.json) — fix the call or refresh the snapshot "
        "(scripts/refresh-openapi.sh):\n" + "\n".join(offenders)
    )


def test_negative_control_executable_guard(repo_root, tmp_path):
    """Proves the executable extractor is LIVE, not vacuous: a bogus `api GET /tsak/{}`
    (typo of `task`) must turn the guard RED, while the real migrated tree stays GREEN."""
    spec_keys = _load_spec_keys(repo_root)

    bogus = tmp_path / "BOGUS_skill.md"
    bogus.write_text("Example call:\n\n    api GET /tsak/{}\n")
    red = _api_call_offenders([bogus], spec_keys, tmp_path)
    assert red, "negative control failed: bogus `api GET /tsak/{}` was NOT caught by the guard"

    green = _api_call_offenders(_doc_files(repo_root), spec_keys, repo_root)
    assert not green, "the real migrated tree must pass clean:\n" + "\n".join(green)


def test_consumer_contract_in_sync(repo_root):
    """The committed consumer-contract.json (the published consumer subset) stays in sync with
    the api() surface — regenerate-and-diff, exactly like the OpenAPI snapshot. If the skills'
    api() calls change, regenerate with scripts/refresh-consumer-contract.py."""
    expected = build_consumer_contract(repo_root)
    path = repo_root / "tests" / "fixtures" / "consumer-contract.json"
    assert path.is_file(), (
        "tests/fixtures/consumer-contract.json is missing — generate it with "
        "scripts/refresh-consumer-contract.py"
    )
    committed = json.loads(path.read_text())
    assert committed == expected, (
        "consumer-contract.json is stale (the api() surface changed) — regenerate it with "
        "scripts/refresh-consumer-contract.py and commit the diff"
    )
