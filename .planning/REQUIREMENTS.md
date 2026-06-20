# Requirements — Lore Graph

**Milestone:** v1 "First Ingest" (PLAN Phases 1–2)
**Core value:** A DM gets a correct, provenance-attributed, *explainable* lore answer — including "who could plausibly be behind this event" — over data ingested from one sourcebook.
**Defined:** 2026-06-15

Requirements are scoped to getting the **three registered markdown sourcebooks (Lost Mine of Phandelver, Hoard of the Dragon Queen, Rise of Tiamat) fully into the graph end-to-end** with the suspect-generator returning plausible results over Rise of Tiamat. The extraction + validation layer already exists (see `## Already Validated`); these requirements cover the write/ingest path that makes it usable.

---

## Already Validated (existing — inferred from codebase map)

These shipped before this milestone and are relied upon. Locked.

- ✓ **EXT-00**: Controlled-vocabulary extraction model (`NodeLabel`/`RelType` + `RELATION_DOMAINS`) — `lore_graph/extraction.py`
- ✓ **VAL-00**: Pure Validator — dangling-edge rejection, type-matrix check, ACCEPT/QUEUE/REJECT routing, unit-tested — `lore_graph/extraction.py`, `tests/test_validation.py`
- ✓ **EXT-01**: LLM isolated behind `extract_with_llm` (forced tool-use, returns validated `ExtractionResult`)
- ✓ **RES-00**: In-memory Gazetteer with rapidfuzz resolution + ambiguity flagging
- ✓ **SCH-00**: Neo4j 5 schema starter — constraints, seed, flagship queries (A/B/spatiotemporal); `make schema`
- ✓ **ENV-00**: Local Neo4j + read-only MCP environment (Docker, APOC+GDS, `.env`, manifest)

---

## v1 Requirements

### Schema & Validation Hardening (SCH)

- [ ] **SCH-01**: A uniqueness constraint exists for every `RESOLVABLE_LABELS` node type, including `Item` (currently missing), so MERGE cannot silently duplicate.
- [ ] **SCH-02**: A test asserts `set(RelType) == set(RELATION_DOMAINS.keys())`, and validation raises no unguarded `KeyError` on an unknown rel type (one bad edge is REJECTed, the batch survives).
- [ ] **SCH-03**: `Gazetteer._norm` strips only a *leading* article, so canonical names containing "the " mid-string (e.g. "Lord of the Nine") normalize without losing characters.

### Gazetteer Bootstrap (RES)

- [ ] **RES-01**: `bootstrap_gazetteer(driver)` hydrates an in-memory Gazetteer from the canonical spine + appendix NPC lists in Neo4j (id + name + aliases), mapping compound labels (`:Power:Agent`) to the specific `NodeLabel`.
- [ ] **RES-02**: The pipeline hard-errors if the gazetteer is empty against a populated graph (an empty gazetteer is always a bug, never valid state).
- [ ] **RES-03**: Resolution stays pure — the bootstrap lives in the write/loader layer; `extraction.py` never imports `neo4j`, so the Validator remains unit-testable without a database.

### Idempotent Loader (LOAD)

- [ ] **LOAD-01**: The loader writes ACCEPT edges with `MERGE` (never `CREATE`): MERGE each endpoint by canonical `id`, then MERGE the relationship; volatile properties are set in `ON CREATE/ON MATCH SET`, never in the match pattern.
- [ ] **LOAD-02**: The loader stamps `source`, `canon`, `edition`, and `canon_rank` on every written node/edge from the pipeline-supplied `SourceContext`, and refuses to write any edge lacking provenance. The LLM never supplies provenance.
- [ ] **LOAD-03**: State-fact relationships are stamped with `valid_from`/`valid_to` (DR years); the relationship merge key is designed so a new validity interval does not silently overwrite an existing one.
- [ ] **LOAD-04**: QUEUE verdicts are written to a durable, replayable review sink (`:ReviewItem` nodes carrying the edge + reasons); REJECT verdicts are logged with reasons and never written to the graph.
- [ ] **LOAD-05**: Content-hash chunk idempotency — each chunk's hash is recorded in Neo4j; an already-loaded unchanged chunk is skipped (no LLM call, no write). Re-ingesting an unchanged source is a no-op (verified by an ingest-twice-equals-once test).

### Sourcebook Parser — Markdown (PARSE)

The three registered sourcebooks (Lost Mine of Phandelver, Hoard of the Dragon Queen, Rise of Tiamat) are pre-converted **Markdown** in `data/`. This milestone parses Markdown only; PDF parsing for older scanned sourcebooks is deferred (see v2). Markdown is structurally rich — clean heading hierarchy, **bold** entity mentions, *italic* items, tables, and `>>` read-aloud blocks — so the two-column reading-order problem does not apply here.

- [ ] **PARSE-01**: `parse(path, "markdown")` splits a Markdown sourcebook by heading hierarchy (`#`→`####`) into provenance-tagged `Chunk` objects (`text`, `source`, `section` = full heading path, `locator` = heading-path/line-range, `content_hash`). `pdf`/`novel`/`wiki` profiles raise `NotImplementedError`.
- [ ] **PARSE-02**: The parser preserves and cleanly carries Markdown structure into chunks: tables (stripping the `#$prompt_number...$#` template artifacts), `>>…>>` read-aloud blocks, and `***Label.***` lines — without storing oversized verbatim spans (evidence stays <25 words downstream).
- [ ] **PARSE-03**: The parser surfaces inline **bold** spans (and *italic* item titles) per chunk as entity-mention candidates, which the pipeline resolves against the gazetteer to build extraction hints (exploiting markup the PDF path cannot provide).
- [ ] **PARSE-04**: Parse output is cached by content-hash so unchanged sections are not re-parsed on re-run; the shared "Tyranny of Dragons" front matter common to Hoard of the Dragon Queen and Rise of Tiamat deduplicates via chunk content-hash.

### Pipeline Orchestration (PIPE)

- [ ] **PIPE-01**: `ingest(source_id)` runs the full loop register → parse → resolve → extract → validate → load idempotently, reading the source row from `data/manifest.json` and writing back `status` (`pending → parsed → loaded`).
- [ ] **PIPE-02**: The pipeline mints exactly one `SourceContext` per source from manifest fields and threads it into both `validate_batch` and `load`; it passes resolved canonical names as `gazetteer_hints` into extraction.
- [ ] **PIPE-03**: The pipeline checks `stop_reason`; a `max_tokens` truncation splits the chunk and re-extracts (idempotency dedupes the overlap), and guards for a missing `ANTHROPIC_API_KEY` before any LLM call.

### End-to-End Ingest & Verification (ING)

All **three** registered markdown sourcebooks (Lost Mine of Phandelver, Hoard of the Dragon Queen, Rise of Tiamat) are ingested end-to-end through the same pipeline — each is a must-pass. **Rise of Tiamat is the suspect-generator verification anchor** (its Cult/Council plot is what Query B reasons over).

- [ ] **ING-01**: All three registered markdown sourcebooks are ingested end-to-end; their events, NPCs, goals, and factions land in the graph with provenance and canon tier. The shared "Tyranny of Dragons" front matter (HotDQ/RoT) deduplicates via content-hash rather than producing duplicate edges.
- [ ] **ING-02**: All extracted edges from each of the three books are manually reviewable (small enough at three single-source books) — the human-review backstop against extraction errors.
- [ ] **ING-03**: An integration test confirms a validated edge survives the MERGE round-trip and is retrievable by the flagship queries (A: goal lookup, B: suspect-generator, spatiotemporal scope).
- [ ] **ING-04**: The suspect-generator (Query B) returns plausible results over real Rise of Tiamat data — a known instigator surfaces with a traceable motive (aligned goal) and means (command/capability path), per a defined acceptance checklist.
- [ ] **ING-05**: Cross-book entity resolution holds — entities appearing in more than one book (e.g. the Cult of the Dragon, Severin, Tiamat across HotDQ and RoT) resolve to a single canonical node, not per-book duplicates.

---

## v2 Requirements (deferred — PLAN Phase 3)

- **PDF parser profile for scanned/older sourcebooks** — PyMuPDF4LLM fast pass + per-page triage escalating hard two-column pages to Marker `--use_llm`/Docling. Deferred because the first three target books are already Markdown; PDFs (e.g. Descent into Avernus) come later.
- **Confidence-scored review queue + auto-accept policy tuning** (beyond the minimal sink)
- **Descent into Avernus ingest + RoT→DiA seam verification** (the seam seed edge is flagged unverified)
- **Blood War modeled as a `Conflict` node** (slow front-state + battle-event stream)
- **Generalized extraction prompts/resolution** from learnings

---

## Out of Scope (with reasoning)

- **Hybrid vector retrieval + embeddings** — out of scope for v1; now **ROADMAP Phase 4** (sequenced after v1). Needs real graph data first (this milestone produces it). Embedding model already deployed (bge-m3 @ `gb10:8090`, 1024-dim, cosine); Neo4j native vector index means zero retrofit cost.
- **Live DM companion over MCP** — out of scope for v1; now **ROADMAP Phase 4**. Cannot build/test retrieval without graph content.
- **Contradiction auto-resolution** — PLAN Phase 5; RoT is single-source, nothing to resolve. Stamp canon-tier; resolve nothing (resolving now risks silently discarding facts, violating "hold contradictions with attribution").
- **Novel/EPUB parser + multi-edition batch ingest** — PLAN Phase 5; different extraction problem; reusing the sourcebook profile produces garbage.
- **GNNs / graph ML** — PLAN Phase 6, optional; needs a large graph; never replaces the explainable LLM+Cypher path.
- **Game-mechanics layer** — explicitly lower priority; stat-block text is the hardest parse case for no lore payoff.
- **Writing through MCP** — architectural red line; the Python bolt driver owns all writes.

---

## Traceability

| REQ-ID | Phase | Status |
|--------|-------|--------|
| SCH-01 | Phase 1 | Pending |
| SCH-02 | Phase 1 | Pending |
| SCH-03 | Phase 1 | Pending |
| RES-01 | Phase 1 | Pending |
| RES-02 | Phase 1 | Pending |
| RES-03 | Phase 1 | Pending |
| LOAD-01 | Phase 1 | Pending |
| LOAD-02 | Phase 1 | Pending |
| LOAD-03 | Phase 1 | Pending |
| LOAD-04 | Phase 1 | Pending |
| LOAD-05 | Phase 1 | Pending |
| PARSE-01 | Phase 2 | Pending |
| PARSE-02 | Phase 2 | Pending |
| PARSE-03 | Phase 2 | Pending |
| PARSE-04 | Phase 2 | Pending |
| PIPE-01 | Phase 3 | Pending |
| PIPE-02 | Phase 3 | Pending |
| PIPE-03 | Phase 3 | Pending |
| ING-01 | Phase 3 | Pending |
| ING-02 | Phase 3 | Pending |
| ING-03 | Phase 3 | Pending |
| ING-04 | Phase 3 | Pending |
| ING-05 | Phase 3 | Pending |

---
*Defined: 2026-06-15 · Milestone: v1 "First Ingest"*
