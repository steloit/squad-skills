"""Offline hermetic unit tests for skills/squad/scripts/api.py.

All HTTP I/O uses a loopback http.server stub on 127.0.0.1:0.
No real board, no token file, no LLM, no secrets required.
The CI gate (pytest tests/ -q) runs these without docker or env vars.
"""
import http.server
import json
import pathlib
import socketserver
import subprocess
import sys
import threading
import urllib.parse

import pytest

API_SCRIPT = (
    pathlib.Path(__file__).resolve().parents[1]
    / "skills"
    / "squad"
    / "scripts"
    / "api.py"
)

# ── loopback stub ─────────────────────────────────────────────────────────────


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
    """Context manager: loopback TCPServer on 127.0.0.1:0 in a daemon thread.

    Usage::

        with _StubServer() as srv:
            srv._stub_responses.append({"status": 200, "body": b'{"ok":true}'})
            rc, out, err = _run(["GET", "/x"], base_url=srv.base_url)
            req = srv._stub_requests[0]   # inspect what the helper sent
    """

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


# ── subprocess helper ─────────────────────────────────────────────────────────

# Sentinel used for token-never-leaked assertions: never a real token.
SENTINEL_TOKEN = "SECRET_SENTINEL_abc123xyz987"


def _run(
    args,
    *,
    base_url,
    org="testorg",
    token=SENTINEL_TOKEN,
    home=None,
    cwd=None,
):
    """Run api.py as a subprocess; returns (returncode, stdout, stderr).

    - token=None   → SQUAD_AUTH_TOKEN not set (no-token-configured path)
    - org="" / org=None → SQUAD_ORG not set (triggers exit 2 pre-flight)
    - home=<path>  → HOME override so no ~/.squad/auth is consulted
    """
    import os

    e = dict(os.environ)
    # Strip any real board credentials so the test environment is isolated.
    e.pop("SQUAD_AUTH_TOKEN", None)
    e.pop("SQUAD_ORG", None)
    e.pop("SQUAD_BASE_URL", None)

    e["SQUAD_BASE_URL"] = base_url
    if org:  # empty string or None → leave SQUAD_ORG unset
        e["SQUAD_ORG"] = org
    if token is not None:
        e["SQUAD_AUTH_TOKEN"] = token
    if home is not None:
        e["HOME"] = str(home)

    res = subprocess.run(
        [sys.executable, str(API_SCRIPT)] + list(args),
        capture_output=True,
        text=True,
        env=e,
        cwd=cwd,
        timeout=20,
    )
    return res.returncode, res.stdout, res.stderr


# ── unit: build_url ───────────────────────────────────────────────────────────


def test_build_url_org_in_path(api_mod):
    url = api_mod.build_url("http://board", "acme", "/task/T-1", "proj")
    assert "/api/orgs/acme/task/T-1" in url


def test_build_url_project_merged_into_query(api_mod):
    url = api_mod.build_url("http://board", "org", "/task/T-1", "myproj")
    qs = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    assert qs["project"] == ["myproj"]


def test_build_url_preserves_existing_query_string(api_mod):
    url = api_mod.build_url("http://board", "org", "/board?summary=true", "proj")
    qs = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    assert qs["summary"] == ["true"]
    assert "project" in qs


def test_build_url_fields_passthrough(api_mod):
    """`?fields=version` must survive alongside the merged `project=`."""
    url = api_mod.build_url("http://board", "org", "/task/T-1?fields=version", "proj")
    qs = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    assert qs["fields"] == ["version"]
    assert qs["project"] == ["proj"]


def test_build_url_no_duplicate_project(api_mod):
    """If the path already carries `?project=X`, a second entry must not appear."""
    url = api_mod.build_url("http://board", "org", "/board?project=explicit", "default")
    qs = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    assert len(qs["project"]) == 1
    assert qs["project"] == ["explicit"]


def test_build_url_no_leading_slash_on_path(api_mod):
    """resource-path without a leading `/` still produces a valid URL."""
    url = api_mod.build_url("http://board", "org", "task/T-1", "proj")
    assert "/api/orgs/org/task/T-1" in url


# ── unit: extract (dotted-path selector) ─────────────────────────────────────


def test_extract_integer_scalar(api_mod):
    found, val = api_mod.extract({"version": 42}, "version")
    assert found and val == 42


def test_extract_string_scalar(api_mod):
    found, val = api_mod.extract({"status": "impl"}, "status")
    assert found and val == "impl"


def test_extract_nested_key(api_mod):
    found, val = api_mod.extract({"a": {"b": "hello"}}, "a.b")
    assert found and val == "hello"


def test_extract_list_index(api_mod):
    found, val = api_mod.extract({"items": [10, 20, 30]}, "items.1")
    assert found and val == 20


def test_extract_bool_value(api_mod):
    found, val = api_mod.extract({"active": True}, "active")
    assert found and val is True


def test_extract_null_value(api_mod):
    found, val = api_mod.extract({"x": None}, "x")
    assert found and val is None


def test_extract_absent_key(api_mod):
    found, _ = api_mod.extract({"x": 1}, "y")
    assert not found


def test_extract_absent_nested(api_mod):
    found, _ = api_mod.extract({"a": {}}, "a.b")
    assert not found


def test_extract_index_out_of_range(api_mod):
    found, _ = api_mod.extract({"a": [1]}, "a.99")
    assert not found


def test_extract_non_int_key_on_list(api_mod):
    found, _ = api_mod.extract({"a": [1, 2]}, "a.notanint")
    assert not found


# ── subprocess: bad method + usage → exit 2 ───────────────────────────────────


def test_bad_method_exit_2():
    rc, out, err = _run(["PUT", "/task/T-1"], base_url="http://stub.invalid:1")
    assert rc == 2
    assert out == ""


def test_get_with_json_body_exit_2():
    """--json is not allowed with GET (exit 2 before any network call)."""
    rc, out, err = _run(
        ["GET", "/task/T-1", "--json", '{"x":1}'],
        base_url="http://stub.invalid:1",
    )
    assert rc == 2
    assert out == ""


# ── subprocess: SQUAD_ORG unset → exit 2, zero requests ───────────────────────


def test_squad_org_unset_exit_2_zero_requests(tmp_path):
    """SQUAD_ORG unset → exit 2, actionable stderr, no HTTP request issued."""
    with _StubServer() as srv:
        rc, out, err = _run(
            ["GET", "/task/T-1"],
            base_url=srv.base_url,
            org="",         # falsy → SQUAD_ORG not set in env
            cwd=str(tmp_path),  # no .squadrc → file fallback also returns ""
        )
    # server must not have received any request
    assert len(srv._stub_requests) == 0
    assert rc == 2
    assert out == ""
    assert "SQUAD_ORG" in err


# ── subprocess: --json @missing → exit 2 ─────────────────────────────────────


def test_json_at_missing_file_exit_2(tmp_path):
    missing = tmp_path / "does_not_exist.json"
    rc, out, err = _run(
        ["POST", "/task/T-1", "--json", f"@{missing}"],
        base_url="http://stub.invalid:1",  # won't be reached; check fires first
    )
    assert rc == 2
    assert out == ""
    assert str(missing) in err or "not found" in err.lower()


# ── subprocess: no token configured → exit 3 ─────────────────────────────────


def test_no_token_exit_3(tmp_path):
    """No SQUAD_AUTH_TOKEN in env AND empty HOME (no ~/.squad/auth) → exit 3."""
    rc, out, err = _run(
        ["GET", "/task/T-1"],
        base_url="http://stub.invalid:1",  # won't be reached; token check fires first
        token=None,     # SQUAD_AUTH_TOKEN removed from env
        home=tmp_path,  # HOME override: ~/.squad/auth won't exist
    )
    assert rc == 3
    assert out == ""
    assert "Personal Access Tokens" in err


# ── loopback: HTTP 401 → exit 3 ───────────────────────────────────────────────


def test_401_exit_3():
    with _StubServer() as srv:
        srv._stub_responses.append({"status": 401, "body": b'{"error":"Unauthorized"}'})
        rc, out, err = _run(["GET", "/task/T-1"], base_url=srv.base_url)
    assert rc == 3
    assert out == ""
    assert "Personal Access Tokens" in err


# ── loopback: HTTP 403 → exit 4 (generic 4xx branch) ─────────────────────────


def test_403_exit_4():
    with _StubServer() as srv:
        srv._stub_responses.append({"status": 403, "body": b'{"error":"Forbidden"}'})
        rc, out, err = _run(["GET", "/task/T-1"], base_url=srv.base_url)
    assert rc == 4
    assert out == ""


# ── loopback: HTTP 404 → exit 4 ───────────────────────────────────────────────


def test_404_exit_4():
    with _StubServer() as srv:
        srv._stub_responses.append({"status": 404, "body": b'{"error":"Not found"}'})
        rc, out, err = _run(["GET", "/task/T-1"], base_url=srv.base_url)
    assert rc == 4
    assert out == ""


# ── loopback: HTTP 500 → exit 5 ───────────────────────────────────────────────


def test_500_exit_5():
    with _StubServer() as srv:
        srv._stub_responses.append({"status": 500, "body": b'{"error":"Internal server error"}'})
        rc, out, err = _run(["GET", "/task/T-1"], base_url=srv.base_url)
    assert rc == 5
    assert out == ""


# ── loopback: network / transport failure → exit 6 ────────────────────────────


def test_closed_port_exit_6():
    """Connection to a released port (ECONNREFUSED) → URLError → exit 6."""
    import socket

    # Bind an ephemeral port then immediately release it.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    # Port is now closed; connection should be refused immediately.
    rc, out, err = _run(
        ["GET", "/task/T-1"],
        base_url=f"http://127.0.0.1:{port}",
    )
    assert rc == 6
    assert out == ""


# ── loopback: -q present-scalar ──────────────────────────────────────────────


def test_q_integer_scalar():
    with _StubServer() as srv:
        srv._stub_responses.append(
            {"status": 200, "body": json.dumps({"version": 42}).encode()}
        )
        rc, out, err = _run(["GET", "/task/T-1", "-q", "version"], base_url=srv.base_url)
    assert rc == 0
    assert out.strip() == "42"
    assert err == ""


def test_q_string_scalar():
    with _StubServer() as srv:
        srv._stub_responses.append(
            {"status": 200, "body": json.dumps({"status": "impl"}).encode()}
        )
        rc, out, err = _run(["GET", "/task/T-1", "-q", "status"], base_url=srv.base_url)
    assert rc == 0
    assert out.strip() == "impl"
    assert err == ""


# ── loopback: -q present-container (compact JSON) ─────────────────────────────


def test_q_dict_container():
    with _StubServer() as srv:
        srv._stub_responses.append(
            {"status": 200, "body": json.dumps({"meta": {"a": 1}}).encode()}
        )
        rc, out, err = _run(["GET", "/task/T-1", "-q", "meta"], base_url=srv.base_url)
    assert rc == 0
    assert json.loads(out) == {"a": 1}


def test_q_list_container():
    with _StubServer() as srv:
        srv._stub_responses.append(
            {"status": 200, "body": json.dumps({"items": [1, 2, 3]}).encode()}
        )
        rc, out, err = _run(["GET", "/task/T-1", "-q", "items"], base_url=srv.base_url)
    assert rc == 0
    assert json.loads(out) == [1, 2, 3]


# ── loopback: -q absent path → exit 4 ────────────────────────────────────────


def test_q_absent_path_exit_4():
    with _StubServer() as srv:
        srv._stub_responses.append(
            {"status": 200, "body": json.dumps({"x": 1}).encode()}
        )
        rc, out, err = _run(
            ["GET", "/task/T-1", "-q", "nonexistent_key"], base_url=srv.base_url
        )
    assert rc == 4
    assert out == ""


# ── loopback: URL/query assembly verified at the stub ─────────────────────────


def test_org_in_request_path():
    """Org slug must appear in the HTTP path sent to the board."""
    with _StubServer() as srv:
        srv._stub_responses.append({"status": 200, "body": b'{"ok":true}'})
        _run(["GET", "/task/T-1"], base_url=srv.base_url, org="acmecorp")
        req = srv._stub_requests[0]
    assert "/api/orgs/acmecorp/" in req["path"]


def test_project_in_request_query():
    """project= must appear in the query string forwarded to the board."""
    with _StubServer() as srv:
        srv._stub_responses.append({"status": 200, "body": b'{"ok":true}'})
        _run(["GET", "/task/T-1"], base_url=srv.base_url)
        req = srv._stub_requests[0]
    qs = urllib.parse.parse_qs(urllib.parse.urlparse(req["path"]).query)
    assert "project" in qs


def test_fields_query_forwarded():
    """`?fields=version` on the resource-path is forwarded to the stub unchanged."""
    with _StubServer() as srv:
        srv._stub_responses.append({"status": 200, "body": b'{"version":7}'})
        _run(["GET", "/task/T-1?fields=version"], base_url=srv.base_url)
        req = srv._stub_requests[0]
    qs = urllib.parse.parse_qs(urllib.parse.urlparse(req["path"]).query)
    assert qs.get("fields") == ["version"]


# ── loopback: 204 / empty-body edge ──────────────────────────────────────────


def test_empty_body_no_q_exit_0():
    """Empty 200 body without -q: exit 0, stdout empty (no crash)."""
    with _StubServer() as srv:
        srv._stub_responses.append({"status": 200, "body": b""})
        rc, out, err = _run(["GET", "/task/T-1"], base_url=srv.base_url)
    assert rc == 0
    assert out == ""


def test_empty_body_with_q_exit_4():
    """-q on an empty body → exit 4 (cannot traverse empty JSON)."""
    with _StubServer() as srv:
        srv._stub_responses.append({"status": 200, "body": b""})
        rc, out, err = _run(
            ["GET", "/task/T-1", "-q", "version"], base_url=srv.base_url
        )
    assert rc == 4
    assert out == ""


# ── loopback: success pass-through (no -q) ───────────────────────────────────


def test_success_passthrough():
    body = {"id": "T-1", "version": 5}
    with _StubServer() as srv:
        srv._stub_responses.append({"status": 200, "body": json.dumps(body).encode()})
        rc, out, err = _run(["GET", "/task/T-1"], base_url=srv.base_url)
    assert rc == 0
    assert json.loads(out) == body
    assert err == ""


# ── stdout always empty on non-zero exits ─────────────────────────────────────


@pytest.mark.parametrize(
    "status,expected_rc",
    [
        (401, 3),
        (403, 4),
        (404, 4),
        (500, 5),
    ],
)
def test_stdout_empty_on_http_error(status, expected_rc):
    with _StubServer() as srv:
        srv._stub_responses.append({"status": status, "body": b'{"error":"x"}'})
        rc, out, err = _run(["GET", "/task/T-1"], base_url=srv.base_url)
    assert rc == expected_rc
    assert out == ""


# ── token-never-leaked ────────────────────────────────────────────────────────


def test_sentinel_absent_from_stdout_on_success():
    """Token must not appear in stdout on a successful call."""
    with _StubServer() as srv:
        srv._stub_responses.append({"status": 200, "body": b'{"data":"ok"}'})
        rc, out, err = _run(["GET", "/task/T-1"], base_url=srv.base_url)
    assert SENTINEL_TOKEN not in out
    assert SENTINEL_TOKEN not in err


def test_sentinel_absent_from_stderr_on_401():
    """Token must not appear in stderr even when auth fails."""
    with _StubServer() as srv:
        srv._stub_responses.append({"status": 401, "body": b'{"error":"Unauthorized"}'})
        rc, out, err = _run(["GET", "/task/T-1"], base_url=srv.base_url)
    assert SENTINEL_TOKEN not in out
    assert SENTINEL_TOKEN not in err


def test_sentinel_absent_from_stderr_on_500():
    """Token must not appear in output on server errors."""
    with _StubServer() as srv:
        srv._stub_responses.append({"status": 500, "body": b'{"error":"boom"}'})
        rc, out, err = _run(["GET", "/task/T-1"], base_url=srv.base_url)
    assert SENTINEL_TOKEN not in out
    assert SENTINEL_TOKEN not in err


def test_no_token_cli_arg_in_help():
    """api.py must not expose a `--token` CLI argument (token is never in argv)."""
    import os

    e = dict(os.environ)
    e.pop("SQUAD_AUTH_TOKEN", None)
    e["SQUAD_ORG"] = "testorg"
    e["SQUAD_BASE_URL"] = "http://stub.invalid:1"
    res = subprocess.run(
        [sys.executable, str(API_SCRIPT), "--help"],
        capture_output=True,
        text=True,
        env=e,
        timeout=10,
    )
    combined = res.stdout + res.stderr
    assert "--token" not in combined
