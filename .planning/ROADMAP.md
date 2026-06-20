# Roadmap — Lore Graph

**Milestone:** v1 "First Ingest" (PLAN Phases 1–2)
**Core value:** A DM gets a correct, provenance-attributed, *explainable* lore answer — including "who could plausibly be behind this event" — over data ingested from the three registered Markdown sourcebooks, with Rise of Tiamat as the suspect-generator anchor.
**Granularity:** coarse
**Created:** 2026-06-15

This milestone wires the already-trusted extraction + validation layer into a write/ingest path: a hardened schema, a gazetteer bootstrapped from Neo4j, an idempotent loader, a Markdown parser, and an orchestration pipeline — then ingests all three books and verifies the suspect-generator over Rise of Tiamat.

## Phases

- [ ] **Phase 1: Graph-Write Foundation** - Hardened schema + gazetteer bootstrap + idempotent provenance-stamping loader, proven by an extraction→Neo4j→query round-trip.
- [ ] **Phase 2: Markdown Sourcebook Parser** - Heading-hierarchy split into provenance-tagged, structure-aware, content-hashed chunks with bold/italic entity-mention hints.
- [ ] **Phase 3: Pipeline Orchestration & End-to-End Ingest** - Full idempotent ingest loop over all three books; suspect-generator returns plausible, traceable results over Rise of Tiamat.
- [ ] **Phase 4: Hybrid Retrieval + Companion** - Embed node text with bge-m3 into Neo4j's native vector index (1024-dim, cosine); retrieval = vector seed → graph walk, exposed to the DM companion over the read-only MCP server. *(Maps to PLAN Phase 4; extends beyond the v1 "First Ingest" milestone — needs real graph content from Phases 1–3 first.)*

## Phase Details

### Phase 1: Graph-Write Foundation
**Goal**: The graph-write/integrity layer is trustworthy and idempotent — the schema cannot silently duplicate, the gazetteer is hydrated from Neo4j so closed-world validation works, and every write is provenance-stamped and replayable.
**Depends on**: Nothing (first phase; builds on the existing Validated extraction/Validator layer)
**Requirements**: SCH-01, SCH-02, SCH-03, RES-01, RES-02, RES-03, LOAD-01, LOAD-02, LOAD-03, LOAD-04, LOAD-05
**Success Criteria** (what must be TRUE):
  1. Feeding existing `ValidatedEdge` output through `load()` MERGEs ACCEPT edges into Neo4j, and an integration test retrieves them via flagship Query A (goal lookup) and Query B (suspect-generator) — the highest-priority test gap is closed.
  2. Running the same batch twice produces identical node and edge counts (ingest-twice-equals-once), backed by content-hash `:Chunk` skip and stable MERGE keys with volatile props set only in `ON CREATE/ON MATCH SET`.
  3. `bootstrap_gazetteer(driver)` hydrates a non-empty in-memory gazetteer from the seeded spine + appendix NPC lists (mapping `:Power:Agent` → the specific `NodeLabel`); `gaz.resolve("Severin")` hits the canonical id, and the pipeline hard-errors on an empty gazetteer against a populated graph. `extraction.py` still imports no `neo4j`.
  4. Every written node/edge carries `source`/`canon`/`edition`/`canon_rank` from the pipeline-supplied `SourceContext`; the loader refuses any edge lacking provenance, and state-fact edges carry `valid_from`/`valid_to` with a merge key that does not overwrite an existing validity interval.
  5. A QUEUE verdict lands as a replayable `:ReviewItem` node carrying the edge + reasons; a REJECT is logged with reasons and never written; an `Item` MERGE cannot duplicate (uniqueness constraint added) and an unknown rel type REJECTs one edge without aborting the batch.
**Plans**: TBD

### Phase 2: Markdown Sourcebook Parser
**Goal**: A pre-converted Markdown sourcebook becomes a list of provenance-tagged, structure-aware, content-hashed `Chunk` objects — surfacing markup the deferred PDF path cannot — entirely as a pure text transform independent of the graph.
**Depends on**: Nothing (independent text track; parallelizable with Phase 1)
**Requirements**: PARSE-01, PARSE-02, PARSE-03, PARSE-04
**Success Criteria** (what must be TRUE):
  1. `parse(path, "markdown")` splits a sourcebook by `#`→`####` heading hierarchy into `Chunk` objects carrying `text`, `source`, `section` (full heading path), `locator`, and `content_hash`; `pdf`/`novel`/`wiki` profiles raise `NotImplementedError`.
  2. Tables (with `#$prompt_number...$#` template artifacts stripped), `>>…>>` read-aloud blocks, and `***Label.***` lines are preserved into chunks without storing oversized verbatim spans (evidence stays <25 words downstream).
  3. Inline **bold** spans and *italic* item titles are surfaced per chunk as entity-mention candidates available to the pipeline as gazetteer-hint inputs.
  4. Re-parsing an unchanged source is served from a content-hash cache (no re-parse), and the shared HotDQ/RoT "Tyranny of Dragons" front matter deduplicates to a single set of chunks by content-hash.
**Plans**: TBD

### Phase 3: Pipeline Orchestration & End-to-End Ingest
**Goal**: The full register→parse→resolve→extract→validate→load loop runs idempotently over all three Markdown sourcebooks, and the suspect-generator returns plausible, traceable results over real Rise of Tiamat data.
**Depends on**: Phase 1, Phase 2
**Requirements**: PIPE-01, PIPE-02, PIPE-03, ING-01, ING-02, ING-03, ING-04, ING-05
**Success Criteria** (what must be TRUE):
  1. `ingest(source_id)` runs the full idempotent loop reading the manifest row and writing back status `pending → parsed → loaded`; it mints exactly one `SourceContext` per source, threads it into `validate_batch` and `load`, and passes resolved canonical names as `gazetteer_hints` into extraction.
  2. All three registered Markdown sourcebooks ingest end-to-end with events/NPCs/goals/factions landing in the graph with provenance and canon tier; the shared "Tyranny of Dragons" front matter deduplicates by content-hash rather than producing duplicate edges, and cross-book entities (Cult of the Dragon, Severin, Tiamat) resolve to single canonical nodes.
  3. A `max_tokens` truncation splits the chunk and re-extracts (idempotency dedupes the overlap), and a missing `ANTHROPIC_API_KEY` is caught before any LLM call.
  4. All extracted edges from each book are manually reviewable (the human-review backstop), an integration test confirms a validated edge survives the MERGE round-trip and is retrievable by flagship queries (A, B, spatiotemporal), and the suspect-generator (Query B) over Rise of Tiamat surfaces a known instigator with a traceable motive (aligned goal) and means (command/capability path) per a defined acceptance checklist.
**Plans**: TBD

### Phase 4: Hybrid Retrieval + Companion
**Goal**: A DM companion answers a session-time lore question by combining a vector seed over node embeddings with a graph walk — scoped to party time/place and respecting canon tier — using the already-deployed bge-m3 embedding endpoint and Neo4j's native vector index.
**Depends on**: Phase 3 (retrieval cannot be built or tuned without real graph content; this milestone produces it)
**Requirements**: TBD (assigned at discuss/plan time)
**Locked decisions** (settled during lab infra deployment, 2026-06-20 — do not relitigate without a stated reason):
  - **Embedding model**: BAAI **bge-m3** — 1024-dim, multilingual, 8192-token context. Chosen over nomic-embed / bge-large for multilingual + long-document headroom.
  - **Endpoint (already deployed)**: dedicated always-on `llama-server --embeddings` instance at **`http://gb10.vaske.us:8090/v1/embeddings`** (model field `bge-m3`), kept separate from the chat router so it is never LRU-evicted. CLS pooling; output is **L2-normalized**; **no instruction prefixes** needed (unlike bge-en).
  - **Vector store**: Neo4j 5 **native vector index** (no separate vector DB) — `vector.dimensions: 1024`, `vector.similarity_function: 'cosine'` (vectors arrive pre-normalized).
  - **Retrieval pattern**: vector seed → graph traversal. The same embeddings also back the Gazetteer `embedding_resolve` hook for hard-case entity resolution.
**Success Criteria** (what must be TRUE):
  1. A Neo4j vector index over the chosen node labels' `embedding` property (1024-dim, cosine) is added to `schema/` and applied by `make schema`.
  2. The pipeline `embed` step (pipeline step 8) populates node embeddings from the bge-m3 endpoint and is idempotent — unchanged nodes (by content-hash) are not re-embedded; writes go through the bolt driver, never MCP.
  3. The Gazetteer `embedding_resolve(mention)` hook resolves a hard case fuzzy matching misses (e.g. "the cult leader" → `Severin Silrajin`) and routes genuine near-ties to review.
  4. A retrieval call combines a vector seed with a graph walk and returns provenance-attributed, canon-tier-respecting results scoped to party time/place, exposed to the companion over the **read-only** Neo4j MCP server.
**Plans**: TBD

## Progress

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Graph-Write Foundation | 0/TBD | Not started | - |
| 2. Markdown Sourcebook Parser | 0/TBD | Not started | - |
| 3. Pipeline Orchestration & End-to-End Ingest | 0/TBD | Not started | - |
| 4. Hybrid Retrieval + Companion | 0/TBD | Planned (after v1) | - |

---
*Created: 2026-06-15 · Milestone: v1 "First Ingest" · Granularity: coarse*
