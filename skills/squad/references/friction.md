# Squad Friction Reports, Run Audit & Coach

Friction **with Squad itself** (the skills/board/orchestrator you work *with*, not the repo you work *on*) is reported, not fixed. Never leave the actual task to chase it; the worked project's own bugs go on that project's board, not here.

## Friction report = a card on project `squad`

A `todo` card, `priority=low`, tags `["friction", "triage"]`, description with these labeled fields:

| Field | Required | Values |
|-------|----------|--------|
| `area` | yes | `skill` \| `template` \| `orchestrator` \| `board-api` \| `board-ui` \| `agent-ergonomics` \| `other` |
| `severity` | yes | `low` \| `med` \| `high` |
| `evidence` | **yes** | what you were doing + concrete friction with `file:line` or a repro. **No concrete evidence → no report.** |
| `suggestion` | no | possible fix/direction |
| `source_project` / `source_task` | yes | the project + task you were working when you hit it |

Guardrails: max **3** reports per skill invocation (one squad-run pass = one invocation across all agents). Dedup before filing:

```bash
# Open friction cards (non-terminal buckets only), id + title:
api GET /board?project=squad&summary=true \
  | jq -r '[.todo, .plan, .plan_review, .impl, .impl_review, .test] | add // [] | .[]
           | select((.tags // "") | test("friction")) | "\(.id)\t\(.title)"'
# A normalized-title + area match → skip (or append evidence to that card); never re-file.
```

File with the standard create endpoint, forced to project squad:

```bash
BODY=$(jq -n --arg area "..." --arg severity "..." --arg title "..." --arg evidence "..." \
  --arg suggestion "..." --arg source_project "..." --arg source_task "..." \
  '{title: $title, project: "squad", priority: "low", level: 1, tags: ["friction", "triage"],
    description: ("**area:** " + $area + "\n**severity:** " + $severity + "\n**evidence:** " + $evidence
      + "\n**suggestion:** " + $suggestion + "\n**source_project:** " + $source_project
      + "\n**source_task:** " + $source_task)}')
api POST /task?project=squad --json "$BODY"
```

## Run audit (append-only, every run — clean and friction)

```
POST /run-audit?project=squad  → {"id": <int>}
```

Body: `source_project`* · `skill`* · `source_task` · `level` · `provider` · `overall_status`* (`clean|friction`) · `rubric`* (JSON array — the 6 scored rows) · `signals`* (JSON array/object, never a bare string) · `filed_card_ids`* (JSON array, `[]` on clean). Bare-text JSON fields → 400. Best-effort: a failed POST is logged and the run continues.

Read-back: `GET /run-audits?project=&since=&status=&skill=` → `{"audits": [...]}`.

## Coach dispatch (agent-run skills only, at run close)

`squad-run`, `squad-explore`, `squad-batch-run`, `squad-refine`, `squad-gen-wiki` dispatch the **Coach** once per run — an independent fresh-context judge of the run trajectory that POSTs the run audit and files material friction (default-zero bar; owns the N=3 budget). CRUD/setup skills never dispatch it.

**Launch it in the background and do not block the run's completion on it.** Surface it to the user only when it filed friction (one line: `🔍 N friction report(s) filed for triage`).

```bash
# Render the Coach prompt (models resolved from models.json by the script):
COACH_PROMPT=$(python3 ../squad/scripts/render_agent_prompt.py \
  --template ../squad/templates/coach.md --models ../squad/models.json \
  --set PROJECT="$PROJECT" --set skill_name="<skill>" --set source_project="$PROJECT" \
  --set source_task="$TASK" --set run_summary="$SUMMARY" \
  --set trajectory="$TRAJECTORY" --set friction_signals="$SIGNALS" \
  --set TIMESTAMP="$(date -u +%Y-%m-%dT%H:%M:%SZ)")
```

Capture free-text inputs (`trajectory`, `run_summary`, `friction_signals`) via single-quoted heredocs (`VAR=$(cat <<'EOF' … EOF)`) — never plain double-quoted assignments. Launch via the Task tool in the background: claude → `Task(subagent_type="general-purpose", model=<coach model>, prompt=$COACH_PROMPT)`; codex adds `model_reasoning_effort`.
