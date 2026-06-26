# api.py — board-access helper

The single zero-dependency helper every Squad skill calls instead of
hand-assembling `curl` + auth + JSON. It owns auth (opaque token), transport,
JSON encode/decode, and a structured error/exit-code contract. python3
stdlib-only (no `requests`/`httpx`) — installs anywhere python3 runs.

## Invocation

~~~
api.py <METHOD> <resource-path> [--json <@file|inline|->] [-q <dotted.path>]
~~~

- **`METHOD`** — `GET` | `POST` | `PATCH` | `DELETE` (any other value is a usage
  error, exit 2).
- **`resource-path`** — the board path **after** the org prefix, e.g.
  `/task/<id>`, `/task/<id>/spec`, `/board`, `/projects`. `api.py` prepends
  `/api/orgs/<org>` and merges `project=<project>` into the query. Any query
  string already on the path (`?fields=…`, `?summary=true`, `?limit=…`,
  `?before=…`) is preserved.
- **`--json`** — request body for `POST`/`PATCH`/`DELETE`: `@file` (read a file),
  an inline JSON string, or `-` (read stdin). The body is validated and
  re-encoded as JSON, and `Content-Type: application/json` is set once. Not
  allowed with `GET` (exit 2). A missing `@file` is a usage error (exit 2).
- **`-q <dotted.path>`** — print only the selected value from the JSON response.
  Dots split keys; integer segments index lists (e.g. `activity.0.actor`).
  Scalars print raw; containers print as compact JSON. An absent path is exit 4.

## I/O contract

Machine-readable result to **stdout**, diagnostics to **stderr**, never mixed.
On any non-zero exit, **stdout stays empty**. With `-q`, only the selected
scalar/value is printed.

## Auth (owned internally, opaque)

The Personal Access Token is resolved by the `SQUAD_AUTH_TOKEN=` key name only —
env `SQUAD_AUTH_TOKEN` first, then the bare line in `~/.squad/auth`. It is treated
as an opaque credential (never matched/validated by value, prefix, length, or
format — formats rotate), is never echoed/logged, and is **never** a CLI argument
(so it can't leak into argv / `ps`). `SQUAD_ORG` is required (env > `.squadrc`);
an unset org is a fail-fast pre-flight error (exit 2, no request issued).
`SQUAD_BASE_URL` overrides the deployed default (env > `~/.squad/config`).

## Exit codes

| Code | Meaning |
|------|---------|
| 0 | success |
| 2 | usage error — bad args, missing `--json @file`, or `SQUAD_ORG` unset |
| 3 | auth — HTTP 401 or no token configured (stderr carries mint/refresh guidance: Settings → Personal Access Tokens) |
| 4 | client error — other 4xx (board error body surfaced), or `-q` path absent |
| 5 | server error — 5xx |
| 6 | network / transport failure |

So `if api.py …; then …; fi` and `set -e` work.

## Examples

~~~bash
# read a task's version (scalar to stdout)
api.py GET /task/<id> -q version

# board summary (query string preserved, project= merged in)
api.py GET /board?summary=true

# submit a spec from a file
api.py POST /task/<id>/spec --json @body.json

# patch a field inline
api.py PATCH /task/<id> --json '{"status":"done"}'

# body from stdin
echo '{"text":"hi"}' | api.py POST /task/<id>/comment --json -
~~~

The full contract also lives in `api.py --help`. A live read-only smoke
(`api_smoke.py`, needs a real PAT — not in CI) proves auth + transport + decode +
`-q` against the deployed board without mutating it.
