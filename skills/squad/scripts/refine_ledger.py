#!/usr/bin/env python3
"""refine_ledger.py — the deterministic stop-gate AUTHORITY for the squad-refine
gap-ledger interview loop.

The interview's stop decision is a deterministic, auditable, low-freedom
operation, so it lives in code — NOT model judgement (Anthropic "prefer scripts
for deterministic operations"). The DIVISION OF LABOUR is the whole point:

  - the LLM GENERATES the semantic content (which gaps exist, what each
    probe-scan over an answer turns up) — high-freedom judgement;
  - this SCRIPT COUNTS + DECIDES (OPEN count, coverage + diminishing-returns +
    hard-cap checks → a CONTINUE/STOP verdict + the residual-open list) —
    low-freedom bookkeeping.

SKILL.md re-emits the FULL ledger every round, pipes it here, and OBEYS the exit
code. The model never self-adjudicates the stop ("looks done" is a known gameable
failure), so the loop cannot collapse to a single round while any answer leaves a
concept underspecified, and cannot run forever (the hard cap + "enough" escape).

This script is PURE LOGIC: stdlib only (argparse, json, sys), NO network, NO
subprocess (unlike the sibling observe.py, which shells out to api.py). It reads a
ledger artifact, never the board. Mirrors api.py's I/O contract: the machine
result goes to STDOUT, diagnostics to STDERR, never mixed; on any non-zero usage
exit, STDOUT stays empty.

One subcommand: `verdict`. Input is the ledger artifact as a JSON list of
`{id, dimension, status, source}` on STDIN (or `--ledger @file | inline | -`),
plus the round signals `--round`, `--cap`, `--last-probe`, `--user-enough`.

  open_count       entries whose status == OPEN
  core_unresolved  ids of OPEN entries whose dimension is in the CORE set
                   (WHAT/SCOPE/ACCEPTANCE — the dimensions that gate shippability)
  residual_open    the full OPEN entry objects (for the caller's `## Open Questions`)

Stop-gate (precedence order):
  STOP-ENOUGH    iff --user-enough            — the user's escape, any round
  STOP-DEGRADED  iff round >= cap AND a CORE row is still OPEN — cap hit, under-
                 specified: caller writes `## Open Questions` + an explore/split rec
  STOP-CLEAN     iff (round >= cap, core covered)  — forced stop at the cap with the
                 core resolved; any non-core residual → `## Open Questions`
              OR iff (open_count == 0 AND core covered AND last_probe == no_new_gaps)
                 — coverage AND diminishing-returns BOTH satisfied: synthesize
  CONTINUE       otherwise — an OPEN row remains, or the last probe-scan raised a
                 new gap (diminishing-returns not yet stable): ask another round

Exit codes (verdict):
  0  STOP-CLEAN     synthesize (⑤)
  1  CONTINUE       loop (ask another round)
  2  STOP-DEGRADED  cap hit with a core dimension still OPEN — degrade gracefully
  3  STOP-ENOUGH    user said "enough" — synthesize now, residual → Open Questions
  64 usage error    bad args / malformed ledger / unknown dimension or status
                    (EX_USAGE — kept DISTINCT from the 2 STOP-DEGRADED verdict so
                    the caller never confuses an input mistake with a real cap-stop)

The 0..3 codes are the verdict contract the shell branches on (like observe.py's
gate). Usage errors are pushed to 64 (sysexits.h EX_USAGE) so the verdict space
0..3 is unambiguous — argparse's own default of 2 is overridden to 64 too.
`--json` prints the full decision object to STDOUT:
  {verdict, open_count, core_unresolved, residual_open, reason, degraded}
"""
import argparse
import json
import sys

EX_USAGE = 64  # sysexits.h — distinct from the 0..3 verdict codes (review ruling)

# The ③ gap-analysis dimension vocabulary (squad-refine/SKILL.md ③). Mirrored here
# only to validate the ledger's `dimension` field — an unknown dimension is a
# usage error, never silently counted. Keep in sync with SKILL.md ③.
DIMENSIONS = ("WHAT", "WHY", "SCOPE", "ACCEPTANCE", "CONSTRAINTS", "EDGE", "DEPS")

# The CORE set: the dimensions that gate shippability. A card is not refined while
# any of these is OPEN — they decide WHAT gets built, its boundary, and its
# done-test. CONSTRAINTS/EDGE/DEPS/WHY can land in `## Open Questions` as residual.
CORE = ("WHAT", "SCOPE", "ACCEPTANCE")

STATUSES = ("OPEN", "RESOLVED")
PROBE_OUTCOMES = ("new_gaps", "no_new_gaps")

DEFAULT_CAP = 6  # the safety cap (~5-6 rounds); the diminishing-returns backstop.


class _UsageParser(argparse.ArgumentParser):
    """argparse exits 2 on a usage error by default; override to EX_USAGE (64) so
    the verdict code space 0..3 never collides with a usage failure (review ruling
    3). --help still exits 0 (argparse calls exit(0) directly, not error())."""

    def error(self, message):
        self.print_usage(sys.stderr)
        self.exit(EX_USAGE, f"{self.prog}: error: {message}\n")


def _read_ledger_raw(arg):
    """Resolve the ledger source: `@file`, `-`/None → stdin, else inline JSON.
    Mirrors api.py's --json `@file|inline|-` contract. Returns the raw text."""
    if arg is None or arg == "-":
        return sys.stdin.read()
    if arg.startswith("@"):
        import pathlib

        path = pathlib.Path(arg[1:])
        if not path.is_file():
            raise ValueError(f"--ledger file not found: {path}")
        return path.read_text()
    return arg


def parse_ledger(raw):
    """Parse + validate the ledger artifact. Returns the list of entry dicts.

    Raises ValueError (→ EX_USAGE) on: non-JSON, not a list, a non-dict entry, a
    missing id/dimension/status, or an out-of-vocab dimension/status. Validation
    is strict on purpose — a malformed ledger must fail loudly, never resolve to a
    silently-wrong verdict (a wrong STOP would ship an under-specified card)."""
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"ledger is not valid JSON: {exc}") from exc
    if not isinstance(data, list):
        raise ValueError("ledger must be a JSON list of {id, dimension, status, source} entries")
    for i, entry in enumerate(data):
        if not isinstance(entry, dict):
            raise ValueError(f"ledger entry {i} is not an object")
        for key in ("id", "dimension", "status"):
            if key not in entry:
                raise ValueError(f"ledger entry {i} is missing required key '{key}'")
        dim = entry["dimension"]
        if dim not in DIMENSIONS:
            raise ValueError(
                f"ledger entry {entry['id']!r} has unknown dimension {dim!r} "
                f"(expected one of {', '.join(DIMENSIONS)})"
            )
        status = entry["status"]
        if status not in STATUSES:
            raise ValueError(
                f"ledger entry {entry['id']!r} has unknown status {status!r} "
                f"(expected OPEN or RESOLVED)"
            )
    return data


def compute_verdict(ledger, round_no, cap, last_probe, user_enough):
    """The deterministic stop-gate. Returns (decision_dict, exit_code).

    Precedence: user-enough → cap (degraded vs forced-clean) → coverage +
    diminishing-returns → continue. A RESOLVED entry is never counted OPEN (the
    anti-reask guarantee the Grice filter relies on)."""
    open_entries = [e for e in ledger if e["status"] == "OPEN"]
    open_count = len(open_entries)
    core_unresolved = [e["id"] for e in open_entries if e["dimension"] in CORE]
    residual_open = open_entries

    def decision(verdict, code, reason, degraded=False):
        return {
            "verdict": verdict,
            "open_count": open_count,
            "core_unresolved": core_unresolved,
            "residual_open": residual_open,
            "reason": reason,
            "degraded": degraded,
        }, code

    # 1) The user's escape — stops immediately at any round; residual → Open Questions.
    if user_enough:
        return decision(
            "STOP-ENOUGH", 3,
            f"user said enough at round {round_no}; synthesize now, {open_count} "
            f"open row(s) → ## Open Questions",
        )

    # 2) The hard cap — a forced stop (the diminishing-returns backstop).
    if round_no >= cap:
        if core_unresolved:
            return decision(
                "STOP-DEGRADED", 2,
                f"cap reached (round {round_no} >= cap {cap}) with core dimension(s) "
                f"still OPEN ({', '.join(core_unresolved)}); write ## Open Questions "
                f"+ recommend /squad-explore or a card split",
                degraded=True,
            )
        return decision(
            "STOP-CLEAN", 0,
            f"cap reached (round {round_no} >= cap {cap}); core covered, "
            f"{open_count} non-core row(s) → ## Open Questions",
        )

    # 3) Coverage AND diminishing-returns must BOTH hold to synthesize.
    if open_count == 0 and not core_unresolved and last_probe == "no_new_gaps":
        return decision(
            "STOP-CLEAN", 0,
            "no open gaps and the last probe-scan raised none (diminishing "
            "returns stable); synthesize",
        )

    # 4) Otherwise keep going — an OPEN row remains, or the probe-scan is unstable.
    if open_count > 0:
        why = f"{open_count} open gap(s) remain"
    else:
        why = "last probe-scan raised new gaps (diminishing returns not yet stable)"
    return decision("CONTINUE", 1, f"{why}; ask another round")


def cmd_verdict(args):
    try:
        raw = _read_ledger_raw(args.ledger)
        ledger = parse_ledger(raw)
    except ValueError as exc:
        sys.stderr.write(f"refine_ledger.py: error: {exc}\n")
        return EX_USAGE
    if args.cap < 1:
        sys.stderr.write("refine_ledger.py: error: --cap must be >= 1\n")
        return EX_USAGE
    if args.round < 1:
        sys.stderr.write("refine_ledger.py: error: --round must be >= 1\n")
        return EX_USAGE

    decision, code = compute_verdict(
        ledger, args.round, args.cap, args.last_probe, args.user_enough
    )
    if args.json:
        sys.stdout.write(json.dumps(decision) + "\n")
    else:
        sys.stdout.write(f"{decision['verdict']} — {decision['reason']}\n")
    return code


def build_parser():
    parser = _UsageParser(
        prog="refine_ledger.py",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="Deterministic stop-gate for the squad-refine gap-ledger loop.",
        epilog=(
            "exit codes (verdict):\n"
            "  0  STOP-CLEAN     synthesize (⑤)\n"
            "  1  CONTINUE       loop (ask another round)\n"
            "  2  STOP-DEGRADED  cap hit with a core (WHAT/SCOPE/ACCEPTANCE) row OPEN\n"
            "  3  STOP-ENOUGH    user said 'enough' — synthesize, residual → Open Questions\n"
            "  64 usage error    bad args / malformed ledger / unknown dimension or status\n"
            "                    (EX_USAGE — distinct from the 2 STOP-DEGRADED verdict)\n\n"
            "The ledger is a JSON list of {id, dimension, status, source} on stdin\n"
            "(or --ledger @file). dimension ∈ WHAT/WHY/SCOPE/ACCEPTANCE/CONSTRAINTS/\n"
            "EDGE/DEPS; the core set (gates shippability) is WHAT/SCOPE/ACCEPTANCE.\n"
            "--last-probe is the MANDATORY probe-scan outcome; absent ⇒ new_gaps (a\n"
            "STOP-CLEAN can never be reached without an explicit no_new_gaps).\n\n"
            "examples:\n"
            "  refine_ledger.py verdict --round 1 --last-probe new_gaps < ledger.json\n"
            "  refine_ledger.py verdict --round 2 --last-probe no_new_gaps --json < l.json\n"
            "  refine_ledger.py verdict --round 6 --cap 6 --ledger @l.json   # cap path\n"
            "  refine_ledger.py verdict --user-enough --ledger @l.json       # user escape\n"
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True, metavar="<verdict>")

    p_verdict = sub.add_parser(
        "verdict",
        help="compute the CONTINUE/STOP verdict from the re-emitted ledger.",
    )
    p_verdict.add_argument(
        "--ledger",
        metavar="<@file|inline|->",
        default=None,
        help="the ledger artifact: @file, inline JSON, or - / omitted for stdin.",
    )
    p_verdict.add_argument(
        "--round", type=int, default=1, metavar="N",
        help="the current round number (1-based).",
    )
    p_verdict.add_argument(
        "--cap", type=int, default=DEFAULT_CAP, metavar="M",
        help=f"the safety cap; round >= cap forces a stop (default {DEFAULT_CAP}).",
    )
    p_verdict.add_argument(
        "--last-probe",
        dest="last_probe",
        choices=PROBE_OUTCOMES,
        default="new_gaps",
        help="the last round's MANDATORY probe-scan outcome (default new_gaps — a "
        "missing probe can never reach STOP-CLEAN).",
    )
    p_verdict.add_argument(
        "--user-enough",
        dest="user_enough",
        action="store_true",
        help="the user said 'enough' — stop immediately (STOP-ENOUGH, exit 3).",
    )
    p_verdict.add_argument(
        "--json",
        action="store_true",
        help="emit the full decision object to stdout.",
    )
    p_verdict.set_defaults(func=cmd_verdict)
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
