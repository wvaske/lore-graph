# STATE — Lore Graph

## Project Reference

- **Core value:** A DM gets a correct, provenance-attributed, *explainable* lore answer — including "who could plausibly be behind this event" — over ingested sourcebook data.
- **Milestone:** v1 "First Ingest" (PLAN Phases 1–2) — three Markdown sourcebooks end-to-end; Rise of Tiamat is the suspect-generator anchor.
- **Current focus:** Phase 1 — Graph-Write Foundation (the integrity/critical path).

## Current Position

- **Phase:** 1 — Graph-Write Foundation
- **Plan:** Not yet planned (`/gsd:plan-phase 1`)
- **Status:** Roadmap created; awaiting phase planning.
- **Progress:** [..........] 0/3 phases complete

## Performance Metrics

| Metric | Value |
|--------|-------|
| Phases complete | 0/3 |
| Requirements mapped | 23/23 |
| Requirements delivered | 0/23 |

## Accumulated Context

### Decisions
- v1 = "First Ingest"; build loader → gazetteer bootstrap → parser → pipeline (graph-write track is the critical path; parser is parallelizable).
- Parse Markdown only this milestone; PDF parsing (two-column triage) deferred to v2 / PLAN Phase 3.
- `bootstrap_gazetteer` lives in `loader.py` (the only other Neo4j-driver holder); `extraction.py` stays free of the `neo4j` import to keep the Validator pure.
- Three phases at coarse granularity, dependency-driven per research build order.

### Open questions (resolve during planning)
- Time-bounded MERGE key: does a state-fact relationship's merge identity include `valid_from`? (Phase 1 loader design.)
- Origin of `valid_from`/`valid_to` DR-year values (LLM attribute vs manual seed). (Phase 1/3 decision.)
- Concrete "plausible suspects" acceptance checklist for ING-04. (Phase 3.)

### Todos
- Run `/gsd:plan-phase 1` to decompose Phase 1 into executable plans.

### Blockers
- None.

## Session Continuity

- **Last action:** Roadmap + STATE created from PROJECT/REQUIREMENTS/research (2026-06-15).
- **Next action:** Plan Phase 1.
- **Files:** `.planning/ROADMAP.md`, `.planning/REQUIREMENTS.md`, `.planning/PROJECT.md`, `.planning/research/*`.

---
*Last updated: 2026-06-15 after roadmap creation*
