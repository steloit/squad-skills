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
**`squad-eval`** board project, then scores each scenario two ways:
1. **Deterministic board ground truth** — after the run, query the board: was the task
   created / moved / refined as expected? (objective, not fuzzy)
2. **GEval rubric** — LLM-as-judge on the response quality (`evals/scenarios.yaml`).

```bash
export ANTHROPIC_API_KEY=…          # agent + judge
export SQUAD_AUTH_TOKEN=…           # board (or ~/.squad/auth)
# one-time: ensure the test project exists →  cd anywhere && /squad-init squad-eval
pip install -r evals/requirements.txt
python -m pytest evals/ -q
```
Without the CLI / key / token it **skips cleanly** (so a secret-less CI stays green).
Scenarios self-clean — created tasks carry a `[[eval]]` title marker and are deleted after.

### Add a scenario
Append to `evals/scenarios.yaml`: a `prompt`, optional `setup.create_task`, deterministic
`expect.board` / `expect.task_description_contains_any`, and an `expect.rubric`. Keep the
golden set small and **hard** — a 100% pass rate usually means the eval is too easy.

## "Did this change make it better?" — before/after
Run Tier 2 on the old skills, then the new, and compare:
- **board-state pass rate** (the objective signal), **GEval scores**, agent **errors/retries**, **turns/tokens**.
Better = same-or-higher pass rate + scores, fewer errors. Tier 1 must stay 100% green (it's
deterministic — any drop is a real regression).

## Notes
- **Cost** is why Tier 2 isn't per-PR — each scenario is a full agent run + judge calls.
- **`ToolCorrectnessMetric` is intentionally not used yet**: while the skills call the board
  via `Bash(curl)`, every tool call is just "Bash" — not meaningful to score. It becomes
  valuable **after an MCP migration** (typed `squad_*` tools); add it then.
- Judge defaults to an Anthropic model when `ANTHROPIC_API_KEY` is set; override in
  `evals/test_behavioral.py::_judge`.
