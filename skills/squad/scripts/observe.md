# observe.py — observation-consent gate

A zero-dependency, **read-only**, **fail-closed** helper that decides whether
squad-run may emit a `user_steering` observation event. A privacy gate is a
deterministic, auditable, low-freedom operation, so it lives in code (not model
judgement) and squad-run calls it unconditionally. python3 stdlib-only — installs
anywhere python3 runs. It **never** handles the token: it subprocesses the sibling
`api.py` for one `GET /consent`, and `api.py` owns auth/transport/JSON.

This helper only **reads** consent — there is **no** grant/withdraw/disclosure. The
human opt-in/opt-out act lives in the **web app** (Settings → Observation & Consent).

## Invocation

~~~
observe.py gate    [--json]
observe.py status  [--json]
observe.py dry-run [--json]
~~~

- **`gate`** — the observation gate-seam. Resolve order: local env kill-switches FIRST
  (`DO_NOT_TRACK` / `SQUAD_OBSERVE_DISABLED` / `CI` → OFF, **no network**), else one
  `GET /consent` → ON iff the `behavioral_capture` row is `opted_in`. `--json` emits
  the decision object to stdout; squad-run branches on the **exit code** alone.
- **`status`** — read-only. Same resolution, prints the effective on/off, the
  deciding `source`, the `policy_version` on record, and the web-app manage pointer.
  Issues only a `GET`; never mutates.
- **`dry-run`** — prints the **abstracted** `user_steering` payload that WOULD be
  recorded to **stdout** (pipeable to `jq`) + a `# DRY RUN` banner to **stderr**.
  ZERO network/writes; works in any consent state (inspection, not capture).

## Env kill-switches (a hard off)

Any of `DO_NOT_TRACK`, `SQUAD_OBSERVE_DISABLED`, `CI`, set and not in
`{"", "0", "false"}`, resolves the gate **OFF with no network call** — overriding
even an active server grant (env-precedes-config, the GitHub-CLI rule).

## Exit codes (gate / status)

| Code | Meaning |
|------|---------|
| 0 | observation **ON** — opted-in for `behavioral_capture`, no local override |
| 1 | **OFF**, clean — an env kill-switch is set, OR not opted-in (no row / `false`) |
| 2 | **OFF**, fail-closed — a consent-read error (api.py non-zero or non-JSON stdout) |

`dry-run` always exits 0. All non-zero = OFF (the "0=on, non-zero=off" contract);
the 1-vs-2 split is diagnostic only. So `if observe.py gate; then …; fi` works.

## Wire contract consumed (read-only)

`GET /consent` →
`{ "consent": [ { "purpose": "behavioral_capture", "opted_in": <bool>,
"policy_version": <str|null>, … } ], "events": [ … ] }`. The gate reads ONLY
`purpose` / `opted_in` / `policy_version` from the `behavioral_capture` row;
every other field is ignored. No `behavioral_capture` row ⇒ never granted ⇒ OFF.

## Once-per-run cadence

`observe.py` is stateless — one `GET` per `gate` call. The run-scoped cache is the
**caller's** job: squad-run resolves `gate` ONCE at run start and reuses the cached
exit code for every per-correction emit. The server independently 403s un-consented
writes, so the gate is an **optimization + the local override**, not the sole
guarantee. The full contract also lives in `observe.py --help`.

A live read-only round-trip (`observe_smoke.py`, `SQUAD_OBSERVE_LIVE=1`, needs a
locally-booted consent branch — production `GET /consent` is not deployed)
proves the gate reflects the real server state without mutating it.
