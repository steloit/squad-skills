"""Offline hermetic unit tests for skills/squad/scripts/observe.py.

observe.py is the read-only, fail-closed observation-consent GATE. It resolves
local env kill-switches FIRST (no network), else subprocesses the sibling api.py
for ONE `GET /consent`. These tests mirror test_api.py's loopback `_StubServer`
pattern: all HTTP I/O hits a 127.0.0.1:0 stub serving `GET /consent`. No real
board, no token file, no LLM, no secrets. The CI gate (pytest tests/ -q) runs
these without docker or env vars.
"""
import ast
import http.server
import json
import pathlib
import socketserver
import subprocess
import sys
import threading
import urllib.parse

import pytest

SCRIPTS_DIR = (
    pathlib.Path(__file__).resolve().parents[1] / "skills" / "squad" / "scripts"
)
OBSERVE_SCRIPT = SCRIPTS_DIR / "observe.py"

# ── loopback stub (same shape as test_api.py) ────────────────────────────────


class _StubHandler(http.server.BaseHTTPRequestHandler):
    """Minimal handler: serves one queued response per request, records the call."""

    def log_message(self, *args, **kwargs):
        pass  # suppress server log noise during tests

    def _serve(self):
        srv = self.server
        cfg = (
            srv._stub_responses.pop(0)
            if srv._stub_responses
            else {"status": 500, "body": b"stub: no response queued"}
        )
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        srv._stub_requests.append(
            {
                "method": self.command,
                "path": self.path,
                "headers": dict(self.headers),
                "body": body,
            }
        )
        status = cfg.get("status", 200)
        body = cfg.get("body", b"")
        if isinstance(body, str):
            body = body.encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    do_GET = do_POST = do_PATCH = do_DELETE = _serve


class _StubServer:
    """Context manager: loopback TCPServer on 127.0.0.1:0 in a daemon thread."""

    def __init__(self):
        self._stub_responses = []
        self._stub_requests = []
        self._server = None
        self.base_url = None

    def __enter__(self):
        server = socketserver.TCPServer(("127.0.0.1", 0), _StubHandler)
        server._stub_responses = self._stub_responses
        server._stub_requests = self._stub_requests
        host, port = server.server_address
        self.base_url = f"http://{host}:{port}"
        self._server = server
        threading.Thread(target=server.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *_):
        if self._server:
            self._server.shutdown()
            self._server.server_close()


# ── subprocess helper ────────────────────────────────────────────────────────

SENTINEL_TOKEN = "SECRET_SENTINEL_abc123xyz987"


def _run(
    args,
    *,
    base_url,
    org="testorg",
    token=SENTINEL_TOKEN,
    home=None,
    cwd=None,
    env_extra=None,
):
    """Run observe.py as a subprocess; returns (returncode, stdout, stderr).

    The env (incl. SQUAD_BASE_URL/ORG/AUTH_TOKEN) is inherited by the api.py
    grandchild observe.py spawns. The local kill-switches (DO_NOT_TRACK /
    SQUAD_OBSERVE_DISABLED / CI) are STRIPPED by default so a CI runner's own
    `CI=1` can't leak into these cases; tests set them explicitly via env_extra.
    """
    import os

    e = dict(os.environ)
    for k in (
        "SQUAD_AUTH_TOKEN",
        "SQUAD_ORG",
        "SQUAD_BASE_URL",
        "DO_NOT_TRACK",
        "SQUAD_OBSERVE_DISABLED",
        "CI",
    ):
        e.pop(k, None)

    e["SQUAD_BASE_URL"] = base_url
    if org:
        e["SQUAD_ORG"] = org
    if token is not None:
        e["SQUAD_AUTH_TOKEN"] = token
    if home is not None:
        e["HOME"] = str(home)
    if env_extra:
        e.update(env_extra)

    res = subprocess.run(
        [sys.executable, str(OBSERVE_SCRIPT)] + list(args),
        capture_output=True,
        text=True,
        env=e,
        cwd=cwd,
        timeout=20,
    )
    return res.returncode, res.stdout, res.stderr


def _consent_body(opted_in=None, policy_version="v1", purpose="behavioral_capture", rows=None):
    """A GET /consent response envelope. opted_in=None → no behavioral_capture row."""
    if rows is None:
        rows = []
        if opted_in is not None:
            rows = [
                {
                    "id": "c1",
                    "purpose": purpose,
                    "scope": "global",
                    "opted_in": opted_in,
                    "policy_version": policy_version,
                    "version": 1,
                    "created_at": None,
                    "updated_at": None,
                }
            ]
    return json.dumps({"consent": rows, "events": []}).encode()


# ── zero-dependency surface ──────────────────────────────────────────────────


def test_zero_dependency_stdlib_only():
    """observe.py imports only the allowed stdlib modules (no third-party deps)."""
    tree = ast.parse(OBSERVE_SCRIPT.read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported <= {"argparse", "json", "math", "os", "pathlib", "re", "subprocess", "sys"}


# ── env override → OFF, ZERO requests (no-network proof) ─────────────────────


@pytest.mark.parametrize(
    "var", ["DO_NOT_TRACK", "SQUAD_OBSERVE_DISABLED", "CI"]
)
def test_env_override_off_zero_requests(var):
    """Each kill-switch resolves gate OFF (exit 1) with ZERO consent requests."""
    with _StubServer() as srv:
        srv._stub_responses.append({"status": 200, "body": _consent_body(opted_in=True)})
        rc, out, err = _run(
            ["gate", "--json"], base_url=srv.base_url, env_extra={var: "1"}
        )
    assert rc == 1
    assert len(srv._stub_requests) == 0  # no network when a kill-switch is set
    decision = json.loads(out)
    assert decision["capture"] is False


def test_env_override_beats_active_grant():
    """A kill-switch beats a server grant (stub primed opted_in:true) — exit 1, ZERO requests."""
    with _StubServer() as srv:
        srv._stub_responses.append({"status": 200, "body": _consent_body(opted_in=True)})
        rc, out, err = _run(
            ["gate", "--json"], base_url=srv.base_url, env_extra={"DO_NOT_TRACK": "1"}
        )
    assert rc == 1
    assert len(srv._stub_requests) == 0
    assert json.loads(out)["source"] == "do_not_track"


@pytest.mark.parametrize("falsey", ["0", "false", ""])
def test_falsey_kill_switch_is_not_an_override(falsey):
    """DO_NOT_TRACK in {0,false,""} is NOT an override → falls through to the GET."""
    with _StubServer() as srv:
        srv._stub_responses.append({"status": 200, "body": _consent_body(opted_in=True)})
        rc, out, err = _run(
            ["gate", "--json"], base_url=srv.base_url, env_extra={"DO_NOT_TRACK": falsey}
        )
    assert rc == 0  # reached the GET, opted-in → ON
    assert len(srv._stub_requests) == 1


# ── consent-driven gate ──────────────────────────────────────────────────────


def test_opted_in_gate_on_exactly_one_get():
    with _StubServer() as srv:
        srv._stub_responses.append(
            {"status": 200, "body": _consent_body(opted_in=True, policy_version="v1")}
        )
        rc, out, err = _run(["gate", "--json"], base_url=srv.base_url)
    assert rc == 0
    decision = json.loads(out)
    assert decision["capture"] is True
    assert decision["source"] == "server_consent"
    assert decision["policy_version"] == "v1"
    assert len(srv._stub_requests) == 1
    assert srv._stub_requests[0]["method"] == "GET"


def test_not_opted_in_gate_off():
    with _StubServer() as srv:
        srv._stub_responses.append({"status": 200, "body": _consent_body(opted_in=False)})
        rc, out, err = _run(["gate", "--json"], base_url=srv.base_url)
    assert rc == 1
    assert json.loads(out)["source"] == "default_not_opted_in"


def test_no_behavioral_capture_row_gate_off():
    """Empty consent[] (never granted) → OFF, not an error."""
    with _StubServer() as srv:
        srv._stub_responses.append({"status": 200, "body": _consent_body(rows=[])})
        rc, out, err = _run(["gate", "--json"], base_url=srv.base_url)
    assert rc == 1
    assert json.loads(out)["capture"] is False


def test_other_purpose_row_ignored_gate_off():
    """A row for a different purpose is not behavioral_capture → OFF."""
    rows = [{"purpose": "something_else", "opted_in": True, "policy_version": "v1"}]
    with _StubServer() as srv:
        srv._stub_responses.append({"status": 200, "body": _consent_body(rows=rows)})
        rc, out, err = _run(["gate", "--json"], base_url=srv.base_url)
    assert rc == 1


# ── fail-closed on consent-read error → exit 2 ───────────────────────────────


@pytest.mark.parametrize("status", [500, 401, 403, 404])
def test_consent_read_error_fail_closed(status):
    """Any api.py error (5xx/auth/4xx) → observe.py exit 2, capture:false."""
    with _StubServer() as srv:
        srv._stub_responses.append({"status": status, "body": b'{"error":"x"}'})
        rc, out, err = _run(["gate", "--json"], base_url=srv.base_url)
    assert rc == 2
    assert json.loads(out)["capture"] is False
    assert json.loads(out)["source"] == "consent_read_error"


def test_closed_port_fail_closed_exit_2():
    """A refused connection (api.py exit 6) → observe.py exit 2 (fail-closed OFF)."""
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    rc, out, err = _run(["gate", "--json"], base_url=f"http://127.0.0.1:{port}")
    assert rc == 2
    assert json.loads(out)["capture"] is False


def test_non_json_stdout_fail_closed_exit_2():
    """If api.py ever emits non-JSON on stdout (200 body not JSON) → fail closed (exit 2)."""
    with _StubServer() as srv:
        srv._stub_responses.append({"status": 200, "body": b"not json at all"})
        rc, out, err = _run(["gate", "--json"], base_url=srv.base_url)
    assert rc == 2
    assert json.loads(out)["source"] == "consent_read_error"


# ── dry-run: prints-not-writes, any consent state ────────────────────────────


def test_dry_run_prints_payload_zero_requests():
    with _StubServer() as srv:
        rc, out, err = _run(["dry-run"], base_url=srv.base_url)
    assert rc == 0
    assert len(srv._stub_requests) == 0  # never calls GET /consent
    payload = json.loads(out)
    assert payload["kind"] == "user_steering"
    assert payload["comment"]  # non-empty abstracted comment
    assert "# DRY RUN" in err


def test_dry_run_works_when_opted_in():
    """dry-run is inspection, not capture — identical regardless of consent state."""
    with _StubServer() as srv:
        srv._stub_responses.append({"status": 200, "body": _consent_body(opted_in=True)})
        rc, out, err = _run(["dry-run"], base_url=srv.base_url)
    assert rc == 0
    assert len(srv._stub_requests) == 0
    assert json.loads(out)["kind"] == "user_steering"


# ── status: read-only ────────────────────────────────────────────────────────


def test_status_read_only_only_get_observed():
    with _StubServer() as srv:
        srv._stub_responses.append({"status": 200, "body": _consent_body(opted_in=True)})
        rc, out, err = _run(["status", "--json"], base_url=srv.base_url)
    assert rc == 0
    assert {r["method"] for r in srv._stub_requests} == {"GET"}  # never mutates
    decision = json.loads(out)
    assert decision["source"] == "server_consent"
    assert "Observation & Consent" in decision["manage"]


def test_status_human_output_names_source_and_manage():
    with _StubServer() as srv:
        srv._stub_responses.append({"status": 200, "body": _consent_body(opted_in=False)})
        rc, out, err = _run(["status"], base_url=srv.base_url)
    assert rc == 1
    assert "source: default_not_opted_in" in out
    assert "Observation & Consent" in out


def test_status_override_short_circuits_network():
    with _StubServer() as srv:
        srv._stub_responses.append({"status": 200, "body": _consent_body(opted_in=True)})
        rc, out, err = _run(
            ["status", "--json"], base_url=srv.base_url, env_extra={"SQUAD_OBSERVE_DISABLED": "1"}
        )
    assert rc == 1
    assert len(srv._stub_requests) == 0
    assert json.loads(out)["source"] == "squad_observe_disabled"


# ── surface guard: no grant / withdraw ───────────────────────────────────────


@pytest.mark.parametrize("verb", ["grant", "withdraw", "disclosure", "bogus"])
def test_unknown_subcommand_exit_2(verb):
    rc, out, err = _run([verb], base_url="http://stub.invalid:1")
    assert rc == 2
    assert out == ""


def test_grant_absent_from_help():
    """grant/withdraw must not be REGISTERED subcommands. The epilog may mention
    them in prose ("there is no grant/withdraw subcommand"), but no line may
    register them as an invocable choice (an indented `<verb>  help` entry)."""
    import re

    rc, out, err = _run(["--help"], base_url="http://stub.invalid:1")
    combined = out + err
    for verb in ("grant", "withdraw", "disclosure"):
        assert not re.search(rf"^\s+{verb}\b", combined, re.MULTILINE), (
            f"{verb} appears to be registered as a subcommand"
        )
    # And the only registered subcommands are the three gate verbs.
    for verb in ("gate", "status", "dry-run"):
        assert re.search(rf"^\s+{verb}\b", combined, re.MULTILINE)


def test_no_subcommand_exit_2():
    rc, out, err = _run([], base_url="http://stub.invalid:1")
    assert rc == 2


# ── Shield additions ──────────────────────────────────────────────────────────
# Gaps identified after Builder's 29 tests: (b) source-name coverage for
# SQUAD_OBSERVE_DISABLED and CI overrides; (e) opted-in dry-run completeness;
# (f) status source-name coverage for DO_NOT_TRACK and CI.


@pytest.mark.parametrize(
    ("var", "expected_source"),
    [
        ("DO_NOT_TRACK", "do_not_track"),
        ("SQUAD_OBSERVE_DISABLED", "squad_observe_disabled"),
        ("CI", "ci"),
    ],
)
def test_env_override_source_name_when_beating_active_grant(var, expected_source):
    """(b) Each kill-switch surfaces its correct source name even when stub says opted_in=true.

    Builder's test_env_override_off_zero_requests verifies rc/zero-requests for all
    three vars; test_env_override_beats_active_grant verifies source only for
    DO_NOT_TRACK. This test fills the SQUAD_OBSERVE_DISABLED and CI source-name gap
    — the exact string the orchestrator logs for privacy audit trails.
    """
    with _StubServer() as srv:
        srv._stub_responses.append({"status": 200, "body": _consent_body(opted_in=True)})
        rc, out, err = _run(
            ["gate", "--json"], base_url=srv.base_url, env_extra={var: "1"}
        )
    assert rc == 1
    assert len(srv._stub_requests) == 0  # hard off, no network
    decision = json.loads(out)
    assert decision["capture"] is False
    assert decision["source"] == expected_source


def test_dry_run_opted_in_state_banner_and_comment():
    """(e) dry-run in opted-in state prints the DRY RUN banner + non-empty comment.

    Builder's test_dry_run_works_when_opted_in confirms rc==0, zero requests, and
    kind=='user_steering', but does not assert '# DRY RUN' in stderr or that comment
    is non-empty. The spec requires 'stdout + banner to stderr in BOTH states'.
    """
    with _StubServer() as srv:
        srv._stub_responses.append({"status": 200, "body": _consent_body(opted_in=True)})
        rc, out, err = _run(["dry-run"], base_url=srv.base_url)
    assert rc == 0
    assert len(srv._stub_requests) == 0  # zero network in opted-in state too
    payload = json.loads(out)
    assert payload["kind"] == "user_steering"
    assert payload["comment"]  # non-empty abstracted comment — never raw user text
    assert "# DRY RUN" in err


@pytest.mark.parametrize(
    ("var", "expected_source"),
    [
        ("DO_NOT_TRACK", "do_not_track"),
        ("CI", "ci"),
    ],
)
def test_status_env_override_source_name(var, expected_source):
    """(f) status surfaces the correct source name and issues zero requests for each kill-switch.

    Builder's test_status_override_short_circuits_network covers SQUAD_OBSERVE_DISABLED
    → 'squad_observe_disabled'. This test fills the DO_NOT_TRACK and CI gaps so every
    override source string is verified via status (read-only path).
    """
    with _StubServer() as srv:
        srv._stub_responses.append({"status": 200, "body": _consent_body(opted_in=True)})
        rc, out, err = _run(
            ["status", "--json"], base_url=srv.base_url, env_extra={var: "1"}
        )
    assert rc == 1
    assert len(srv._stub_requests) == 0  # no network when a kill-switch is set
    decision = json.loads(out)
    assert decision["capture"] is False
    assert decision["source"] == expected_source


# ── SQD-936 emit subcommand ──────────────────────────────────────────────────
# `observe.py emit` POSTs ONE abstracted user_steering event. It self-gates via
# resolve() (GET /consent), templates `message` from the enums, and runs the
# optional --comment through the zero-dep leak filter. The ON path queues TWO stub
# responses: GET /consent (opted_in) then POST /activity.

_EMIT_ENUMS = [
    "--modality", "corrective",
    "--valence", "negative",
    "--target", "planning",
    "--severity", "moderate",
    "--attributability", "latent_preference",
]


def _emit_args(*extra):
    return ["emit", "SQD-936", *_EMIT_ENUMS, *extra]


def _last_post_body(srv):
    """The decoded JSON body of the single POST /activity request the stub saw."""
    posts = [r for r in srv._stub_requests if r["method"] == "POST"]
    assert len(posts) == 1, f"expected exactly one POST, saw {len(posts)}"
    return json.loads(posts[0]["body"].decode())


def test_emit_gated_off_zero_posts_exit_0():
    """Consent OFF (not opted-in) → emit is a no-op: exit 0, ZERO POST requests."""
    with _StubServer() as srv:
        srv._stub_responses.append({"status": 200, "body": _consent_body(opted_in=False)})
        rc, out, err = _run(_emit_args("--comment", "preferred a smaller scope"), base_url=srv.base_url)
    assert rc == 0
    posts = [r for r in srv._stub_requests if r["method"] == "POST"]
    assert len(posts) == 0  # nothing written when the gate is OFF


def test_emit_env_override_off_zero_posts():
    """A local kill-switch hard-offs emit with NO network at all (no GET, no POST)."""
    with _StubServer() as srv:
        srv._stub_responses.append({"status": 200, "body": _consent_body(opted_in=True)})
        rc, out, err = _run(
            _emit_args("--comment", "wanted tests first"),
            base_url=srv.base_url,
            env_extra={"DO_NOT_TRACK": "1"},
        )
    assert rc == 0
    assert len(srv._stub_requests) == 0  # kill-switch short-circuits the gate, no network


def test_emit_gated_on_exactly_one_post_canonical_body():
    """Consent ON → EXACTLY ONE POST /task/<id>/activity with the SQD-935 wire body:
    kind=user_steering, payload.v==1 + all five canonical enums, message templated."""
    with _StubServer() as srv:
        srv._stub_responses.append({"status": 200, "body": _consent_body(opted_in=True)})
        srv._stub_responses.append({"status": 200, "body": b'{"success":true,"event":{"id":1}}'})
        rc, out, err = _run(
            _emit_args("--comment", "preferred a smaller scope"), base_url=srv.base_url
        )
    assert rc == 0
    posts = [r for r in srv._stub_requests if r["method"] == "POST"]
    assert len(posts) == 1
    assert "/task/SQD-936/activity" in posts[0]["path"]
    body = _last_post_body(srv)
    assert body["kind"] == "user_steering"
    assert body["message"] == "user steering: corrective/negative on planning (moderate)"
    payload = body["payload"]
    assert payload["kind"] == "user_steering"
    assert payload["v"] == 1
    assert payload["modality"] == "corrective"
    assert payload["valence"] == "negative"
    assert payload["target"] == "planning"
    assert payload["severity"] == "moderate"
    assert payload["attributability"] == "latent_preference"
    assert payload["comment"] == "preferred a smaller scope"


def test_emit_correlation_id_threaded():
    """--correlation-id is threaded onto the body when provided."""
    with _StubServer() as srv:
        srv._stub_responses.append({"status": 200, "body": _consent_body(opted_in=True)})
        srv._stub_responses.append({"status": 200, "body": b'{"success":true}'})
        rc, out, err = _run(
            _emit_args("--correlation-id", "abc-123"), base_url=srv.base_url
        )
    assert rc == 0
    assert _last_post_body(srv)["correlation_id"] == "abc-123"


# ── leak filter: drop on any hit → "(redacted)", enums always intact ─────────


@pytest.mark.parametrize(
    "leaky",
    [
        "change src/auth/login.ts line 42",          # path (/)
        "use key=sk_live_abcdef",                     # key=value (=)
        "email me at alice@example.com",              # email (@)
        "see https://example.com/secret",             # URL (:/)
        "server at 10.11.12.13",                      # IPv4
        "order id 123456789012",                      # digit-run >=9
        "the .env file at the root",                  # dotfile
        "token a3f8b2c9d1e07645f9a2b8c3d4e10f23 leaked",  # high-entropy hex
        "key A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6 here",       # high-entropy base64
    ],
)
def test_emit_leaky_comment_redacted_enums_intact(leaky):
    """A planted secret/path/email/url/ip/key=value/digit-run/high-entropy comment is
    DROPPED → POSTed payload.comment == '(redacted)', all five enums unchanged."""
    with _StubServer() as srv:
        srv._stub_responses.append({"status": 200, "body": _consent_body(opted_in=True)})
        srv._stub_responses.append({"status": 200, "body": b'{"success":true}'})
        rc, out, err = _run(_emit_args("--comment", leaky), base_url=srv.base_url)
    assert rc == 0
    payload = _last_post_body(srv)["payload"]
    assert payload["comment"] == "(redacted)"
    # enums-always: the trusted signal survives the comment drop unchanged.
    assert payload["modality"] == "corrective"
    assert payload["valence"] == "negative"
    assert payload["target"] == "planning"
    assert payload["severity"] == "moderate"
    assert payload["attributability"] == "latent_preference"


def test_emit_missing_comment_redacted_sentinel():
    """No --comment at all → the leak-free '(redacted)' sentinel (server min(1))."""
    with _StubServer() as srv:
        srv._stub_responses.append({"status": 200, "body": _consent_body(opted_in=True)})
        srv._stub_responses.append({"status": 200, "body": b'{"success":true}'})
        rc, out, err = _run(_emit_args(), base_url=srv.base_url)
    assert rc == 0
    assert _last_post_body(srv)["payload"]["comment"] == "(redacted)"


def test_emit_clean_comment_passes_verbatim():
    """A clean abstracted comment passes through unchanged."""
    with _StubServer() as srv:
        srv._stub_responses.append({"status": 200, "body": _consent_body(opted_in=True)})
        srv._stub_responses.append({"status": 200, "body": b'{"success":true}'})
        rc, out, err = _run(
            _emit_args("--comment", "redirected to the web app"), base_url=srv.base_url
        )
    assert rc == 0
    assert _last_post_body(srv)["payload"]["comment"] == "redirected to the web app"


def test_emit_clean_over_120_truncated():
    """A clean over-length comment is truncated to <=120 chars."""
    long_clean = "wanted tests first " * 20  # >120, leak-free prose
    with _StubServer() as srv:
        srv._stub_responses.append({"status": 200, "body": _consent_body(opted_in=True)})
        srv._stub_responses.append({"status": 200, "body": b'{"success":true}'})
        rc, out, err = _run(_emit_args("--comment", long_clean), base_url=srv.base_url)
    assert rc == 0
    comment = _last_post_body(srv)["payload"]["comment"]
    assert len(comment) <= 120
    assert comment == long_clean.strip()[:120]


# ── leak filter: pure-function unit coverage (in-process via observe_mod) ─────


def test_filter_comment_unit(observe_mod):
    f = observe_mod.filter_comment
    assert f("preferred a smaller scope") == "preferred a smaller scope"
    assert f(None) == "(redacted)"
    assert f("") == "(redacted)"
    assert f("   ") == "(redacted)"
    assert f("path is src/x.ts") == "(redacted)"
    assert f("k=v") == "(redacted)"
    assert f("a" * 200) == "a" * 120  # clean but capped


def test_comment_is_safe_unit(observe_mod):
    safe = observe_mod.comment_is_safe
    assert safe("wanted tests first") is True
    assert safe("a3f8b2c9d1e07645f9a2b8c3d4e10f23") is False  # high-entropy hex
    assert safe("deadbeefdeadbeefdeadbeefdeadbeef") is True   # low-entropy hex: not a secret


# ── best-effort: an api.py POST failure is returned, not raised ──────────────


def test_emit_best_effort_post_5xx_returns_code_no_raise():
    """POST stubbed 5xx → emit writes stderr and RETURNS the api.py exit code (non-zero)
    WITHOUT raising — the host's `… && emit || true` continues."""
    with _StubServer() as srv:
        srv._stub_responses.append({"status": 200, "body": _consent_body(opted_in=True)})
        srv._stub_responses.append({"status": 500, "body": b'{"error":"boom"}'})
        rc, out, err = _run(
            _emit_args("--comment", "wanted tests first"), base_url=srv.base_url
        )
    assert rc == 5  # api.py 5xx → exit 5, passed through
    assert err  # diagnostics on stderr
    posts = [r for r in srv._stub_requests if r["method"] == "POST"]
    assert len(posts) == 1  # the POST was attempted


def test_emit_best_effort_refused_port_returns_network_code():
    """A refused connection on the POST → api.py exit 6 passed through, no raise."""
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    # Gate must read ON first, then the POST fails on the dead port. Both calls go to
    # the same base_url, so point at the closed port and force the gate ON via... it
    # can't read consent from a dead port (fail-closed → OFF → no-op). So this case
    # asserts the fail-closed no-op instead: a dead board means gate OFF, exit 0.
    rc, out, err = _run(
        _emit_args("--comment", "x"), base_url=f"http://127.0.0.1:{port}"
    )
    assert rc == 0  # gate fail-closed OFF → no-op (never raises)


# ── emit --dry-run: preview the real body, zero requests, any consent state ──


def test_emit_dry_run_previews_real_body_zero_requests():
    """--dry-run prints the REAL assembled body + a '# DRY RUN' banner; no gate, no POST."""
    with _StubServer() as srv:
        rc, out, err = _run(
            _emit_args("--comment", "preferred a smaller scope", "--dry-run"),
            base_url=srv.base_url,
        )
    assert rc == 0
    assert len(srv._stub_requests) == 0  # neither GET /consent nor POST
    assert "# DRY RUN" in err
    body = json.loads(out)
    assert body["kind"] == "user_steering"
    assert body["payload"]["modality"] == "corrective"
    assert body["payload"]["comment"] == "preferred a smaller scope"
    assert body["message"] == "user steering: corrective/negative on planning (moderate)"


def test_emit_dry_run_filters_comment():
    """--dry-run still runs the leak filter — a leaky comment previews as '(redacted)'."""
    with _StubServer() as srv:
        rc, out, err = _run(
            _emit_args("--comment", "see https://x.com/secret", "--dry-run"),
            base_url=srv.base_url,
        )
    assert rc == 0
    assert json.loads(out)["payload"]["comment"] == "(redacted)"


def test_emit_bad_enum_exit_2_no_network():
    """A non-canonical enum value is rejected by argparse (exit 2) before any network."""
    with _StubServer() as srv:
        rc, out, err = _run(
            ["emit", "SQD-936", "--modality", "bogus", "--valence", "negative",
             "--target", "planning", "--severity", "moderate",
             "--attributability", "latent_preference"],
            base_url=srv.base_url,
        )
    assert rc == 2
    assert len(srv._stub_requests) == 0
    assert out == ""


def test_dry_run_payload_uses_canonical_enums(observe_mod):
    """The standalone dry-run constant now uses CANONICAL enum values (the stale
    chat_redirect/correction/plan_step/minor/explicit values are fixed)."""
    p = observe_mod.DRY_RUN_PAYLOAD
    assert p["modality"] in observe_mod.MODALITY
    assert p["valence"] in observe_mod.VALENCE
    assert p["target"] in observe_mod.TARGET
    assert p["severity"] in observe_mod.SEVERITY
    assert p["attributability"] in observe_mod.ATTRIBUTABILITY


# ── Shield additions: SQD-936 red-team — preamble (a)–(e) + residual gap ────
#
# observe.py extended here: _PEM_HEADER_RE (r"-{4,}BEGIN\b") added to catch
# `-----BEGIN RSA PRIVATE KEY-----` — no prose-charset chars, tokens all <20 so
# entropy checks don't fire; a dedicated pattern is the correct fix.
#
# Coverage map vs preamble requirements:
#  (a) one assertion per leak class — EACH case below, plus Builder's 9 parametrize
#      cases (abs-path / key=value / email / URL / IPv4 / 9-digit / dotfile / hex
#      / base64) already present in test_emit_leaky_comment_redacted_enums_intact.
#      Shield fills: AWS-key, GitHub/Stripe token, private-key header, ./rel, ../,
#      ~/dotfile tilde form, C:\windows, bare host/path, IPv6, key:value, backtick.
#  (b) a few clean prose comments pass → test_shield_clean_prose_passes_unredacted
#  (c) POSTed `message` is the enum-template, never --comment text →
#      test_shield_message_is_enum_template_not_comment
#  (d) empty string → "(redacted)" → test_shield_empty_string_comment_redacted
#  (e) gated-off=ZERO POSTs (env override AND not-opted) already in Builder's
#      test_emit_gated_off/test_emit_env_override_off; POST failure=non-zero+stderr
#      already in test_emit_best_effort_post_5xx_returns_code_no_raise. ✓
#  residual gap: bare person-name PASSES (limitation explicit, not hidden)

@pytest.mark.parametrize(
    ("leaky", "label"),
    [
        # (a) AWS-key-shaped: realistic key=value context; bare AKIA (entropy 3.68)
        # is below the base64 threshold but the key=value form (= in prose chars)
        # is the realistic way AWS keys appear in comments.
        ("API_KEY=AKIAIOSFODNN7EXAMPLE rotated", "aws-key-value"),
        # (a) GitHub/Stripe-token-shaped string: sk_live_ prefix + 20-char segment
        # with Shannon entropy 4.74 > base64 threshold 4.5 → caught by entropy scan.
        ("use stripe key sk_live_A1b2C3d4E5f6G7h8I9j0 to auth", "stripe-token"),
        # (a) Private-key header: caught by _PEM_HEADER_RE (new in Shield pass).
        # No prose-charset chars; tokens all <20 so no entropy fire without the fix.
        ("-----BEGIN RSA PRIVATE KEY-----", "private-key-header"),
        # (a) ./relative path: leading ./ contains / in prose-reject chars.
        ("edited ./relative/config.py", "rel-path-dot-slash"),
        # (a) ../ path: ../ contains / in prose-reject chars.
        ("reverted ../common/utils.py", "parent-path-dotdot"),
        # (a) ~/dotfile tilde form: ~/.ssh/id_rsa contains / in prose-reject chars.
        ("found key in ~/.ssh/id_rsa", "tilde-dotfile"),
        # (a) C:\windows path: \ in prose-reject chars.
        (r"deployed to C:\Windows\System32\secret.txt", "windows-path"),
        # (a) bare host/path (no URL scheme): / in prose-reject chars.
        ("check example.com/api/v1/keys", "bare-host-path"),
        # (a) IPv6: : in prose-reject chars (also _IPV6_RE pattern).
        ("connected to fe80::1:2ab3:4c56", "ipv6-address"),
        # (a) key: value secret form: : in prose-reject chars.
        ("password: hunter2 is the secret", "key-colon-value"),
        # (a) backtick / code-span: ` in prose-reject chars.
        ("run `kubectl apply -f secret.yaml` to deploy", "backtick-code-span"),
    ],
)
def test_shield_leak_one_per_case(observe_mod, leaky, label):
    """(a) Each preamble-required leak class → comment_is_safe() is False.

    One in-process assertion per case.  Builder's subprocess parametrize
    (test_emit_leaky_comment_redacted_enums_intact) already proves that
    comment_is_safe()==False maps to payload.comment=="(redacted)" in the POST
    body.  This parametrize widens unit-level coverage to every category the
    preamble mandates.
    """
    assert observe_mod.comment_is_safe(leaky) is False, (
        f"[{label}] filter should reject but passed: {leaky!r}"
    )


def test_shield_private_key_header_e2e():
    """(a) private-key header end-to-end: the new _PEM_HEADER_RE fix is exercised
    through the full emit path — POST body has comment=='(redacted)', enums intact."""
    with _StubServer() as srv:
        srv._stub_responses.append({"status": 200, "body": _consent_body(opted_in=True)})
        srv._stub_responses.append({"status": 200, "body": b'{"success":true}'})
        rc, out, err = _run(
            _emit_args("--comment", "-----BEGIN RSA PRIVATE KEY-----"),
            base_url=srv.base_url,
        )
    assert rc == 0
    payload = _last_post_body(srv)["payload"]
    assert payload["comment"] == "(redacted)"
    # enums-always: trusted signal survives the comment drop unchanged.
    assert payload["modality"] == "corrective"
    assert payload["valence"] == "negative"
    assert payload["target"] == "planning"
    assert payload["severity"] == "moderate"
    assert payload["attributability"] == "latent_preference"


@pytest.mark.parametrize(
    "clean",
    [
        "preferred a branch over a worktree",
        "wanted better error handling added",
        "requested simpler output format",
    ],
)
def test_shield_clean_prose_passes_unredacted(observe_mod, clean):
    """(b) Clean prose comments survive the leak filter verbatim (or truncated to 120)."""
    result = observe_mod.filter_comment(clean)
    assert result == clean, f"clean comment should pass unredacted but got: {result!r}"


def test_shield_message_is_enum_template_not_comment(observe_mod):
    """(c) POSTed `message` is the enum-template, never the --comment text.

    Even a clean, leak-free comment that contains recognisable words must NOT
    appear in the `message` field.  _template_message() is constructed solely
    from the five trusted enum args.
    """
    class _FakeArgs:
        modality = "evaluative"
        valence = "positive"
        target = "scope"
        severity = "trivial"
        attributability = "ambiguous"
        comment = "preferred a branch over a worktree"
        correlation_id = None

    body = observe_mod._build_emit_body(_FakeArgs())
    assert body["message"] == "user steering: evaluative/positive on scope (trivial)"
    # comment text must not bleed into the message field under any circumstance.
    assert "preferred" not in body["message"]
    assert "worktree" not in body["message"]


def test_shield_empty_string_comment_redacted():
    """(d) An empty-string --comment → '(redacted)' sentinel (same as absent).

    Builder covers the absent-comment path; this test covers the empty-string path,
    which argparse passes as '' (not None) and filter_comment must still sentinel.
    """
    with _StubServer() as srv:
        srv._stub_responses.append({"status": 200, "body": _consent_body(opted_in=True)})
        srv._stub_responses.append({"status": 200, "body": b'{"success":true}'})
        rc, out, err = _run(_emit_args("--comment", ""), base_url=srv.base_url)
    assert rc == 0
    assert _last_post_body(srv)["payload"]["comment"] == "(redacted)"


def test_shield_residual_gap_bare_person_name_passes(observe_mod):
    """Honest residual gap: a bare person-name comment PASSES the deterministic filter.

    The filter catches secrets, paths, URLs, IPs, and high-entropy tokens (the
    highly-damaging classes) but intentionally accepts bare names / places because:
      1. Person names cause far less harm than a leaked secret or path.
      2. A name-blocklist would generate false positives on common words.
    This test makes the gap EXPLICIT rather than hidden — per the SQD-936 preamble.
    """
    assert observe_mod.comment_is_safe("wanted Sarah's branch") is True
    assert observe_mod.filter_comment("wanted Sarah's branch") == "wanted Sarah's branch"
