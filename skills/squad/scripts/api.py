#!/usr/bin/env python3
"""api.py — the single zero-dependency board-access helper for Squad skills.

Every skill issues board calls through this helper instead of hand-assembling
curl + auth + JSON. It owns, internally and opaquely to the calling agent:

  - Auth      — resolve the Personal Access Token by the SQUAD_AUTH_TOKEN= key
                name only (env > ~/.squad/auth). The token is OPAQUE: never
                matched/validated/filtered by value, prefix, length, or format;
                never echoed or logged; never accepted as a CLI arg (kept out of
                argv / process listings).
  - Transport — BASE_URL (env > ~/.squad/config > deployed default), the
                /api/orgs/<org>/ path prefix, a fail-fast SQUAD_ORG pre-flight,
                the project query param, Content-Type set once.
  - JSON      — encode request bodies and pass response bodies through (closes
                the echo|jq control-char mangling class).
  - Errors    — map 401/no-token to mint/refresh guidance; surface 4xx/5xx
                cleanly; map outcomes onto a stable exit-code taxonomy.

Invocation:
  api.py <METHOD> <resource-path> [--json <@file|inline|->] [-q <dotted.path>]

  METHOD        GET | POST | PATCH | DELETE
  resource-path the board path AFTER the org prefix (e.g. /task/<id>,
                /task/<id>/spec, /board, /projects). api.py prepends
                /api/orgs/<org> and merges project=<project>.

I/O contract: machine-readable result to STDOUT, diagnostics to STDERR, never
mixed. On any non-zero exit, stdout stays empty.

Exit codes:
  0  success
  2  usage error (bad args, missing --json @file, SQUAD_ORG unset)
  3  auth (HTTP 401, or no token configured) — stderr carries mint/refresh fix
  4  client error (other 4xx, or -q path absent in the response)
  5  server error (5xx)
  6  network / transport failure
"""
import argparse
import json
import os
import pathlib
import sys
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_BASE_URL = "https://squad-api-285415501393.asia-south1.run.app"
TOKEN_KEY = "SQUAD_AUTH_TOKEN="


def is_skill_dir(path):
    """True when `path` looks like an installed skill directory (holds a SKILL.md).

    A skill-local script that operates on the USER's repo (writing .squadrc,
    resolving the project from the directory) must refuse to run against a skill
    directory. The failure mode this guards: an agent resolves a relative script
    path by cd-ing into the skill dir, so the script silently operates on the
    skill itself instead of the user's project — writing config into the install
    and polluting it with stale state."""
    return (pathlib.Path(path) / "SKILL.md").is_file()


def _read_keyed_line(path, key):
    """Return the value after the first `key` line in `path` (key includes the
    trailing '='), keeping everything after that first '=' verbatim — mirrors
    shared.md's `grep '^KEY=' | cut -d= -f2-`. Returns "" if absent/unreadable."""
    try:
        if not path.is_file():
            return ""
        for line in path.read_text().splitlines():
            if line.startswith(key):
                return line[len(key):]
    except OSError:
        return ""
    return ""


def resolve_project():
    # env > .squadrc SQUAD_PROJECT= > current-directory name (symmetric with
    # resolve_org: env overrides the committed file, then a built-in default).
    proj = os.environ.get("SQUAD_PROJECT", "")
    if proj:
        return proj
    proj = _read_keyed_line(pathlib.Path(".squadrc"), "SQUAD_PROJECT=")
    if proj:
        return proj
    return pathlib.Path.cwd().name


def resolve_org():
    # env > .squadrc (REQUIRED — the tenant is the /api/orgs/<org>/ path segment).
    org = os.environ.get("SQUAD_ORG", "")
    if org:
        return org
    return _read_keyed_line(pathlib.Path(".squadrc"), "SQUAD_ORG=")


def resolve_base_url():
    # env > ~/.squad/config > deployed default (self-host override only).
    url = os.environ.get("SQUAD_BASE_URL", "")
    if url:
        return url
    url = _read_keyed_line(pathlib.Path.home() / ".squad" / "config", "SQUAD_BASE_URL=")
    return url or DEFAULT_BASE_URL


def resolve_token():
    # OPAQUE credential: resolved by KEY NAME (SQUAD_AUTH_TOKEN=) ONLY — never by
    # value, prefix, length, or format. Token formats rotate over time (e.g.
    # stp_ -> sk_), so inspecting the value would silently break on the next
    # rotation. The value is never echoed or logged.
    tok = os.environ.get("SQUAD_AUTH_TOKEN", "")
    if tok:
        return tok
    return _read_keyed_line(pathlib.Path.home() / ".squad" / "auth", TOKEN_KEY)


def auth_guidance():
    """Actionable mint/refresh guidance for the 401 / no-token-configured case.
    The token is NEVER printed — only the human-relayable fix is."""
    print(
        "ERROR: no valid token for this board (auth failed or unconfigured).",
        file=sys.stderr,
    )
    print(
        "Fix: a human mints or refreshes a Personal Access Token in the board's "
        "web UI (Settings -> Personal Access Tokens), then stores the bare "
        "`SQUAD_AUTH_TOKEN=<token>` line it prints in ~/.squad/auth (mode 600), "
        "or exports SQUAD_AUTH_TOKEN for this shell. The token is never pasted "
        "to the agent.",
        file=sys.stderr,
    )


def build_url(base_url, org, resource_path, project):
    """base_url + /api/orgs/<org> + resource-path, then merge project=<project>
    into the query (preserving any query string already on resource-path)."""
    if not resource_path.startswith("/"):
        resource_path = "/" + resource_path
    full = base_url.rstrip("/") + "/api/orgs/" + org + resource_path
    parts = urllib.parse.urlsplit(full)
    query = urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
    if not any(k == "project" for k, _ in query):
        query.append(("project", project))
    return urllib.parse.urlunsplit(parts._replace(query=urllib.parse.urlencode(query)))


def extract(data, dotted):
    """Traverse decoded JSON by '.'-split keys (integer keys index into lists,
    e.g. activity.0.actor). Returns (found, value)."""
    cur = data
    for key in dotted.split("."):
        if isinstance(cur, dict):
            if key in cur:
                cur = cur[key]
            else:
                return False, None
        elif isinstance(cur, list):
            try:
                idx = int(key)
            except ValueError:
                return False, None
            if -len(cur) <= idx < len(cur):
                cur = cur[idx]
            else:
                return False, None
        else:
            return False, None
    return True, cur


def print_value(value):
    """Print a -q-selected value: scalars raw, containers as compact JSON."""
    if isinstance(value, (dict, list)):
        sys.stdout.write(json.dumps(value))
    elif value is None:
        sys.stdout.write("null")
    elif isinstance(value, bool):
        sys.stdout.write("true" if value else "false")
    else:
        sys.stdout.write(str(value))
    sys.stdout.write("\n")


def handle_success(body_bytes, query_path):
    text = body_bytes.decode("utf-8", errors="replace")
    if query_path:
        # -q requires structured JSON to traverse.
        try:
            parsed = json.loads(text) if text else None
        except json.JSONDecodeError:
            print(
                f"ERROR: response body is not JSON; cannot apply -q '{query_path}'.",
                file=sys.stderr,
            )
            return 4
        if text == "":
            print(
                f"ERROR: response body is empty; cannot apply -q '{query_path}'.",
                file=sys.stderr,
            )
            return 4
        found, value = extract(parsed, query_path)
        if not found:
            print(f"ERROR: path not found in response: {query_path}", file=sys.stderr)
            return 4
        print_value(value)
        return 0
    # No -q: thin pass-through of the board response. Decode only when there is a
    # body so an empty / 204 response prints nothing instead of crashing.
    if text:
        sys.stdout.write(text)
        if not text.endswith("\n"):
            sys.stdout.write("\n")
    return 0


def handle_http_error(err):
    code = err.code
    try:
        body = err.read().decode("utf-8", errors="replace")
    except Exception:
        body = ""
    if code == 401:
        auth_guidance()
        return 3
    if 400 <= code < 500:
        print(f"ERROR: board returned HTTP {code}.", file=sys.stderr)
        if body:
            print(body, file=sys.stderr)
        return 4
    if 500 <= code < 600:
        print(f"ERROR: board server error (HTTP {code}).", file=sys.stderr)
        if body:
            print(body, file=sys.stderr)
        return 5
    print(f"ERROR: unexpected HTTP status {code}.", file=sys.stderr)
    if body:
        print(body, file=sys.stderr)
    return 4


def main():
    parser = argparse.ArgumentParser(
        prog="api.py",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="Zero-dependency board-access helper (auth + transport + JSON + errors).",
        epilog=(
            "exit codes:\n"
            "  0  success\n"
            "  2  usage error (bad args, missing --json @file, SQUAD_ORG unset)\n"
            "  3  auth (HTTP 401 or no token configured)\n"
            "  4  client error (other 4xx, or -q path absent)\n"
            "  5  server error (5xx)\n"
            "  6  network / transport failure\n\n"
            "examples:\n"
            "  api.py GET /task/<id> -q version\n"
            "  api.py GET /board?summary=true\n"
            "  api.py POST /task/<id>/spec --json @body.json\n"
            "  api.py PATCH /task/<id> --json '{\"status\":\"done\"}'\n"
            "\n"
            "auth: the token is resolved internally (env SQUAD_AUTH_TOKEN > "
            "~/.squad/auth); it is never a CLI argument.\n"
        ),
    )
    parser.add_argument(
        "method",
        choices=["GET", "POST", "PATCH", "DELETE"],
        help="HTTP method.",
    )
    parser.add_argument(
        "path",
        help="board path after the org prefix, e.g. /task/<id> or /board.",
    )
    parser.add_argument(
        "--json",
        dest="json_body",
        metavar="<@file|inline|->",
        help="request body: @file, an inline JSON string, or - for stdin "
        "(POST/PATCH/DELETE only).",
    )
    parser.add_argument(
        "-q",
        dest="query_path",
        metavar="<dotted.path>",
        help="print only this dotted path from the response (e.g. version, "
        "activity.0.actor).",
    )
    args = parser.parse_args()

    # --- usage validation (exit 2) ---------------------------------------------
    if args.json_body is not None and args.method == "GET":
        parser.error("--json is not allowed with GET")

    data = None
    if args.json_body is not None:
        if args.json_body == "-":
            raw = sys.stdin.read()
        elif args.json_body.startswith("@"):
            body_path = pathlib.Path(args.json_body[1:])
            if not body_path.is_file():
                print(f"ERROR: --json file not found: {body_path}", file=sys.stderr)
                return 2
            raw = body_path.read_text()
        else:
            raw = args.json_body
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            print(f"ERROR: --json value is not valid JSON: {exc}", file=sys.stderr)
            return 2
        # Re-encode to normalise — kills echo|jq control-char mangling.
        data = json.dumps(parsed).encode("utf-8")

    # --- pre-flight: SQUAD_ORG required (no request issued if unset) -----------
    # Runbook-style error: name the missing value, every place it can be set, the
    # precedence among them, and a copy-pasteable fix — not a bare "export it".
    org = resolve_org()
    if not org:
        print(
            "ERROR: SQUAD_ORG could not be resolved — every board call is "
            "org-scoped (/api/orgs/<org>/...), so no request was sent.",
            file=sys.stderr,
        )
        print(
            "Resolution order (first match wins): env SQUAD_ORG  >  committed "
            ".squadrc (SQUAD_ORG=<slug>).",
            file=sys.stderr,
        )
        print("Set it in ANY of:", file=sys.stderr)
        print(
            "  • committed .squadrc (team-shared default):   "
            "echo 'SQUAD_ORG=<slug>' >> .squadrc",
            file=sys.stderr,
        )
        print(
            "  • this shell only (no tracked-file edit):      "
            "export SQUAD_ORG=<slug>",
            file=sys.stderr,
        )
        print(
            "A committed .squadrc that omits SQUAD_ORG is recoverable "
            "non-interactively via `export SQUAD_ORG=<slug>` — no edit to the "
            "tracked file is required.",
            file=sys.stderr,
        )
        print(
            "The <slug> is the tenant from the mint dialog's `SQUAD_ORG=<slug>` "
            "line; it is NOT derivable from the token (the PAT is user-scoped and "
            "valid across multiple orgs, so it cannot disambiguate the tenant).",
            file=sys.stderr,
        )
        return 2

    # --- pre-flight: token required (same path as 401) -------------------------
    token = resolve_token()
    if not token:
        auth_guidance()
        return 3

    project = resolve_project()
    base_url = resolve_base_url()
    url = build_url(base_url, org, args.path, project)

    req = urllib.request.Request(url, data=data, method=args.method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/json")
    if data is not None:
        req.add_header("Content-Type", "application/json")

    try:
        with urllib.request.urlopen(req) as resp:
            body_bytes = resp.read()
        return handle_success(body_bytes, args.query_path)
    except urllib.error.HTTPError as exc:
        return handle_http_error(exc)
    except urllib.error.URLError as exc:
        print(
            f"ERROR: network/transport failure reaching the board: {exc.reason}",
            file=sys.stderr,
        )
        return 6


if __name__ == "__main__":
    raise SystemExit(main())
