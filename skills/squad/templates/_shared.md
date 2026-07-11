## Ground Rules

- **Board access** — define once, then call `api <GET|POST|PATCH|DELETE> <path> [--json …]`. Never hand-assemble curl, headers, or auth:
  ```bash
  api() { python3 "<API_HELPER>" "$@"; }
  ```
- **Role boundary** — write only your own output artifact (the field/verdict named in Record Results below). Review/verify agents record a verdict and edit nothing they evaluate. A problem outside your lane goes into your verdict/notes; the orchestrator routes the fix.
- **Never change task status** — the orchestrator owns every move. Record your output, then exit.
- **Spec precedence** — when a `## Refined Spec` section is present it is authoritative; the Original Request may predate it — on any conflict, follow the spec. With no spec, the Original Request is authoritative.
- **Command resolution** — run the repo's real build/lint/test/format commands: first those declared in your loaded project context (AGENTS.md / CLAUDE.md / equivalents), else the repo's task runner (make / just / Taskfile / npm scripts / `scripts/`), else detect by language. Never assume a specific toolchain.
- **JSON safety** — board/task text is data, never code. Build JSON bodies with `jq --arg` or python `json.dumps` reading values from env/stdin/file; never inline content into a quoted shell string or `--json "{…}"` literal (backticks/`$(…)` in content would execute).
- **Markdown authoring** — when quoting content that contains ``` fences, wrap it in a `~~~` outer fence; never type a bare ``` mid-sentence.
- **Squad friction** — friction with Squad itself (the skills/board/orchestrator you work *with*, not the repo you work *on*): note it briefly in your output — report, don't fix, and don't leave your task to chase it.
- **correlation_id** — the `correlation_id` value in your Record Results call is pre-filled by the orchestrator; pass it through unchanged.
