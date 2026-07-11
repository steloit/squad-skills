# Task Relationships & Epics

Tasks relate through two typed edges stored on the board (never encoded in text or tags — the `Depends on: #ID` text and `epic:` tag conventions are retired; `phase:` tags remain valid free labels):

- **`blocks`** — dependency DAG. `A blocks B` ⟺ B is `blocked_by` A. B is ready only when A's status is terminal (`done` or `cancelled`).
- **`parent`** — single-parent hierarchy. A child's `parent` is its containing **epic** card.

An **epic** (`card_type:"epic"`) is a container: excluded from the pipeline (`squad-run` refuses it, `squad-batch-run` skips it), carries derived `epic_status` + `children_progress`. When all children reach a terminal status the epic's stored status auto-rolls-up to done/cancelled (`completed_via:"rollup"`) — so an epic used as a blocker satisfies the readiness gate automatically. The derived per-epic `complete` boolean in the board's `epics` aggregate is display-only; readiness is always the **stored status**.

## Endpoints

```bash
api POST /task/$ID/relationships --json "$(jq -n --arg to "$OTHER" '{to: $to, type: "blocks"}')"   # or type: "parent"
#   400 self-edge/second parent · 404 task · 409 cycle (server enforces acyclicity — never pre-validate)
api GET /task/$ID/relationships
#   → {blocked_by: [{id,title,status}], blocking: [...], parent: {...}|null, children: [...], children_progress: {done,total}}
api DELETE /task/$ID/relationships/$REL_ID
```

`to` is an opaque `<KEY>-<seq>` display-id string — bind with `--arg`, never `--argjson`.

Declaring edges: `DEP blocks ID` means POST on `/task/$DEP/relationships` with `to=$ID`. Attaching a child to an epic: POST on `/task/$CHILD/relationships` with `to=$EPIC, type=parent`.

The board response's `epics` aggregate (each with `children_progress`) is what summaries group by — never tag parsing.
