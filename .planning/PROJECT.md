# Lore Graph

## What This Is

A self-hosted knowledge graph + hybrid (graph + vector) retrieval pipeline for D&D / Forgotten Realms lore, exposed to a DM companion over MCP. It ingests sourcebooks (and later novels), builds a graph of people, organizations, goals, and **reified events** across in-world time, and answers session-time lore questions scoped to where and when the party is. Primary focus is **lore** — people, canonical events, goals, politics, the Blood War — not game mechanics.

## Core Value

A DM can ask a session-time lore question scoped to the party's place and time and get a **correct, provenance-attributed, explainable** answer — including "who could plausibly be behind this event" (the suspect-generator). The reason matters more than the score: every answer must trace to canonical edges with a source.

## Requirements

### Validated

<!-- Inferred from existing code via .planning/codebase/ map. Locked. -->

- ✓ **Controlled-vocabulary extraction model** — `NodeLabel`/`RelType` enums + `RELATION_DOMAINS` type matrix as the single source of truth for what may enter the graph — existing (`lore_graph/extraction.py`)
- ✓ **Pure, deterministic Validator** — closed-world edge validation: resolves refs, rejects dangling edges and type violations, routes ACCEPT/QUEUE/REJECT; unit-tested without network — existing (`lore_graph/extraction.py`, `tests/test_validation.py`)
- ✓ **LLM isolated behind one boundary** — `extract_with_llm` is the only network call; forced-tool-use Anthropic extraction returning a validated `ExtractionResult` — existing (`lore_graph/extraction.py`)
- ✓ **In-memory Gazetteer with fuzzy resolution** — alias/name → canonical id via rapidfuzz, with ambiguity flagging — existing (`lore_graph/extraction.py`)
- ✓ **Neo4j 5 schema starter** — constraints, conventions, hand-seed, and flagship query patterns (goal lookup, suspect-generator, spatiotemporal scope); applied via `make schema` — existing (`schema/lore_graph_schema.cypher`)
- ✓ **Local Neo4j + read-only MCP environment** — Docker Neo4j 5 (APOC + GDS), read-only MCP wiring for the companion, `.env` template, source manifest — existing (`docker-compose.yml`, `.mcp.json`, `data/manifest.json`)

### Active

<!-- This milestone: "First ingest" — PLAN.md Phases 1–2. Hypotheses until shipped. -->

- [ ] **Gazetteer bootstrap** — seed canonical entities from the hand-authored spine (nine Hells layers + archdukes, Council of Waterdeep factions) and the RoT/DiA appendix NPC lists, loaded from Neo4j at runtime so resolution works before parsing
- [ ] **Idempotent loader** — `loader.py` MERGE writer that stamps `source`/`canon`/edition + `valid_from`/`valid_to`, writes ACCEPT edges to the graph, and sends QUEUE verdicts to a review sink; re-running a source is a no-op (content-hash skip)
- [ ] **Markdown sourcebook parser** — `parsing.py` splits pre-converted Markdown sourcebooks by heading hierarchy into provenance-tagged chunks, exploiting **bold** entity mentions / *italic* items / tables / `>>` read-aloud blocks. (PDF parsing for scanned sourcebooks is deferred — see Out of Scope.)
- [ ] **End-to-end pipeline** — `pipeline.py` ties register → parse → resolve → extract → validate → load into one idempotent loop
- [ ] **All three Markdown sourcebooks ingested** — Lost Mine of Phandelver, Hoard of the Dragon Queen, and Rise of Tiamat all load through the pipeline end-to-end (each must-pass), with cross-book entities resolving to single canonical nodes; **Rise of Tiamat is the suspect-generator verification anchor**, with all extracted edges manually reviewable
- [ ] **Suspect-generator returns plausible results** — Query B over the ingested RoT data surfaces agents whose goals an event advances, with traceable reasons

### Out of Scope

<!-- Boundaries for THIS milestone. Reasoning prevents re-adding. -->

- **PDF parsing for scanned/older sourcebooks** — deferred; the first three target books are pre-converted Markdown. The two-column PyMuPDF4LLM→Marker/Docling triage pipeline comes in a later phase (e.g. for Descent into Avernus).
- **Hybrid vector retrieval + the live companion** — deferred to a later milestone (PLAN Phase 4); needs real graph data first, which this milestone produces
- **Descent into Avernus, review-queue UX, Blood War Conflict modeling** — deferred to PLAN Phase 3; prove the pipeline on one book before generalizing
- **Scale-out: prior editions + novels + contradiction tooling** — deferred to PLAN Phase 5; the canon-tier axis already exists so this needs no retrofit
- **Graph ML / GNNs** — deferred to PLAN Phase 6 (optional, post-scale); does not replace the explainable LLM+Cypher path
- **Game mechanics layer** — explicitly lower priority than lore; separate concern
- **Writing through MCP** — the companion is read-only by design; the Python bolt driver owns all writes

## Context

- **Brownfield project with a complete spec.** `CLAUDE.md` records settled architecture decisions; `PLAN.md` has the full 7-phase build plan. A codebase map exists at `.planning/codebase/` (STACK, ARCHITECTURE, STRUCTURE, CONVENTIONS, TESTING, INTEGRATIONS, CONCERNS).
- **Current state:** the extraction + validation layer is done and tested; `loader.py`, `parsing.py`, `pipeline.py` are documented stubs that raise `NotImplementedError`. This milestone implements them.
- **Known issues to address during this milestone** (from `.planning/codebase/CONCERNS.md`): the Gazetteer is in-memory only and never bootstrapped from Neo4j; `Gazetteer._norm` strips "the " mid-string; `RELATION_DOMAINS` lookup has no `KeyError` guard for a missing entry; `Item` node type lacks a uniqueness constraint in the Cypher schema; no content-hash idempotency exists yet.
- **Source material:** three pre-converted **Markdown** sourcebooks (Lost Mine of Phandelver, Hoard of the Dragon Queen, Rise of Tiamat) live in `data/` and are registered in `data/manifest.json` (5e, PUBLISHED, canon_rank 1, `format: markdown`). They are gitignored (`data/*.md` added) — copyrighted, never committed. Descent into Avernus is registered as `format: pdf, status: deferred` for a later PDF-parsing phase. HotDQ and RoT share a ~650-line "Tyranny of Dragons" front matter that content-hash chunking will dedupe.
- **Markdown structure (analyzed 2026-06-15):** clean `#`→`####` heading hierarchy (chunk boundaries + provenance path), **bold** named-entity mentions, *italic* item titles, pipe tables (carrying a `#$prompt_number...$#` template artifact to strip), and `>>…>>` read-aloud blocks. No monster stat blocks (lore-focused extraction).

## Constraints

- **Tech stack**: Python 3.11+, Pydantic v2, Neo4j 5 Community (native vector index — no separate vector DB), Anthropic API for extraction — settled in `CLAUDE.md`; do not relitigate without a stated reason.
- **Architecture**: Events are reified as nodes, never entity→entity verb edges; goals are first-class nodes; provenance + canon are stamped by the pipeline, never invented by the LLM — these are the load-bearing decisions the model hangs on.
- **Integrity**: closed-world edge validation; `MERGE` not `CREATE`; the `Validator` must stay pure (no I/O, no network) so it remains unit-testable.
- **Copyright**: evidence spans stay <25 words; never store long verbatim passages; never commit `data/sources/`.
- **Vocabulary discipline**: adding a `RelType` requires adding its `RELATION_DOMAINS` entry and the matching Cypher definition in the same change.

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| v1 milestone = "First ingest" (PLAN Phases 1–2), Rise of Tiamat end-to-end | Tightest vertical slice that proves the whole pipeline; everything downstream (companion, scale-out) needs real graph data first | — Pending |
| Reuse existing extraction/Validator as Validated foundation; build loader → gazetteer bootstrap → parser → pipeline | The hard, integrity-critical layer is already done and tested; remaining work is the write + ingest path | — Pending |
| Defer the companion/hybrid retrieval to a later milestone | Cannot meaningfully build or test retrieval without content in the graph | — Pending |
| Parse Markdown (not PDF) this milestone; defer PDF parsing | The three target books are pre-converted Markdown — structurally rich and free of the two-column reading-order problem; PDF triage is the highest-risk work and only needed for scanned/older books later | — Pending |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd:complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-06-15 after initialization*
