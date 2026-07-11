# Observation & Consent (`user_steering` events)

Squad can observe **abstracted user steering** (corrections at decision gates) — opt-in only, never raw content. Opt-in/out lives in the **web app** (Settings → Observation & Consent); skills only read consent state. Off by default.

## The consent gate

```bash
observe() { python3 ../squad/scripts/observe.py "$@"; }
observe gate          # exit 0 = ON · 1 = OFF clean (kill-switch or not opted in) · 2 = OFF fail-closed (read error)
observe status        # effective on/off + deciding source (--json for the object)
observe dry-run | jq .  # the would-be payload; writes/sends nothing
```

- Local kill-switches (any set and not in `{"", "0", "false"}` → OFF, no network): `DO_NOT_TRACK`, `SQUAD_OBSERVE_DISABLED`, `CI`.
- Otherwise one `GET /consent`; ON iff the `behavioral_capture` row is opted-in. Fails closed on any error. The server independently 403s un-consented writes — the gate is an optimization + local override, not the sole guarantee.
- Resolve the gate once per run and reuse the exit code; a mid-run opt-out takes effect next run.

## Emitting (one event per correction occurrence)

A correction = a gate moment where the human redirects the run (rejects a plan, edits a spec, picks a non-recommended direction). Routine approvals emit **nothing**. Best-effort — guard with the cached gate and `|| true`; an emit failure never breaks the run. `squad-run`'s reject-gate emits are built into `pipeline.py advance` — no manual emit there.

```bash
[ "$OBSERVE_OK" = 0 ] && observe emit "$ID" --modality <m> --valence <v> --target <t> \
  --severity <s> --attributability <a> --comment "<abstracted pattern>" --correlation-id "$CID" || true
```

The five enums are derived from the gate context (trusted, never inferred from free text); bad values exit 2 before any network. The `--comment` is an abstracted pattern, never raw user words/code/paths — a deterministic leak filter drops any hit to the `(redacted)` sentinel (enums always emit).

### Per-gate enum mapping

| Skill | Gate | modality | valence | target | severity | attributability |
|-------|------|----------|---------|--------|----------|-----------------|
| squad-run | Critic reject @ plan_review / human plan reject | evaluative | negative | planning | moderate | violated_constraint |
| squad-run | Inspector reject @ impl_review | evaluative | negative | verification | moderate | violated_constraint |
| squad-run | Ranger fail @ test | evaluative | negative | verification | major | violated_constraint |
| squad-refine | "Edit more" (spec back to interview) | corrective | negative | scope | moderate | latent_preference |
| squad-refine | "Cancel" (spec discarded) | corrective | negative | scope | moderate | ambiguous |
| squad-refine | interview redirect | corrective | na | scope | trivial | latent_preference |
| squad-explore | non-recommended direction chosen | corrective | negative | planning | moderate | latent_preference |
| squad-explore | "Cancel" (report saved, no tasks) | corrective | negative | planning | trivial | ambiguous |
| squad-batch-run | post-Verify unexpected deviation | corrective | negative | scope | major | violated_constraint |

A skill MAY pick a closer enum from the canonical vocab when the gate context is plainly more specific (e.g. `target=git_strategy`). A reject-loop re-dispatch is a NEW occurrence (fresh `correlation_id`), not a duplicate.
