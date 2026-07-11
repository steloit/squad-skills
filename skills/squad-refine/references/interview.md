# Interview Research & Sources

Load this before any research-flavored interview round (a design/architecture question, a "what do you suggest", a best-practices lookup) and before emitting any `SOURCE:` row.

## Value of information (ask vs proceed)

- Ask a question ONLY when its answer would materially change what gets built. Otherwise proceed and note the assumption — never ask filler.
- Classify each candidate question:
  - **Preference / ownership / irreversible-scope fork** → AskUserQuestion menu, each option carrying a one-line rationale (the user owns this call).
  - **Analysis-resolvable** (best practice / architecture / performance / library choice) → research it and present ONE recommendation with reasoning — not a menu.

## Mode detection

Switch to research-then-recommend-ONE for the rest of the session when the user: re-sends a directive verbatim, asks "what do you suggest", says "do web research / best practices", grants freedom to re-architect, or rejects an option set.

## Proposal, not commitment

Every recommendation ships with its reasoning and a cheap override (reject / edit / redirect). Never present it as locked.

## Value-gated research

- Research fires only when the card is design / architecture / re-architecture / high-uncertainty (best practices materially shape the outcome), or the user explicitly asks. A clear or trivial card gets no research; a research keyword on a trivial card does not trigger a sweep — the gate is value, not keyword-match.
- Depth scales with stakes: one targeted best-practices check for a moderate card; a deeper sweep only for a genuine architecture decision — never an always-on fan-out.
- Aggressiveness: `SQUAD_REFINE_RESEARCH = off | auto-by-value | always` (default `auto-by-value`); resolve env `SQUAD_REFINE_RESEARCH` over committed `.squadrc` `SQUAD_REFINE_RESEARCH=`. `off` disables research entirely; `always` researches every design-shaped question.

## Sources convention (`SOURCE:` rows)

- Emit `SOURCE: <url>` entries in `requirements[]` only when external research materially informed the card; a non-research card carries none.
- Cite only sources actually consulted THIS run, as real, verifiable URLs — never fabricate a citation or a plausible-looking paper id.
- A codebase fact cites `file:line`, not a URL.
- The entries live in `requirements[]` (the spec has no free-markdown section); the card view renders them as the Sources block.
