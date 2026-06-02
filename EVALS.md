# Evaluating the Squad skills

Skills are LLM-driven, so we test in **two tiers** — a fast deterministic gate on every
PR, and a heavier behavioral suite (real agent + LLM-as-judge) run on-demand/nightly.

| Tier | What it checks | Cost | When |
|------|----------------|------|------|
| **`tests/`** (pytest) | the *non-LLM* parts — selector parsing, grouping/parallel rules, auth resolution, prompt rendering | free, ~instant | **every PR** (CI: `tests.yml`) |
| **`evals/`** (DeepEval) | the *agent's behavior* — does `/squad add`, `/squad-refine`, etc. produce the right **board state** + a good response | tokens (real agent + judge) | **on-demand + nightly** (CI: `evals.yml`) |

## Tier 1 — deterministic (run this constantly)
```bash
pip install -r tests/requirements.txt
python -m pytest tests/ -q
```
Pure functions with exact expected outputs (`expand_selector`, `parse_*`, `build_groups`,
`load_squad_auth`, `render_agent_prompt`). This is where mechanical regressions hide; it
gates every PR via `.github/workflows/tests.yml`.

## Tier 2 — behavioral (run before/after a skill change, and nightly)
Runs the **real agent headless** (`claude -p --output-format stream-json`) against a live
**`squad-eval`** board project, **N trials per scenario**, scoring each two ways:
1. **Deterministic board ground truth** — after the run, query the board: was the task
   created / moved / refined as expected? (objective hard gate, not fuzzy)
2. **GEval rubric** — LLM-as-judge on the response quality (`evals/scenarios.yaml`).

Per-trial scores append to a git-versioned **`evals/history.jsonl`** (committed), the run is
compared to a **trailing baseline** (per-scenario floor + Welch's t-test), and a
self-contained **HTML trend dashboard** is written to `evals/results/report.html`.

**No API key needed locally** — the agent run *and* the GEval judge both go through your
**Claude Code login**. You only need the board token:
```bash
export SQUAD_AUTH_TOKEN=…            # board (or use ~/.squad/auth)
# one-time: ensure the test project exists →  /squad-init squad-eval
pip install -r evals/requirements.txt

python evals/run_evals.py                 # light scenarios, 3 trials, report + history, no gate
python evals/run_evals.py --heavy --trials 5 --gate   # + squad-run/squad-explore, gated (nightly)
python evals/run_evals.py --scenario squad-init       # just one scenario
```
Flags: `--trials N`, `--heavy` (include the costly squad-run/squad-explore scenarios),
`--window N` (baseline runs), `--floor 0.7` (per-scenario score floor), `--no-judge`
(board-state only), `--gate` (exit non-zero on hard-fail/regression), `--no-report`.

**Coverage — all 5 core skills:**

| Scenario | Skill | Deterministic check | Heavy? |
|----------|-------|---------------------|--------|
| `add-task` | `squad` (create) | task exists, priority/level correct | |
| `board-view` | `squad` (read) | rubric only (read-only) | |
| `squad-init` | `squad-init` | `.squadrc` written with `SQUAD_PROJECT=` | |
| `refine-vague` | `squad-refine` | description gains `## Goal` / `## Scope` | |
| `explore` | `squad-explore` | `[Explore]` report + `explore`-tagged tasks created | ✓ |
| `run-step` | `squad-run` | task progressed past `todo` (plan/impl written) | ✓ |

`squad-run` and `squad-explore` spawn sub-agents and (for run) commit, so they're **opt-in**
via `--heavy` to keep casual/PR runs cheap; the nightly CI includes them.

> **Headless limitation (heavy scenarios):** under a non-TTY parent (our subprocess, and CI),
> `claude -p` can hang on **parallel** sub-agent fan-out ([claude-code#56540](https://github.com/anthropics/claude-code/issues/56540)).
> The skills dispatch sub-agents serially, so this mostly doesn't bite — and if it does, the
> per-scenario `timeout` makes `run_agent` **fail-soft** (the trial is recorded as a failure and
> the gate flags it; the suite never hangs). Heavy-scenario flakiness is usually this, not a skill bug.
Without the `claude` CLI / token it exits with a clear message. Scenarios self-clean — created
tasks carry a `[[eval]]` marker and are deleted after each trial.

**Judge options (keyless-first):**
- default → your **`claude` CLI login** wraps as the GEval judge (no key);
- `export DEEPEVAL_OLLAMA_MODEL=llama3.1` → local Ollama judge;
- `export ANTHROPIC_API_KEY=…` → Anthropic judge (fastest, most robust);
- **no judge at all** → the **deterministic board-state assertions still run** — you just skip the rubric layer.

> CI (`evals.yml`) has no interactive login, so *there* it needs `ANTHROPIC_API_KEY` as a
> secret. Locally, your Claude Code login covers both agent and judge.

### Add a scenario
Append to `evals/scenarios.yaml`. A scenario has a `prompt`, optional `setup`, an `expect`
block, and a `rubric`:
- **`setup`**: `create_task{}` (seed a board task; `{{task_id}}` is substituted into the prompt),
  `workdir_files{path: content}` (seed the temp cwd a codebase skill explores), `git_init: true`,
  `no_squadrc: true` (for `squad-init`, which writes its own).
- **`expect`**: `board_task{title_contains, priority, level, status, status_not, tags_contains,
  description_contains_any[], progressed}`, `board_has[{title_contains|tags_contains}]`,
  `file_contains{path, any[]}`.
- **`heavy: true`** if it spawns sub-agents / commits.

Headless agents can't answer `AskUserQuestion`, so prompts must say *"assume sensible defaults;
don't ask questions."* Keep the golden set **hard** — a 100% pass rate usually means it's too easy.
Created tasks/projects are cleaned up automatically (snapshot-diff + `[[eval]]` sweep).

## "Did this change make it better?" — the trend, not a snapshot
This is built in, not a manual before/after. Each run records per-scenario scores to
`history.jsonl` with the **git SHA**, so the harness answers "better or worse?" itself:

- **Deterministic pass-rate** per scenario (the objective signal) — `k/N` trials.
- **Mean GEval score** vs the trailing baseline, with a **Welch's t-test** so a real drop
  flags `🔴 regression` while run-to-run noise reads `⚪ within noise`; a real gain reads `🟢 improve`.
- **Agent cost** signals (tool calls, errors) per trial.

`--gate` fails (exit 1) on any hard board-state failure **or** a statistically-significant
regression below baseline — that's the nightly/CI gate. `report.html` shows the
score-over-runs sparklines and current-vs-baseline per scenario.

> **Statistical power:** a handful of trials on 3 scenarios is a small sample — the t-test
> needs ≥2 trials and gets more reliable with more. Use `--trials 5+` for the nightly baseline;
> the per-scenario **floor** is the always-on backstop when there isn't enough data to test drift.

## Notes
- **Cost** is why Tier 2 isn't per-PR — each scenario × trial is a full agent run + judge call.
- **`history.jsonl` is committed** (the rolling baseline); `evals/results/` (reports) is gitignored.
- **`ToolCorrectnessMetric` is intentionally not used yet**: while the skills call the board
  via `Bash(curl)`, every tool call is just "Bash" — not meaningful to score. It becomes
  valuable **after an MCP migration** (typed `squad_*` tools); add it then.
- Judge resolution lives in `evals/judge.py::resolve_judge` (Anthropic key → Ollama → `claude` CLI).
- The regression statistics are unit-tested in `tests/test_eval_stats.py` (runs on every PR).
