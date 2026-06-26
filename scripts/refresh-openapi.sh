#!/usr/bin/env bash
# Refresh the vendored OpenAPI snapshot used by the doc-contract guard
# (tests/test_api_paths_match_openapi.py).
#
# The guard validates every `/api/…` path referenced in the skills docs against
# this snapshot, so the snapshot must track the live platform spec. This refresh
# is intentionally explicit + reviewable (a committed diff), NOT auto-fetched at
# test time — the test stays hermetic (no network) and a spec change shows up as
# a reviewed fixture diff.
#
# The public spec is unauthenticated (GET /api/openapi.json → 200, no token).
# The `/api` is the server base; the path KEYS inside are org-relative, e.g.
# `/orgs/{org}/run-audit`.
#
# Usage:  scripts/refresh-openapi.sh [BASE_URL]
set -euo pipefail

BASE_URL="${1:-${SQUAD_BASE_URL:-https://squad-api-285415501393.asia-south1.run.app}}"
DEST="$(cd "$(dirname "$0")/.." && pwd)/tests/fixtures/openapi.json"

mkdir -p "$(dirname "$DEST")"

echo "Fetching OpenAPI spec from ${BASE_URL}/api/openapi.json …"
http_code=$(curl -sL -w '%{http_code}' -o "$DEST.tmp" "${BASE_URL}/api/openapi.json")
if [ "$http_code" != "200" ]; then
  echo "ERROR: expected HTTP 200, got ${http_code}" >&2
  rm -f "$DEST.tmp"
  exit 1
fi

# Sanity: must be JSON with a non-trivial `paths` object before we overwrite.
count=$(python3 -c 'import json,sys; print(len(json.load(open(sys.argv[1]))["paths"]))' "$DEST.tmp")
if [ "$count" -lt 25 ]; then
  echo "ERROR: spec has only ${count} paths (<25) — refusing to write a truncated snapshot" >&2
  rm -f "$DEST.tmp"
  exit 1
fi

mv "$DEST.tmp" "$DEST"
echo "Wrote ${DEST} (${count} paths)."
