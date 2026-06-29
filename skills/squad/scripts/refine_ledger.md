# refine_ledger.py — the squad-refine stop-gate

A zero-dependency, **pure-logic** helper that owns the deterministic stop decision
for the squad-refine gap-ledger interview loop. The interview's "ask
another round vs synthesize" choice is a deterministic, auditable, low-freedom
operation, so it lives in code (not model judgement) — Anthropic's "prefer scripts
for deterministic operations". python3 stdlib-only (`argparse, json, sys`);
**no network, no subprocess** (unlike the sibling `observe.py`, which shells out to
`api.py`). It reads a ledger artifact off stdin and never touches the board.

**Division of labour** (the whole point): the LLM **generates** the semantic
content — which gaps exist, what each probe-scan over an answer turns up; the
script **counts + decides** — OPEN count, coverage + diminishing-returns + hard-cap
checks → a CONTINUE/STOP verdict + the residual-open list. SKILL.md re-emits the
full ledger every round, pipes it here, and **OBEYS the exit code**. The model
never self-adjudicates the stop ("looks done" is a known gameable failure).

## Invocation

~~~
refine_ledger.py verdict [--ledger <@file|inline|->] [--round N] [--cap M] \
                         [--last-probe <new_gaps|no_new_gaps>] [--user-enough] [--json]
~~~

- **`verdict`** — compute the stop-gate from the re-emitted ledger. The ledger is a
  JSON list of `{id, dimension, status, source}` on **stdin** (or `--ledger @file`).
  `--round` is the 1-based round number; `--cap` is the safety cap (default 6);
  `--last-probe` is the **mandatory** probe-scan outcome for the round just asked;
  `--user-enough` is the user's escape. `--json` emits the decision object to stdout;
  the caller branches on the **exit code** alone.

## The ledger artifact

A fixed-schema JSON list the agent **re-emits in full every round** (state lives in
tokens, not memory — per the multi-turn-reliability evidence). Each entry:

| Field       | Values |
|-------------|--------|
| `id`        | a stable gap id (e.g. `g1`, `scope-bulk`) |
| `dimension` | `WHAT` / `WHY` / `SCOPE` / `ACCEPTANCE` / `CONSTRAINTS` / `EDGE` / `DEPS` (the ③ vocab) |
| `status`    | `OPEN` / `RESOLVED` |
| `source`    | `original` (seeded from ③) / `raised-by-answer-R#` (a probe-scan hit) |

The **core set** that gates shippability is `WHAT` / `SCOPE` / `ACCEPTANCE` — a card
is never "refined" while any of these is OPEN. `CONSTRAINTS` / `EDGE` / `DEPS` / `WHY`
can land in `## Open Questions` as residual. An out-of-vocab `dimension` or `status`
is a **usage error** (exit 64), never silently counted.

## Stop-gate

Precedence order (the first match wins):

| Verdict | When | Caller does |
|---------|------|-------------|
| **STOP-ENOUGH** | `--user-enough` (any round) | synthesize now; residual OPEN → `## Open Questions` |
| **STOP-DEGRADED** | `round >= cap` AND a **core** row is still OPEN | `## Open Questions` + recommend `/squad-explore` or a card split |
| **STOP-CLEAN** | `round >= cap` with the core covered | synthesize; non-core residual → `## Open Questions` |
| **STOP-CLEAN** | `open_count == 0` AND core covered AND `last_probe == no_new_gaps` | synthesize (⑤) |
| **CONTINUE** | otherwise — an OPEN row remains, or the last probe raised a new gap | ask another round |

`--last-probe` defaults to `new_gaps`: a STOP-CLEAN can **never** be reached without
an explicit `no_new_gaps` — a missing probe-scan keeps the loop going (fail-safe).
A `RESOLVED` entry is never counted OPEN (the anti-reask guarantee the Grice filter
relies on).

## Exit codes (verdict)

| Code | Verdict | Meaning |
|------|---------|---------|
| 0 | STOP-CLEAN | synthesize (⑤) |
| 1 | CONTINUE | loop (ask another round) |
| 2 | STOP-DEGRADED | cap hit with a core (WHAT/SCOPE/ACCEPTANCE) row OPEN — degrade gracefully |
| 3 | STOP-ENOUGH | user said "enough" — synthesize, residual → `## Open Questions` |
| 64 | usage error | bad args / malformed ledger / unknown dimension or status (EX_USAGE) |

The `0..3` codes are the verdict contract the shell branches on (`case $? in …`,
like `observe.py gate`). Usage errors are pushed to **64** (`sysexits.h` EX_USAGE) —
**distinct** from the `2` STOP-DEGRADED verdict — so an input mistake is never read
as a real cap-stop (argparse's own default of `2` is overridden to `64` too). The
full contract also lives in `refine_ledger.py --help`.

## `--json` decision object

`refine_ledger.py verdict --json` prints one object to stdout:

~~~
{ "verdict": "CONTINUE", "open_count": 2,
  "core_unresolved": ["g1"],            # ids of OPEN entries in the core set
  "residual_open": [ {id, dimension, status, source}, … ],   # full OPEN entries
  "reason": "<human explanation>", "degraded": false }
~~~

## Self-check

`refine_ledger_smoke.py` runs the script across every branch (CONTINUE / STOP-CLEAN
/ STOP-DEGRADED / STOP-ENOUGH / usage-64) and asserts the exit codes + the `--json`
shape. It is pure-logic (no board, no token), so it runs anywhere; the hermetic
pytest lock (`tests/test_refine_ledger.py`) is the CI gate.
