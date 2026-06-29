#!/usr/bin/env python3
"""observe.py — the read-only, fail-closed observation-consent GATE for Squad skills.

A privacy gate is the canonical deterministic, auditable, low-freedom operation
that belongs in code (not model judgement), so squad-run can call it
unconditionally. This helper decides whether the orchestrator may emit a
`user_steering` observation event — it NEVER captures, grants, or withdraws.

Four subcommands ONLY (the grant/withdraw/disclosure act lives in the WEB app):

  gate     — the observation gate-seam. Resolve order: local env kill-switches FIRST
             (DO_NOT_TRACK / SQUAD_OBSERVE_DISABLED / CI → OFF, NO network),
             else ONE read of `GET /consent` (via the sibling api.py) → ON iff
             the `behavioral_capture` row is opted_in. FAILS CLOSED: any
             consent-read error → OFF. Emits a `--json` decision + an exit code.
  status   — read-only. Same resolution, but prints the effective on/off, the
             deciding source, the policy_version on record, and a web-app manage
             pointer. Issues only a GET; never mutates.
  dry-run  — prints an ILLUSTRATIVE `user_steering` payload that WOULD be recorded
             to stdout + a `# DRY RUN` banner to stderr. ZERO network/writes;
             works in any consent state (inspection, not capture).
  emit     — the Tier-1 observation capture: POST ONE abstracted `user_steering`
             event for a human correction. The five enums come from the calling
             skill's trusted gate context (argparse `choices=` validated); the
             optional `--comment` is the only free-text surface and is passed
             through a deterministic, zero-dep reject-on-detect leak filter — any
             hit → the constant `"(redacted)"` sentinel (the enums always emit).
             SELF-GATES via resolve() (no-op exit 0 if OFF) and is BEST-EFFORT:
             an api.py POST failure is written to stderr and RETURNED (never
             raised), so the host skill's `… && emit || true` always continues.
             `--dry-run` previews the assembled body (no gate, no POST).

This script NEVER handles the PAT — the sibling api.py owns auth/transport/JSON
and keeps the token opaque. observe.py only shells out to it and reads the
response wire shape (`{ consent: [ { purpose, opted_in, policy_version, … } ] }`).
Zero third-party imports: argparse, json, math, os, pathlib, re, subprocess, sys.

Exit codes (gate / status):
  0  observation ON  — opted-in for behavioral_capture, no local override
  1  OFF, clean      — an env kill-switch is set, OR not opted-in (no row / false)
  2  OFF, fail-closed — a consent-read error (api.py non-zero or non-JSON stdout)
`dry-run` always exits 0. All non-zero = OFF (the "0=on, non-zero=off" contract
squad-run branches on without parsing); the 1-vs-2 split is diagnostic only.

Exit codes (emit):
  0  emitted OK, OR gated-off no-op (consent OFF), OR --dry-run preview
  2  usage error (bad/absent enum — argparse rejects before any network)
  3/4/5/6  the api.py POST code passed through (auth / client incl. server-403 /
           server / network) — advisory only; emit is best-effort, never raises.
"""
import argparse
import json
import math
import os
import pathlib
import re
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
API = HERE / "api.py"

# The single v1 capture purpose (the consent gate). No row for it ⇒ never granted ⇒ OFF.
PURPOSE = "behavioral_capture"
MANAGE_POINTER = "Squad web app → Settings → Observation & Consent"

# Local kill-switches, in precedence order. The first set-and-truthy one wins and
# short-circuits the network — the human's local override beats an active grant.
_OVERRIDE_ENV = [
    ("DO_NOT_TRACK", "do_not_track"),
    ("SQUAD_OBSERVE_DISABLED", "squad_observe_disabled"),
    ("CI", "ci"),
]

# The donottrack.sh convention: set, and not one of these → truthy (an override).
_FALSEY = {"", "0", "false"}

# Canonical user_steering enum vocabularies. These MIRROR the single source of
# truth (the server-side activity event types); they are duplicated here only
# to bind argparse `choices=` for client-side validation before the wire POST —
# the server re-validates. Keep in sync with that file; never invent values.
MODALITY = ("evaluative", "corrective", "demonstrative", "other")
VALENCE = ("positive", "negative", "na")
TARGET = ("git_strategy", "planning", "scope", "verification", "pipeline_flow", "tooling", "other")
SEVERITY = ("trivial", "moderate", "major", "other")
ATTRIBUTABILITY = ("latent_preference", "violated_constraint", "ambiguous")

# Platform contract: userSteeringPayloadSchema.comment is z.string().min(1).max(120).
# A dropped / empty comment can't be omitted (min(1)) — substitute this leak-free
# sentinel so "enums-always" stays server-valid.
STEERING_COMMENT_MAX_LEN = 120
REDACTED_SENTINEL = "(redacted)"

# The abstracted user_steering payload (the activity event shape). Values are ILLUSTRATIVE
# but DRAWN FROM THE CANONICAL VOCAB above — the real dimensions come from
# the `emit` observation abstraction of an actual correction. `comment` is always an
# abstracted pattern: never raw user text, code, or paths.
DRY_RUN_PAYLOAD = {
    "kind": "user_steering",
    "v": 1,
    "modality": "corrective",
    "valence": "negative",
    "target": "planning",
    "severity": "moderate",
    "attributability": "latent_preference",
    "comment": "<abstracted pattern — never raw user text/code/paths>",
}


def _truthy(val):
    """A kill-switch env var is an override iff set and not in {"", "0", "false"}."""
    return val is not None and val.strip().lower() not in _FALSEY


def env_override():
    """Return the override source name (do_not_track / squad_observe_disabled / ci)
    if any local kill-switch is set-and-truthy, else None. NO network is issued
    when this returns a name."""
    for name, source in _OVERRIDE_ENV:
        if _truthy(os.environ.get(name)):
            return source
    return None


def read_consent():
    """Subprocess `api.py GET /consent` (api.py owns auth/transport/JSON; the PAT
    stays opaque). Returns (ok, opted_in, policy_version, error).

    FAILS CLOSED: api.py non-zero (auth/4xx/5xx/network) OR non-JSON stdout →
    ok=False. The child's stderr is passed through so the api.py guidance shows.
    """
    proc = subprocess.run(
        [sys.executable, str(API), "GET", "/consent"],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        if proc.stderr:
            sys.stderr.write(proc.stderr)
        return False, False, None, f"api.py GET /consent failed (exit {proc.returncode})"
    try:
        data = json.loads(proc.stdout)
    except (json.JSONDecodeError, ValueError) as exc:
        return False, False, None, f"consent response was not valid JSON: {exc}"
    # Read ONLY purpose / opted_in / policy_version; ignore every other field.
    for row in data.get("consent") or []:
        if isinstance(row, dict) and row.get("purpose") == PURPOSE:
            return True, bool(row.get("opted_in")), row.get("policy_version"), None
    # No behavioral_capture row ⇒ never granted ⇒ OFF (not an error).
    return True, False, None, None


def resolve():
    """Resolve the gate decision. Returns (decision_dict, exit_code).

    Order: env override (no network) → GET /consent → fail-closed on error.
    """
    override = env_override()
    if override is not None:
        return _decision(False, override, None), 1
    ok, opted_in, policy_version, error = read_consent()
    if not ok:
        return _decision(False, "consent_read_error", None, error=error), 2
    if opted_in:
        return _decision(True, "server_consent", policy_version), 0
    return _decision(False, "default_not_opted_in", policy_version), 1


def _decision(capture, source, policy_version, error=None):
    d = {
        "capture": capture,
        "source": source,
        "purpose": PURPOSE,
        "policy_version": policy_version,
        "manage": MANAGE_POINTER,
    }
    if error is not None:
        d["error"] = error
    return d


def cmd_gate(args):
    """The observation gate-seam: squad-run resolves this ONCE per run and branches on the
    exit code (rc==0 ⇒ emit, else skip) — no stdout parsing required."""
    decision, code = resolve()
    if args.json:
        sys.stdout.write(json.dumps(decision) + "\n")
    return code


def cmd_status(args):
    """Read-only effective state + source + manage pointer. Mirrors gate's exit codes."""
    decision, code = resolve()
    if args.json:
        sys.stdout.write(json.dumps(decision) + "\n")
    else:
        state = "on" if decision["capture"] else "off"
        sys.stdout.write(f"observation: {state}\n")
        sys.stdout.write(f"source: {decision['source']}\n")
        sys.stdout.write(f"purpose: {decision['purpose']}\n")
        sys.stdout.write(f"policy_version: {decision['policy_version']}\n")
        sys.stdout.write(f"manage: {decision['manage']}\n")
        if "error" in decision:
            sys.stdout.write(f"error: {decision['error']}\n")
    return code


def cmd_dry_run(args):
    """Print the abstracted user_steering payload that WOULD be recorded — to
    STDOUT (pipeable to jq) — and a banner to STDERR. ZERO network/writes;
    works in any consent state (never calls GET /consent)."""
    sys.stderr.write(
        "# DRY RUN — nothing written or sent. The values below are illustrative; "
        "real dimensions come from the observation abstraction of an actual correction.\n"
    )
    sys.stdout.write(json.dumps(DRY_RUN_PAYLOAD) + "\n")
    return 0


# ── the zero-dep reject-on-detect leak filter (re + math only) ───────────────
#
# The optional --comment is the ONLY free-text surface. It is meant to be an
# ALREADY-abstracted pattern ("preferred a smaller scope"), but we never trust
# that — a deterministic reject-on-detect filter drops anything that looks like a
# path, URL, email, key=value, IP, long digit run, or a high-entropy secret, so a
# raw leak can never reach the wire. On ANY hit the comment becomes the
# "(redacted)" sentinel; the enums (the trusted signal) always emit. Zero
# third-party deps — stdlib `re` + `math` only.

# Any of these chars ⇒ not prose: catches paths (/ \), URLs (: /), emails (@),
# key=value (=), code/shell ({ } ( ) ; $ ` ") in one cheap scan.
_PROSE_REJECT_CHARS = set("/\\@:={}();$`\"")

# Tokens that the charset scan can't catch on its own.
_EMAIL_RE = re.compile(r"[^\s@]+@[^\s@]+\.[^\s@]+")
_URL_RE = re.compile(r"https?://", re.IGNORECASE)
_IPV4_RE = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")
_IPV6_RE = re.compile(r"\b(?:[0-9A-Fa-f]{0,4}:){2,}[0-9A-Fa-f]{0,4}\b")
_DOTFILE_RE = re.compile(r"(?:^|\s)~?/?\.[A-Za-z0-9_]+")  # .env, ~/.ssh, ./node_modules
_KEYVALUE_RE = re.compile(r"\b[\w.-]+=[^\s]+")
_DIGIT_RUN_RE = re.compile(r"\d{9,}")
# PEM / private-key headers: `-----BEGIN RSA PRIVATE KEY-----` etc. contain no
# chars caught by the prose-charset scan and no token ≥20 chars, so entropy
# checks don't fire. A dedicated pattern catches all -----BEGIN … ----- forms.
_PEM_HEADER_RE = re.compile(r"-{4,}BEGIN\b", re.IGNORECASE)

# Entropy charsets (detect-secrets defaults). hex is the stricter subset → test it
# first at the lower threshold.
_HEX_RE = re.compile(r"^[0-9A-Fa-f]+$")
_BASE64_RE = re.compile(r"^[A-Za-z0-9+/=_-]+$")
_ENTROPY_MIN_TOKEN = 20
_HEX_ENTROPY_LIMIT = 3.0
_BASE64_ENTROPY_LIMIT = 4.5


def _shannon_entropy(s):
    """Shannon entropy (bits/char) of a string — stdlib math only."""
    if not s:
        return 0.0
    n = len(s)
    counts = {}
    for ch in s:
        counts[ch] = counts.get(ch, 0) + 1
    return -sum((c / n) * math.log2(c / n) for c in counts.values())


def comment_is_safe(text):
    """True iff `text` is free of every leak signal (prose-charset, the regex
    classes, and a high-entropy secret token). Reject-on-detect — any hit → False."""
    if _PROSE_REJECT_CHARS.intersection(text):
        return False
    for rx in (_EMAIL_RE, _URL_RE, _IPV4_RE, _IPV6_RE, _DOTFILE_RE, _KEYVALUE_RE, _DIGIT_RUN_RE,
               _PEM_HEADER_RE):
        if rx.search(text):
            return False
    for token in text.split():
        if len(token) < _ENTROPY_MIN_TOKEN:
            continue
        if _HEX_RE.match(token) and _shannon_entropy(token) >= _HEX_ENTROPY_LIMIT:
            return False
        if _BASE64_RE.match(token) and _shannon_entropy(token) >= _BASE64_ENTROPY_LIMIT:
            return False
    return True


def filter_comment(text):
    """Reduce the raw --comment to a wire-safe value. Absent/empty OR any leak
    hit → the "(redacted)" sentinel (enums-always, server-valid min(1)). A clean
    comment passes through, truncated to STEERING_COMMENT_MAX_LEN."""
    if text is None:
        return REDACTED_SENTINEL
    text = text.strip()
    if not text:
        return REDACTED_SENTINEL
    if not comment_is_safe(text):
        return REDACTED_SENTINEL
    return text[:STEERING_COMMENT_MAX_LEN]


# ── emit: POST one abstracted user_steering event (consent-gated, best-effort) ─


def _template_message(args):
    """Deterministic message FROM THE ENUMS — never raw user text. `message` is a
    second uncapped free-text surface (tasks.ts `z.string().min(1)`, no max), so we
    template it so it is leak-free by construction, not by filtering."""
    return f"user steering: {args.modality}/{args.valence} on {args.target} ({args.severity})"


def _build_emit_body(args):
    """Assemble the activity wire body from trusted enums + the filtered comment."""
    body = {
        "kind": "user_steering",
        "message": _template_message(args),
        "payload": {
            "kind": "user_steering",
            "v": 1,
            "modality": args.modality,
            "valence": args.valence,
            "target": args.target,
            "severity": args.severity,
            "attributability": args.attributability,
            "comment": filter_comment(args.comment),
        },
    }
    if args.correlation_id:
        body["correlation_id"] = args.correlation_id
    return body


def cmd_emit(args):
    """POST one abstracted user_steering event. --dry-run previews the real body
    (no gate, no POST). Else self-gate via resolve() (no-op exit 0 when OFF), then
    subprocess api.py POST with the body on STDIN (nothing lands in argv).
    Best-effort: an api.py non-zero is logged + RETURNED, never raised."""
    body = _build_emit_body(args)
    if args.dry_run:
        sys.stderr.write(
            "# DRY RUN — nothing written or sent. The body below is the REAL "
            "assembled user_steering payload (enums + filtered comment).\n"
        )
        sys.stdout.write(json.dumps(body) + "\n")
        return 0
    decision, _code = resolve()
    if not decision["capture"]:
        # Gated OFF (env override / not opted-in / fail-closed) → write nothing.
        return 0
    path = f"/task/{args.task_id}/activity"
    proc = subprocess.run(
        [sys.executable, str(API), "POST", path, "--json", "-"],
        input=json.dumps(body),
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        if proc.stderr:
            sys.stderr.write(proc.stderr)
        sys.stderr.write(
            f"observe.py emit: api.py POST {path} failed (exit {proc.returncode}); "
            "best-effort — the host run continues.\n"
        )
        return proc.returncode
    return 0


def build_parser():
    parser = argparse.ArgumentParser(
        prog="observe.py",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="Observation-consent gate + user_steering emit (gate/status/dry-run/emit).",
        epilog=(
            "exit codes (gate / status):\n"
            "  0  observation ON  — opted-in for behavioral_capture, no local override\n"
            "  1  OFF, clean      — an env kill-switch is set, OR not opted-in\n"
            "  2  OFF, fail-closed — a consent-read error (api.py non-zero or non-JSON)\n"
            "dry-run always exits 0.\n\n"
            "exit codes (emit):\n"
            "  0  emitted OK, OR gated-off no-op, OR --dry-run preview\n"
            "  2  usage (bad/absent enum — argparse rejects before any network)\n"
            "  3/4/5/6  the api.py POST code (auth / client incl. server-403 / server /\n"
            "           network) — advisory only; emit is best-effort and never raises.\n\n"
            "All non-zero = OFF (squad-run branches on the gate code, no parsing). The\n"
            "human opt-in/opt-out act lives in the WEB app — this helper only READS\n"
            "consent. There is no grant / withdraw / disclosure subcommand here.\n\n"
            "env kill-switches (hard off, beat an active server grant, NO network):\n"
            "  DO_NOT_TRACK · SQUAD_OBSERVE_DISABLED · CI (set & not in {'',0,false})\n\n"
            "examples:\n"
            "  observe.py gate --json      # the observation gate-seam (resolve once per run)\n"
            "  observe.py status           # effective on/off + source + manage pointer\n"
            "  observe.py dry-run | jq .   # an illustrative payload, written nowhere\n"
            "  observe.py emit ABC-1 --modality corrective --valence negative \\\n"
            "    --target planning --severity moderate --attributability latent_preference \\\n"
            "    --comment 'preferred a smaller scope'   # consent-gated, best-effort POST\n"
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True, metavar="<gate|status|dry-run|emit>")

    p_gate = sub.add_parser("gate", help="resolve the capture decision (exit-code contract).")
    p_gate.add_argument("--json", action="store_true", help="emit the decision object to stdout.")
    p_gate.set_defaults(func=cmd_gate)

    p_status = sub.add_parser("status", help="read-only effective state + source + manage pointer.")
    p_status.add_argument("--json", action="store_true", help="emit the decision object as JSON.")
    p_status.set_defaults(func=cmd_status)

    p_dry = sub.add_parser("dry-run", help="print an illustrative payload; write/send nothing.")
    p_dry.add_argument("--json", action="store_true", help="(payload is always JSON) accepted for symmetry.")
    p_dry.set_defaults(func=cmd_dry_run)

    p_emit = sub.add_parser(
        "emit",
        help="POST one abstracted user_steering event (consent-gated, leak-filtered, best-effort).",
    )
    p_emit.add_argument("task_id", help="the task id the steering event attaches to (e.g. ABC-12).")
    p_emit.add_argument("--modality", required=True, choices=MODALITY, help="the steering modality.")
    p_emit.add_argument("--valence", required=True, choices=VALENCE, help="the steering valence.")
    p_emit.add_argument("--target", required=True, choices=TARGET, help="what the steering was about.")
    p_emit.add_argument("--severity", required=True, choices=SEVERITY, help="the steering severity.")
    p_emit.add_argument(
        "--attributability", required=True, choices=ATTRIBUTABILITY, help="why the steering happened."
    )
    p_emit.add_argument(
        "--comment",
        default=None,
        help="OPTIONAL abstracted pattern (NOT raw text); leak-filtered → '(redacted)' on any hit.",
    )
    p_emit.add_argument(
        "--correlation-id",
        dest="correlation_id",
        default=None,
        help="optional uuid grouping token (the orchestrator's per-correction id).",
    )
    p_emit.add_argument(
        "--dry-run",
        action="store_true",
        help="preview the assembled body (no gate, no POST); exit 0.",
    )
    p_emit.set_defaults(func=cmd_emit)

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
