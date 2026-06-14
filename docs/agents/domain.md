# Domain Docs

How the engineering skills should consume this repo's domain documentation when exploring the codebase.

This is a **single-context** repo (one Python/FastAPI service).

## Before exploring, read these

- **`CONTEXT.md`** at the repo root (domain glossary — may not exist yet).
- **`docs/architecture/decisions/`** — this repo's ADR directory. Read ADRs that touch the area you're about to work in (e.g. `0001-nanoclaw-ephemeral-not-persistent.md`, `0002-rejecting-nanoclaw-for-simpler-agent.md`).

If any of these files don't exist, **proceed silently**. Don't flag their absence; don't suggest creating them upfront. The producer skill (`/grill-with-docs`) creates `CONTEXT.md` lazily when terms or decisions actually get resolved.

> Note: the upstream skills default to `docs/adr/`. This repo uses `docs/architecture/decisions/` instead — always read/write ADRs there.

## File structure

Single-context repo:

```
/
├── CONTEXT.md                         ← domain glossary (created lazily)
├── docs/architecture/decisions/       ← ADRs
│   ├── 0001-nanoclaw-ephemeral-not-persistent.md
│   ├── 0002-rejecting-nanoclaw-for-simpler-agent.md
│   └── README.md
└── ...
```

## Use the glossary's vocabulary

When your output names a domain concept (in an issue title, a refactor proposal, a hypothesis, a test name), use the term as defined in `CONTEXT.md`. Don't drift to synonyms the glossary explicitly avoids.

If the concept you need isn't in the glossary yet, that's a signal — either you're inventing language the project doesn't use (reconsider) or there's a real gap (note it for `/grill-with-docs`).

## Flag ADR conflicts

If your output contradicts an existing ADR, surface it explicitly rather than silently overriding:

> _Contradicts ADR-0002 (rejecting NanoClaw for simpler agent) — but worth reopening because…_
