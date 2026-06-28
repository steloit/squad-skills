#!/usr/bin/env python3
"""observe.py — the read-only, fail-closed observation-consent GATE for Squad skills.

A privacy gate is the canonical deterministic, auditable, low-freedom operation
that belongs in code (not model judgement), so squad-run can call it
unconditionally. This helper decides whether the orchestrator may emit a
`user_steering` observation event — it NEVER captures, grants, or withdraws.

Three subcommands ONLY (the grant/withdraw/disclosure act lives in the WEB app):

  gate     — the SQD-936 seam. Resolve order: local env kill-switches FIRST
             (DO_NOT_TRACK / SQUAD_OBSERVE_DISABLED / CI → OFF, NO network),
             else ONE read of `GET /consent` (via the sibling api.py) → ON iff
             the `behavioral_capture` row is opted_in. FAILS CLOSED: any
             consent-read error → OFF. Emits a `--json` decision + an exit code.
  status   — read-only. Same resolution, but prints the effective on/off, the
             deciding source, the policy_version on record, and a web-app manage
             pointer. Issues only a GET; never mutates.
  dry-run  — prints the ABSTRACTED `user_steering` payload that WOULD be recorded
             to stdout + a `# DRY RUN` banner to stderr. ZERO network/writes;
             works in any consent state (inspection, not capture).

This script NEVER handles the PAT — the sibling api.py owns auth/transport/JSON
and keeps the token opaque. observe.py only shells out to it and reads the
response wire shape (`{ consent: [ { purpose, opted_in, policy_version, … } ] }`).
Zero third-party imports: argparse, json, os, pathlib, subprocess, sys.

Exit codes (gate / status):
  0  observation ON  — opted-in for behavioral_capture, no local override
  1  OFF, clean      — an env kill-switch is set, OR not opted-in (no row / false)
  2  OFF, fail-closed — a consent-read error (api.py non-zero or non-JSON stdout)
`dry-run` always exits 0. All non-zero = OFF (the "0=on, non-zero=off" contract
squad-run branches on without parsing); the 1-vs-2 split is diagnostic only.
"""
import argparse
import json
import os
import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
API = HERE / "api.py"

# The single v1 capture purpose (SQD-937). No row for it ⇒ never granted ⇒ OFF.
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

# The abstracted user_steering payload (SQD-935 shape). Values are ILLUSTRATIVE —
# the real dimensions come from SQD-936's abstraction of an actual correction.
# `comment` is always an abstracted pattern: never raw user text, code, or paths.
DRY_RUN_PAYLOAD = {
    "kind": "user_steering",
    "v": 1,
    "modality": "chat_redirect",
    "valence": "correction",
    "target": "plan_step",
    "severity": "minor",
    "attributability": "explicit",
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
    """The SQD-936 seam: squad-run resolves this ONCE per run and branches on the
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
        "real dimensions come from SQD-936's abstraction of an actual correction.\n"
    )
    sys.stdout.write(json.dumps(DRY_RUN_PAYLOAD) + "\n")
    return 0


def build_parser():
    parser = argparse.ArgumentParser(
        prog="observe.py",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="Read-only, fail-closed observation-consent gate (gate/status/dry-run).",
        epilog=(
            "exit codes (gate / status):\n"
            "  0  observation ON  — opted-in for behavioral_capture, no local override\n"
            "  1  OFF, clean      — an env kill-switch is set, OR not opted-in\n"
            "  2  OFF, fail-closed — a consent-read error (api.py non-zero or non-JSON)\n"
            "dry-run always exits 0.\n\n"
            "All non-zero = OFF (squad-run branches on the code, no parsing). The\n"
            "human opt-in/opt-out act lives in the WEB app — this helper only READS.\n"
            "There is no grant / withdraw / disclosure subcommand here.\n\n"
            "env kill-switches (hard off, beat an active server grant, NO network):\n"
            "  DO_NOT_TRACK · SQUAD_OBSERVE_DISABLED · CI (set & not in {'',0,false})\n\n"
            "examples:\n"
            "  observe.py gate --json      # the SQD-936 seam (resolve once per run)\n"
            "  observe.py status           # effective on/off + source + manage pointer\n"
            "  observe.py dry-run | jq .   # the abstracted payload, written nowhere\n"
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True, metavar="<gate|status|dry-run>")

    p_gate = sub.add_parser("gate", help="resolve the capture decision (exit-code contract).")
    p_gate.add_argument("--json", action="store_true", help="emit the decision object to stdout.")
    p_gate.set_defaults(func=cmd_gate)

    p_status = sub.add_parser("status", help="read-only effective state + source + manage pointer.")
    p_status.add_argument("--json", action="store_true", help="emit the decision object as JSON.")
    p_status.set_defaults(func=cmd_status)

    p_dry = sub.add_parser("dry-run", help="print the would-be payload; write/send nothing.")
    p_dry.add_argument("--json", action="store_true", help="(payload is always JSON) accepted for symmetry.")
    p_dry.set_defaults(func=cmd_dry_run)

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
