"""Offline hermetic unit tests for skills/squad/scripts/refine_ledger.py (SQD-590).

refine_ledger.py is the DETERMINISTIC stop-gate for the squad-refine gap-ledger
loop.  It is pure stdlib logic (no network, no board, no secrets).  Two test
surfaces are exercised for every verdict branch:

  (a) compute_verdict() — direct importable call (fast, in-process).
  (b) CLI subprocess   — stdin / --ledger @file / --ledger inline, verifying the
                         exit-code contract that SKILL.md branches on.

Coverage summary (one case per exit-code branch as requested by Builder):
  exit 0  STOP-CLEAN     — normal coverage path AND forced cap + core covered
  exit 1  CONTINUE       — OPEN>0 AND all-resolved + new_gaps (probe unstable)
  exit 2  STOP-DEGRADED  — cap reached with a core (WHAT/SCOPE/ACCEPTANCE) row OPEN
  exit 3  STOP-ENOUGH    — --user-enough flag (highest-precedence escape)
  exit 64 usage          — malformed JSON, not-a-list, missing key, unknown
                           dimension/status, --round 0, --cap 0; stdout always empty

Additional coverage: anti-reask (RESOLVED never counted OPEN), empty-ledger
fail-safe, --ledger inline + @file + not-found, residual_open content, all seven
vocabulary dimensions accepted, stdout/stderr contract mirrors api.py.

Mirror of tests/test_observe.py style (subprocess + importable, hermetic, no board).
"""
import ast
import json
import pathlib
import subprocess
import sys
import tempfile

import pytest

SCRIPTS_DIR = (
    pathlib.Path(__file__).resolve().parents[1] / "skills" / "squad" / "scripts"
)
LEDGER_SCRIPT = SCRIPTS_DIR / "refine_ledger.py"

# ── shared ledger JSON strings ────────────────────────────────────────────────

# Single OPEN WHAT row → CONTINUE regardless of probe outcome
ONE_OPEN_WHAT = '[{"id":"g1","dimension":"WHAT","status":"OPEN","source":"original"}]'

# Fully resolved; with no_new_gaps → STOP-CLEAN; with new_gaps → CONTINUE
ALL_RESOLVED = '[{"id":"g1","dimension":"WHAT","status":"RESOLVED","source":"original"}]'

# Cap path: core (SCOPE) still OPEN → STOP-DEGRADED
CAP_CORE_OPEN = (
    '[{"id":"g1","dimension":"SCOPE","status":"OPEN","source":"original"},'
    '{"id":"g2","dimension":"ACCEPTANCE","status":"RESOLVED","source":"original"}]'
)

# Cap path: core fully covered, only non-core (EDGE) residual → STOP-CLEAN forced
CAP_NONCORE_ONLY = (
    '[{"id":"g1","dimension":"WHAT","status":"RESOLVED","source":"original"},'
    '{"id":"g2","dimension":"EDGE","status":"OPEN","source":"raised-by-answer-R2"}]'
)

# Empty ledger
EMPTY_LEDGER = "[]"


# ── subprocess helper ────────────────────────────────────────────────────────

def _run_cli(ledger_stdin, *extra_args):
    """Run `refine_ledger.py verdict` as a subprocess.

    ledger_stdin=None means no stdin piping (use --ledger flag instead).
    Returns (returncode, stdout, stderr).
    """
    cmd = [sys.executable, str(LEDGER_SCRIPT), "verdict"] + list(extra_args)
    res = subprocess.run(
        cmd,
        input=ledger_stdin,
        capture_output=True,
        text=True,
        timeout=15,
    )
    return res.returncode, res.stdout, res.stderr


# ── zero-dependency guard ────────────────────────────────────────────────────

def test_zero_dependency_stdlib_only():
    """refine_ledger.py top-level imports are exactly argparse/json/sys; pathlib is lazy.

    The Builder promised stdlib-only (no network, no third-party).  This mirrors
    test_observe.py's guard: any accidental top-level import of a non-stdlib or
    heavy module fails immediately.  pathlib is intentionally lazy (only inside
    _read_ledger_raw for @file mode) so it PASSES here — the lazy import is fine.
    """
    tree = ast.parse(LEDGER_SCRIPT.read_text())
    top_level_imports: set[str] = set()
    for node in ast.iter_child_nodes(tree):  # top-level only, not ast.walk
        if isinstance(node, ast.Import):
            for alias in node.names:
                top_level_imports.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            top_level_imports.add(node.module.split(".")[0])
    # The script body has exactly these three at the module level.
    assert top_level_imports == {"argparse", "json", "sys"}, (
        f"unexpected top-level imports: {top_level_imports}"
    )


# ── --help and no-subcommand ─────────────────────────────────────────────────

def test_help_exits_zero():
    """--help exits 0 (argparse's own SystemExit(0) — not the EX_USAGE override)."""
    res = subprocess.run(
        [sys.executable, str(LEDGER_SCRIPT), "--help"],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0
    combined = res.stdout + res.stderr
    assert "verdict" in combined  # the one subcommand is documented


def test_no_subcommand_exits_64():
    """No subcommand → _UsageParser.error() → exit 64 (EX_USAGE), not argparse's default 2.

    Critic ruling 3: usage errors exit 64, distinct from the 2 STOP-DEGRADED verdict.
    argparse's default is 2; the _UsageParser override must change it.
    """
    res = subprocess.run(
        [sys.executable, str(LEDGER_SCRIPT)],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 64
    assert res.stdout == ""  # stdout stays empty on any usage error


# ── CONTINUE (exit 1): OPEN>0 ────────────────────────────────────────────────

def test_continue_open_gt_0_importable(refine_ledger):
    """compute_verdict with OPEN>0 → CONTINUE, exit code 1."""
    ledger = [{"id": "g1", "dimension": "WHAT", "status": "OPEN", "source": "original"}]
    decision, code = refine_ledger.compute_verdict(
        ledger, round_no=1, cap=6, last_probe="no_new_gaps", user_enough=False
    )
    assert code == 1
    assert decision["verdict"] == "CONTINUE"
    assert decision["open_count"] == 1


def test_continue_open_gt_0_cli():
    """CLI: OPEN>0 → exit 1 with CONTINUE in human output."""
    rc, out, err = _run_cli(ONE_OPEN_WHAT, "--round", "1", "--last-probe", "no_new_gaps")
    assert rc == 1
    assert "CONTINUE" in out


# ── CONTINUE (exit 1): probe unstable (new_gaps despite all-resolved) ────────

def test_continue_new_gaps_probe_all_resolved_importable(refine_ledger):
    """open_count==0 but last_probe=new_gaps → CONTINUE (diminishing-returns unstable).

    A STOP-CLEAN is only reachable when BOTH open_count==0 AND the last probe-scan
    produced no_new_gaps.  The probe-scan gate prevents premature synthesis even when
    all prior gaps were resolved.
    """
    ledger = [{"id": "g1", "dimension": "WHAT", "status": "RESOLVED", "source": "original"}]
    decision, code = refine_ledger.compute_verdict(
        ledger, round_no=2, cap=6, last_probe="new_gaps", user_enough=False
    )
    assert code == 1
    assert decision["verdict"] == "CONTINUE"
    assert decision["open_count"] == 0  # open_count is 0, but probe says unstable


def test_continue_new_gaps_probe_all_resolved_cli():
    """CLI: all-resolved + --last-probe new_gaps → exit 1."""
    rc, out, err = _run_cli(ALL_RESOLVED, "--round", "2", "--last-probe", "new_gaps")
    assert rc == 1
    assert "CONTINUE" in out


# ── STOP-CLEAN (exit 0): normal coverage path ────────────────────────────────

def test_stop_clean_all_resolved_no_new_gaps_importable(refine_ledger):
    """compute_verdict: open_count==0 AND last_probe=no_new_gaps → STOP-CLEAN, exit 0."""
    ledger = [{"id": "g1", "dimension": "WHAT", "status": "RESOLVED", "source": "original"}]
    decision, code = refine_ledger.compute_verdict(
        ledger, round_no=2, cap=6, last_probe="no_new_gaps", user_enough=False
    )
    assert code == 0
    assert decision["verdict"] == "STOP-CLEAN"
    assert decision["degraded"] is False
    assert decision["open_count"] == 0
    assert decision["core_unresolved"] == []
    assert decision["residual_open"] == []


def test_stop_clean_all_resolved_no_new_gaps_cli():
    """CLI: all-resolved + --last-probe no_new_gaps → exit 0 with STOP-CLEAN."""
    rc, out, err = _run_cli(ALL_RESOLVED, "--round", "2", "--last-probe", "no_new_gaps")
    assert rc == 0
    assert "STOP-CLEAN" in out


def test_stop_clean_json_shape_all_keys(refine_ledger):
    """--json decision dict contains all required keys with correct types."""
    ledger = [{"id": "g1", "dimension": "SCOPE", "status": "RESOLVED", "source": "original"}]
    decision, code = refine_ledger.compute_verdict(
        ledger, round_no=1, cap=6, last_probe="no_new_gaps", user_enough=False
    )
    assert code == 0
    required = {"verdict", "open_count", "core_unresolved", "residual_open", "reason", "degraded"}
    missing = required - set(decision)
    assert not missing, f"decision dict missing keys: {missing}"
    assert isinstance(decision["open_count"], int)
    assert isinstance(decision["core_unresolved"], list)
    assert isinstance(decision["residual_open"], list)
    assert isinstance(decision["degraded"], bool)
    assert isinstance(decision["reason"], str) and decision["reason"]


def test_stop_clean_json_cli():
    """CLI --json: STOP-CLEAN emits parseable JSON with all required fields."""
    rc, out, err = _run_cli(ALL_RESOLVED, "--round", "2", "--last-probe", "no_new_gaps", "--json")
    assert rc == 0
    decision = json.loads(out)
    assert decision["verdict"] == "STOP-CLEAN"
    assert decision["degraded"] is False
    assert decision["core_unresolved"] == []
    assert decision["residual_open"] == []
    assert isinstance(decision["open_count"], int)


# ── STOP-CLEAN (exit 0): forced cap with core covered ────────────────────────

def test_stop_clean_cap_core_covered_importable(refine_ledger):
    """Cap hit with only non-core (EDGE) rows OPEN → STOP-CLEAN forced, not STOP-DEGRADED.

    The non-core residual should appear in residual_open for the caller's ## Open Questions.
    """
    ledger = [
        {"id": "g1", "dimension": "WHAT", "status": "RESOLVED", "source": "original"},
        {"id": "g2", "dimension": "EDGE", "status": "OPEN", "source": "raised-by-answer-R2"},
    ]
    decision, code = refine_ledger.compute_verdict(
        ledger, round_no=6, cap=6, last_probe="new_gaps", user_enough=False
    )
    assert code == 0
    assert decision["verdict"] == "STOP-CLEAN"
    assert decision["degraded"] is False
    assert any(e["id"] == "g2" for e in decision["residual_open"])
    assert decision["core_unresolved"] == []  # no core row is OPEN


def test_stop_clean_cap_core_covered_cli():
    """CLI: cap hit + core covered → exit 0 with STOP-CLEAN verdict."""
    rc, out, err = _run_cli(CAP_NONCORE_ONLY, "--round", "6", "--cap", "6", "--json")
    assert rc == 0
    decision = json.loads(out)
    assert decision["verdict"] == "STOP-CLEAN"
    assert decision["degraded"] is False


# ── STOP-DEGRADED (exit 2) ───────────────────────────────────────────────────

def test_stop_degraded_cap_core_open_importable(refine_ledger):
    """Cap reached with a CORE row OPEN → STOP-DEGRADED, exit 2, degraded=True.

    SCOPE is a CORE dimension (WHAT/SCOPE/ACCEPTANCE); cap + SCOPE OPEN → degrade.
    """
    ledger = [
        {"id": "g1", "dimension": "SCOPE", "status": "OPEN", "source": "original"},
        {"id": "g2", "dimension": "ACCEPTANCE", "status": "RESOLVED", "source": "original"},
    ]
    decision, code = refine_ledger.compute_verdict(
        ledger, round_no=6, cap=6, last_probe="new_gaps", user_enough=False
    )
    assert code == 2
    assert decision["verdict"] == "STOP-DEGRADED"
    assert decision["degraded"] is True
    assert "g1" in decision["core_unresolved"]
    assert "g2" not in decision["core_unresolved"]  # RESOLVED, not counted


def test_stop_degraded_cap_core_open_cli():
    """CLI: cap + core OPEN → exit 2, JSON degraded=True, core_unresolved non-empty."""
    rc, out, err = _run_cli(CAP_CORE_OPEN, "--round", "6", "--cap", "6", "--json")
    assert rc == 2
    decision = json.loads(out)
    assert decision["verdict"] == "STOP-DEGRADED"
    assert decision["degraded"] is True
    assert len(decision["core_unresolved"]) >= 1


def test_stop_degraded_core_unresolved_exactly_open_core_ids(refine_ledger):
    """core_unresolved contains exactly the OPEN CORE entry ids, not EDGE/non-core."""
    ledger = [
        {"id": "w1", "dimension": "WHAT", "status": "OPEN", "source": "original"},
        {"id": "s1", "dimension": "SCOPE", "status": "OPEN", "source": "original"},
        {"id": "a1", "dimension": "ACCEPTANCE", "status": "RESOLVED", "source": "original"},
        {"id": "e1", "dimension": "EDGE", "status": "OPEN", "source": "original"},
        {"id": "c1", "dimension": "CONSTRAINTS", "status": "RESOLVED", "source": "original"},
    ]
    decision, code = refine_ledger.compute_verdict(
        ledger, round_no=6, cap=6, last_probe="new_gaps", user_enough=False
    )
    assert code == 2
    # WHAT + SCOPE are OPEN CORE; ACCEPTANCE is RESOLVED; EDGE is non-core
    assert set(decision["core_unresolved"]) == {"w1", "s1"}


# ── STOP-ENOUGH (exit 3) ────────────────────────────────────────────────────

def test_stop_enough_importable(refine_ledger):
    """--user-enough → STOP-ENOUGH, exit 3, regardless of ledger open count."""
    ledger = [{"id": "g1", "dimension": "WHAT", "status": "OPEN", "source": "original"}]
    decision, code = refine_ledger.compute_verdict(
        ledger, round_no=1, cap=6, last_probe="new_gaps", user_enough=True
    )
    assert code == 3
    assert decision["verdict"] == "STOP-ENOUGH"


def test_stop_enough_cli():
    """CLI: --user-enough → exit 3 with STOP-ENOUGH."""
    rc, out, err = _run_cli(ONE_OPEN_WHAT, "--round", "1", "--user-enough", "--json")
    assert rc == 3
    decision = json.loads(out)
    assert decision["verdict"] == "STOP-ENOUGH"


def test_stop_enough_beats_cap(refine_ledger):
    """--user-enough has the highest precedence — beats the cap + core-OPEN path."""
    ledger = [{"id": "g1", "dimension": "SCOPE", "status": "OPEN", "source": "original"}]
    # round==cap AND core OPEN — without --user-enough this would be STOP-DEGRADED
    decision, code = refine_ledger.compute_verdict(
        ledger, round_no=6, cap=6, last_probe="new_gaps", user_enough=True
    )
    assert code == 3
    assert decision["verdict"] == "STOP-ENOUGH"


def test_stop_enough_beats_clean_state(refine_ledger):
    """--user-enough also beats STOP-CLEAN (all resolved + no_new_gaps)."""
    ledger = [{"id": "g1", "dimension": "WHAT", "status": "RESOLVED", "source": "original"}]
    decision, code = refine_ledger.compute_verdict(
        ledger, round_no=1, cap=6, last_probe="no_new_gaps", user_enough=True
    )
    assert code == 3
    assert decision["verdict"] == "STOP-ENOUGH"


# ── Usage errors (exit 64) — distinct from the 2 STOP-DEGRADED verdict ───────

def test_usage_malformed_json_exits_64():
    """Non-JSON stdin → exit 64 (EX_USAGE); STDOUT stays empty."""
    rc, out, err = _run_cli("not valid json {{{", "--round", "1")
    assert rc == 64
    assert out == ""
    assert err  # diagnostic message on stderr


def test_usage_not_a_list_exits_64():
    """Ledger is a JSON object (not a list) → exit 64."""
    rc, out, err = _run_cli(
        '{"id":"g1","dimension":"WHAT","status":"OPEN"}', "--round", "1"
    )
    assert rc == 64
    assert out == ""


def test_usage_missing_required_key_exits_64():
    """Entry missing required 'status' key → exit 64."""
    rc, out, err = _run_cli('[{"id":"g1","dimension":"WHAT"}]', "--round", "1")
    assert rc == 64
    assert out == ""


def test_usage_unknown_dimension_exits_64():
    """Entry with out-of-vocabulary dimension → exit 64 (not STOP-DEGRADED 2)."""
    rc, out, err = _run_cli(
        '[{"id":"g1","dimension":"FOO","status":"OPEN"}]', "--round", "1"
    )
    assert rc == 64
    assert out == ""


def test_usage_unknown_status_exits_64():
    """Entry with unknown status value → exit 64."""
    rc, out, err = _run_cli(
        '[{"id":"g1","dimension":"WHAT","status":"IN_PROGRESS"}]', "--round", "1"
    )
    assert rc == 64
    assert out == ""


def test_usage_round_zero_exits_64():
    """--round 0 → exit 64; --round must be >= 1."""
    rc, out, err = _run_cli(ALL_RESOLVED, "--round", "0", "--last-probe", "no_new_gaps")
    assert rc == 64
    assert out == ""


def test_usage_cap_zero_exits_64():
    """--cap 0 → exit 64; --cap must be >= 1."""
    rc, out, err = _run_cli(
        ALL_RESOLVED, "--round", "1", "--cap", "0", "--last-probe", "no_new_gaps"
    )
    assert rc == 64
    assert out == ""


def test_usage_64_distinct_from_verdict_2():
    """Exit 64 (usage error) is a different integer from exit 2 (STOP-DEGRADED).

    This is the whole point of EX_USAGE: the SKILL.md caller must never confuse
    an input mistake with a real cap-degraded stop (Critic ruling 3).
    """
    rc_usage, _, _ = _run_cli("not json", "--round", "1")
    rc_degraded, _, _ = _run_cli(CAP_CORE_OPEN, "--round", "6", "--cap", "6")
    assert rc_usage == 64
    assert rc_degraded == 2
    assert rc_usage != rc_degraded


# ── anti-reask: RESOLVED never counted OPEN ─────────────────────────────────

def test_anti_reask_resolved_not_counted_importable(refine_ledger):
    """A RESOLVED entry is never counted as OPEN (the Grice quality-filter guarantee).

    The anti-reask invariant: once an entry is RESOLVED, it must never appear in
    open_count or core_unresolved.  This underpins the 'never re-ask a resolved gap'
    rule in SKILL.md.
    """
    ledger = [
        {"id": "g1", "dimension": "WHAT", "status": "RESOLVED", "source": "original"},
        {"id": "g2", "dimension": "SCOPE", "status": "RESOLVED", "source": "original"},
        {"id": "g3", "dimension": "ACCEPTANCE", "status": "RESOLVED", "source": "original"},
    ]
    decision, code = refine_ledger.compute_verdict(
        ledger, round_no=1, cap=6, last_probe="no_new_gaps", user_enough=False
    )
    assert code == 0  # STOP-CLEAN: all CORE resolved + no_new_gaps
    assert decision["open_count"] == 0
    assert decision["core_unresolved"] == []
    assert decision["residual_open"] == []


def test_anti_reask_resolved_not_counted_cli():
    """CLI: a ledger with only RESOLVED entries → open_count=0 in --json output."""
    rc, out, err = _run_cli(ALL_RESOLVED, "--round", "1", "--last-probe", "no_new_gaps", "--json")
    assert rc == 0
    decision = json.loads(out)
    assert decision["open_count"] == 0
    assert decision["core_unresolved"] == []


# ── empty ledger fail-safe ───────────────────────────────────────────────────

def test_empty_ledger_default_probe_continue_importable(refine_ledger):
    """Empty ledger [] with default probe (new_gaps) → CONTINUE (fail-safe).

    A STOP-CLEAN can NEVER be reached without an explicit no_new_gaps probe result.
    The default --last-probe is new_gaps so a missing probe outcome keeps the loop
    going rather than synthesising prematurely (Builder: 'fail-safe default').
    """
    decision, code = refine_ledger.compute_verdict(
        [], round_no=1, cap=6, last_probe="new_gaps", user_enough=False
    )
    assert code == 1
    assert decision["verdict"] == "CONTINUE"


def test_empty_ledger_no_new_gaps_stop_clean_importable(refine_ledger):
    """Empty ledger [] with no_new_gaps → STOP-CLEAN.

    open_count=0 AND last_probe=no_new_gaps → both coverage and diminishing-returns
    conditions satisfied → STOP-CLEAN is the correct verdict.
    """
    decision, code = refine_ledger.compute_verdict(
        [], round_no=1, cap=6, last_probe="no_new_gaps", user_enough=False
    )
    assert code == 0
    assert decision["verdict"] == "STOP-CLEAN"


def test_empty_ledger_default_probe_continue_cli():
    """CLI: [] with no --last-probe (argparse default = new_gaps) → exit 1 (fail-safe)."""
    # Omit --last-probe to exercise the default
    rc, out, err = _run_cli(EMPTY_LEDGER, "--round", "1")
    assert rc == 1
    assert "CONTINUE" in out


# ── --ledger modes ──────────────────────────────────────────────────────────

def test_ledger_inline_flag():
    """--ledger <inline-JSON> works without stdin piping."""
    rc, out, err = _run_cli(
        None,  # no stdin
        "--ledger", ALL_RESOLVED, "--round", "2", "--last-probe", "no_new_gaps",
    )
    assert rc == 0
    assert "STOP-CLEAN" in out


def test_ledger_at_file():
    """--ledger @<path> reads the ledger from a temporary file."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        f.write(ALL_RESOLVED)
        path = f.name
    try:
        rc, out, err = _run_cli(
            None,
            "--ledger", f"@{path}", "--round", "2", "--last-probe", "no_new_gaps",
        )
        assert rc == 0
        assert "STOP-CLEAN" in out
    finally:
        pathlib.Path(path).unlink(missing_ok=True)


def test_ledger_at_file_not_found_exits_64():
    """--ledger @nonexistent path → exit 64 (file-not-found is a usage error)."""
    rc, out, err = _run_cli(
        None,
        "--ledger", "@/nonexistent/path/ledger_sqd590.json", "--round", "1",
    )
    assert rc == 64
    assert out == ""


# ── residual_open content ────────────────────────────────────────────────────

def test_residual_open_contains_exactly_open_entries(refine_ledger):
    """residual_open is the exact OPEN subset; RESOLVED entries are excluded."""
    ledger = [
        {"id": "g1", "dimension": "WHAT", "status": "RESOLVED", "source": "original"},
        {"id": "g2", "dimension": "SCOPE", "status": "OPEN", "source": "raised-by-answer-R1"},
        {"id": "g3", "dimension": "EDGE", "status": "OPEN", "source": "raised-by-answer-R2"},
        {"id": "g4", "dimension": "CONSTRAINTS", "status": "RESOLVED", "source": "original"},
    ]
    decision, code = refine_ledger.compute_verdict(
        ledger, round_no=1, cap=6, last_probe="new_gaps", user_enough=False
    )
    assert code == 1  # SCOPE is OPEN → CONTINUE
    open_ids = {e["id"] for e in decision["residual_open"]}
    assert open_ids == {"g2", "g3"}
    assert all(e["status"] == "OPEN" for e in decision["residual_open"])


# ── all DIMENSIONS accepted ──────────────────────────────────────────────────

@pytest.mark.parametrize(
    "dim",
    ["WHAT", "WHY", "SCOPE", "ACCEPTANCE", "CONSTRAINTS", "EDGE", "DEPS"],
)
def test_all_dimensions_accepted_no_usage_error(refine_ledger, dim):
    """Every vocabulary dimension in DIMENSIONS is accepted without a usage error.

    Validates both the list constant and the parse_ledger validation logic.
    A RESOLVED entry in each dimension with no_new_gaps → STOP-CLEAN (exit 0).
    """
    ledger = [{"id": "g1", "dimension": dim, "status": "RESOLVED", "source": "original"}]
    decision, code = refine_ledger.compute_verdict(
        ledger, round_no=1, cap=6, last_probe="no_new_gaps", user_enough=False
    )
    assert code == 0, (
        f"dimension {dim!r} should be accepted but got exit {code}"
    )


# ── stdout / stderr contract ─────────────────────────────────────────────────

def test_stdout_empty_on_every_usage_error():
    """Any usage error (exit 64) keeps STDOUT empty; diagnostics go to STDERR only.

    Mirrors api.py's I/O contract: machine result on STDOUT, diagnostics on STDERR,
    never mixed.  STDOUT being empty means the caller can safely `$()` the output.
    """
    cases = [
        ("not json", ["--round", "1"]),                     # malformed JSON
        (None, ["--ledger", '[{"id":"x"}]', "--round", "1"]),   # missing keys
        (None, ["--ledger", ALL_RESOLVED, "--round", "0"]),     # --round 0
        (None, ["--ledger", ALL_RESOLVED, "--cap", "0"]),        # --cap 0
    ]
    for stdin, args in cases:
        rc, out, err = _run_cli(stdin, *args)
        assert rc == 64, f"expected 64, got {rc} for args {args}"
        assert out == "", f"expected empty stdout for args {args}, got: {out!r}"


def test_stdout_has_verdict_on_success():
    """A successful verdict (exit 0..3) writes a non-empty VERDICT line to STDOUT."""
    rc, out, err = _run_cli(ALL_RESOLVED, "--round", "1", "--last-probe", "no_new_gaps")
    assert rc == 0
    assert out.strip(), "STDOUT should contain the human-readable verdict line"
