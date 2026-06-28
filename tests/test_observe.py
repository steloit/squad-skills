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
        srv._stub_requests.append(
            {"method": self.command, "path": self.path, "headers": dict(self.headers)}
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
    assert imported <= {"argparse", "json", "os", "pathlib", "subprocess", "sys"}


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
