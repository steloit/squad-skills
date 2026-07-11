---
name: squad-refine
description: 'Refines a rough squad backlog task into a structured requirements spec (goal, requirements, acceptance criteria, edge cases) through a gap-ledger user interview, then saves the spec to the board. Use when a task''s requirements are vague or before running the pipeline on an unrefined card. Trigger phrases: "/squad-refine <ID>", "refine task <ID>", "flesh out / tighten the requirements for <ID>".'
license: MIT
---

> Read `../squad/shared.md` (bootstrap + levels + errors) and `../squad/principles.md` first.

```bash
api() { python3 ../squad/scripts/api.py "$@"; }
```

## `/squad-refine <ID>` — Refine Backlog Requirements

Target: tasks in `todo`. Any other non-terminal status → warn and confirm before proceeding.

### ⓪ Setup (once)

```bash
python3 ../squad/scripts/observe.py gate >/dev/null 2>&1; OBSERVE_OK=$?  # 0 = emit steering, else skip
CID=$(python3 -c 'import uuid;print(uuid.uuid4())')                      # correlation id for steering emits
MODEL_REFINER=$(python3 -c 'import json,os;c=json.load(open("../squad/models.json"));p=os.environ.get("SQUAD_MODEL_PROVIDER") or c.get("default_provider","claude");print(c["providers"][p]["refiner"])')
```

Every steering emit below is best-effort — guard with the cached gate and `|| true` (rubric: `../squad/references/observation.md`).

### ① Read the task + prior context (run the two reads in parallel)

```bash
api GET /task/$ID?fields=title,description,priority,level,tags,card_type
api GET /task/$ID/relationships
```

- Epic target (`card_type:"epic"`) → containers are not refinable: point the user at `.children` and stop.
- Terminal target (`done` — via the pipeline or `POST /task/$ID/complete`, incl. an epic rollup — or `cancelled`) → warn "reopen before refining" (`POST /task/$ID/reopen`) and stop.
- Prior context: for each `.blocked_by[].id`, fetch `api GET /task/$DEP?fields=title,implementation_notes,plan` (batch in parallel) and confirm the interfaces/schemas/file paths in the actual codebase → PRIOR_CONTEXT. Ask the user "Is there a prior task this builds on? (ID or 'none')" ONLY when `.blocked_by` is empty AND the description hints at a dependency.

### ② Show current state

Show the raw title + description as-is, plus a PRIOR_CONTEXT summary if any.

### ③ Gap analysis

Identify what is missing or vague across: WHAT, WHY, SCOPE, ACCEPTANCE, CONSTRAINTS, EDGE, DEPS.

### ④ Interview — the gap-ledger loop

The stop decision is owned by `../squad/scripts/refine_ledger.py`; obey its exit code — never self-judge "looks done".

1. Keep the ledger in a scratch file `$LEDGER`: a JSON list of `{"id","dimension","status","source"}` (dimension = the ③ vocab; status `OPEN|RESOLVED`; source `original` or `raised-by-answer-R#`). Seed it from ③. Each round, update the file but print only NEW or CHANGED rows — never the full list.
2. Select the highest-value OPEN gaps (answers that most change scope/acceptance/level), recency-first; ask 1–4 as ONE AskUserQuestion round. Preference / ownership / irreversible-scope forks → an option menu with a one-line rationale each; analysis-resolvable questions → research and present ONE recommendation with reasoning. Read `references/interview.md` before any research round (value-of-information gate, research depth, `SQUAD_REFINE_RESEARCH`).
3. Record answers → mark rows RESOLVED. Probe-scan every new answer: add ≥1 new OPEN row it raised, or state `No new gaps: <reason>`. Never re-ask a RESOLVED row; a genuinely clear card yields `No new gaps` in round 1 — do not manufacture filler.
4. Call the stop-gate once per round and branch on the exit code:

   ```bash
   python3 ../squad/scripts/refine_ledger.py verdict --ledger "@$LEDGER" \
     --round "$R" --last-probe <new_gaps|no_new_gaps> [--user-enough]
   # 0 STOP-CLEAN    → ⑤; residual non-core OPEN rows → unanswered qa entries
   # 1 CONTINUE      → next round (more rounds are owed — do not synthesize)
   # 2 STOP-DEGRADED → cap hit with WHAT/SCOPE/ACCEPTANCE still open: synthesize with the
   #                   residual as unanswered qa entries AND recommend /squad-explore or a card split
   # 3 STOP-ENOUGH   → user said "enough" (pass --user-enough): synthesize; residual → unanswered qa
   ```

If an answer REDIRECTS the task's direction (not a routine fill-in):

```bash
[ "$OBSERVE_OK" = 0 ] && python3 ../squad/scripts/observe.py emit "$ID" --modality corrective \
  --valence na --target scope --severity trivial --attributability latent_preference \
  --comment "redirected during the interview" --correlation-id "$CID" || true
```

### ⑤ Synthesize the spec

Build a structured spec OBJECT — the human `description` is never rewritten. Ground requirements in PRIOR_CONTEXT facts, not assumptions. Three authored fields (the server assigns `version`):

- `goal` — 1–2 sentences: what this task achieves and why.
- `requirements` — string[]: the complete, testable set; WHAT, not HOW. Soft prefixes: `REQ:` · `AC: WHEN … THE SYSTEM SHALL …` · `SCOPE(IN):` / `SCOPE(OUT):` · `CONSTRAINT:` · `EDGE:` · `SOURCE: <url>` (only when research materially informed the card — guards in `references/interview.md`).
- `qa` — `{question, answer}[]`: one entry per interview question (answer null if unanswered; residual OPEN ledger rows land here as open questions).

```json
{"goal": "Let admins invite members so teams can self-serve onboarding.",
 "requirements": ["REQ: An admin can send an invite by email from the members page.",
   "AC: WHEN an admin submits a valid email THE SYSTEM SHALL create an invite and email a signed link.",
   "SCOPE(OUT): bulk CSV invites are not included."],
 "qa": [{"question": "Email or OAuth invites?", "answer": "Email only for v1"}]}
```

### ⑥ Present + approve (one gate)

Paraphrase the resolved scope, then show the spec readably (goal, requirements, Q&A). Re-assess the level from the REFINED scope against `../squad/shared.md` → Pipeline levels + `../squad/principles.md` → Card-Split Criteria (the rubric is unchanged; only re-score). Then ask ONE AskUserQuestion:

- Question 1: **Approve & save** / **Edit more** (back to ④) / **Cancel** (discard).
- Only if the re-assessed level differs from the current level, add a second question in the SAME call: **Apply <new level>** / **Keep <current>** / **Adjust**. The level is never auto-applied; re-leveling happens only here, never in squad-run.

```bash
# "Edit more":
[ "$OBSERVE_OK" = 0 ] && python3 ../squad/scripts/observe.py emit "$ID" --modality corrective \
  --valence negative --target scope --severity moderate --attributability latent_preference \
  --comment "sent the spec back for edits" --correlation-id "$CID" || true
# "Cancel":
[ "$OBSERVE_OK" = 0 ] && python3 ../squad/scripts/observe.py emit "$ID" --modality corrective \
  --valence negative --target scope --severity moderate --attributability ambiguous \
  --comment "cancelled the refine" --correlation-id "$CID" || true
```

("Approve & save" emits nothing.)

### ⑦ Save (approved only)

```bash
CORRELATION_ID=$(python3 -c 'import uuid;print(uuid.uuid4())')  # one per save occasion; never cache/reuse across saves — a re-refine mints a fresh one
SPEC_JSON=$(jq -n --arg goal "$GOAL" --argjson reqs "$REQS_ARRAY" --argjson qa "$QA_ARRAY" \
  '{goal:$goal, requirements:$reqs, qa:$qa}')
VER=$(api GET /task/$ID?fields=version -q version)
api POST /task/$ID/spec --json "$(jq -n --argjson spec "$SPEC_JSON" --argjson ev "$VER" \
  --arg model "$MODEL_REFINER" --arg cid "$CORRELATION_ID" \
  '{spec:$spec, expected_version:$ev, actor:"Refiner", model:$model, correlation_id:$cid}')"
# 412 (concurrent edit) → re-read version and retry ONCE, KEEPING the same $CORRELATION_ID; still 412 → surface, stop.

# Level per the ⑥ choice; title/priority/tags only if the interview changed them (never description):
api PATCH /task/$ID --json "$(jq -n --argjson level "$LEVEL" '{level:$level}')"

# Dependency surfaced in the interview → declare DEP blocks ID (409 cycle is surfaced, no pre-check):
api POST /task/$DEP/relationships --json "$(jq -n --arg to "$ID" '{to:$to, type:"blocks"}')"

```

Finally append the Refiner note with the SAME id — `POST /task/$ID/activity`:

```json
{ "actor": "Refiner", "model": "<MODEL_REFINER>", "message": "Requirements refined. N questions across M rounds.", "correlation_id": "$CORRELATION_ID" }
```

### ⑧ Coach (background, after save)

Dispatch the Coach per `../squad/references/friction.md` with `skill_name=squad-refine`, `source_task=$ID`, `run_summary="squad-refine refined the requirements for task $ID."`, `trajectory` = the interview rounds + refined spec, `friction_signals` = any board-API friction (`none` if clean). Launch in the background — do not block completion; surface only if it filed friction.

### Interview tips

- "add login" → OAuth/email? Session/JWT? Which pages need guards? · "improve performance" → which page/API, current vs target latency, measurement method? · "fix the UI" → which component, what's wrong, reference design, responsive?
- Prefer concrete options over open-ended "what do you want?".
