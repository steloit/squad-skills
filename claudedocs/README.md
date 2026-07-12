# Design history — why Squad is built this way

This directory holds the **historical design records** of the Squad system:
proposals, research findings, and evaluation designs, preserved as they were
written. They explain how we arrived at the current architecture — they do
NOT describe the current implementation.

**Frozen-history rule:** these documents are never edited to match current
behavior. What the implementation does today lives in
**steloit/squad-engine** (`ARCHITECTURE.md` for mechanism, `PLAYBOOK.md` for
the operating contract, `claudedocs/` there for production evidence). Deltas
between these proposals and the implementation are tracked in the engine's
ARCHITECTURE.md → Architecture History.

| Document | What it is | Status |
|---|---|---|
| [squad-execution-architecture.md](./squad-execution-architecture.md) | The proposal that reversed the 6-role pipeline: single agent loop + thick deterministic harness + three-layer model (local engine / tracker integration / platform as run system-of-record). Includes the production-agent evidence base. | Historical — implemented 2026-07-12 as steloit/squad-engine, with evidence-driven deltas |
| [squad-vertical-slice-v0.md](./squad-vertical-slice-v0.md) | The v0 spec (spec-first, EARS) the engine implementation began from. | Historical — implemented; superseded by the engine's own docs |
| [eval-framework-redesign.md](./eval-framework-redesign.md) | Research: redesigning the skills evaluation framework (two-tier deterministic + behavioral). | Reference for EVALS.md's design |
