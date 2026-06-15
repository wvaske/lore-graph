# Architecture Research

**Domain:** Idempotent LLM-extraction ingestion pipeline feeding a Neo4j property graph (D&D / Forgotten Realms lore)
**Researched:** 2026-06-15
**Confidence:** HIGH (grounded in the in-repo settled contracts: `extraction.py` implemented and read in full; `loader.py`/`parsing.py`/`pipeline.py` carry documented contracts; `schema/lore_graph_schema.cypher` defines the constraints and flagship queries the loader must satisfy)

> **Scope note.** The high-level architecture is SETTLED in `CLAUDE.md` and is *not* relitigated here. This document specifies the **integration architecture** for the four components this "first ingest" milestone builds — gazetteer bootstrap, `loader.py`, `parsing.py`, `pipeline.py` — their boundaries, the exact data shapes passed between stages, and the dependency-driven build order.

## Standard Architecture

### System Overview

The settled pipeline contract is **register → parse → segment → resolve → extract → validate → load → (embed deferred)**. The implemented layer (`extraction.py`) sits in the middle; this milestone builds the bookends (parse, load) plus the orchestrator and the gazetteer bootstrap that feeds resolution.

```
┌──────────────────────────────────────────────────────────────────────┐
│                      pipeline.py — orchestrator (NEW)                  │
│   register → parse → segment → resolve → extract → validate → load     │
│   owns: SourceContext construction, manifest I/O, run-level idempotency │
├───────────┬───────────────┬───────────────┬──────────────┬───────────┤
│  parse    │   resolve      │   extract      │   validate    │   load    │
│ (NEW      │  (Gazetteer    │ (extract_with_ │  (Validator   │  (NEW     │
│ parsing.py)│   — existing,  │  llm —         │   — existing, │  loader.py)│
│           │   BOOTSTRAPPED │  existing      │   PURE)       │           │
│           │   from Neo4j)  │  boundary)     │               │           │
└────┬──────┴───────┬────────┴──────┬─────────┴──────┬───────┴─────┬─────┘
     │              │               │                │             │
     ▼              ▼               ▼                ▼             ▼
┌─────────┐  ┌──────────────┐ ┌────────────┐  ┌────────────┐ ┌──────────────┐
│ Source  │  │ Gazetteer    │ │ Anthropic  │  │ RELATION_  │ │  Neo4j 5     │
│ PDFs    │  │ (in-memory,  │ │ API        │  │ DOMAINS    │ │  + bolt      │
│         │  │  loaded from │ │ (forced    │  │ matrix     │ │  (loader     │
│         │  │  Neo4j spine)│ │  tool use) │  │            │ │  owns writes)│
└─────────┘  └──────▲───────┘ └────────────┘  └────────────┘ └──────┬───────┘
                    │  bootstrap (read canonical spine)             │ writes
                    └───────────────────────────────────────────────┘
```

**The single load-bearing integration fact:** the `Validator` is **pure** and the `Gazetteer` it consults is **in-memory**. The graph's canonical truth lives in Neo4j. The gazetteer bootstrap is therefore the bridge that makes closed-world validation *work*: without it, every canonical entity is unknown to the validator, so its edges become DANGLING-rejected or QUEUE-routed. The bootstrap is **read-only Neo4j → in-memory index**; it does not violate Validator purity because the Validator still receives a populated `Gazetteer` object and performs no I/O itself.

### Component Responsibilities

| Component | Responsibility (what it owns) | Implementation |
|-----------|-------------------------------|----------------|
| `pipeline.py` (NEW) | The orchestration loop. Reads the manifest, constructs `SourceContext` from manifest fields (the ONLY place provenance/canon is minted), calls parse → resolve → extract → validate → load per chunk, threads the bootstrapped `Gazetteer` through, updates manifest `status`, returns `IngestReport`. | `ingest(source_id) -> IngestReport` |
| Gazetteer bootstrap (NEW) | One read query against Neo4j that hydrates an empty `Gazetteer` from the hand-seeded spine + appendix NPC lists, so resolution is non-empty before parsing. Read-only; preserves Validator/Gazetteer purity. | `bootstrap_gazetteer(driver) -> Gazetteer` (in `loader.py` or a small `gazetteer.py`) |
| `loader.py` (NEW) | The **only** write path. MERGE ACCEPT edges (nodes-by-id then relationship), stamp `source`/`canon`/`edition` + `valid_from`/`valid_to`; route QUEUE edges to a review sink; log REJECTs; enforce content-hash idempotency. | `load(kept, rejected, ctx) -> LoadReport`; `is_chunk_loaded(hash)`/`record_chunk(hash)`; `bootstrap_gazetteer(driver)` |
| `parsing.py` (NEW) | Convert a source file to provenance-tagged `Chunk` objects via the `sourcebook` profile (PyMuPDF4LLM fast pass → escalate hard pages). Pure text-transformation; no graph, no LLM. | `parse(path, profile) -> list[Chunk]`; `Chunk{text, source, section, page, content_hash}` |
| `Gazetteer` (existing) | In-memory name/alias → canonical_id fuzzy index. **No interface change** — bootstrap populates it via existing `.add()`. | `extraction.py` |
| `Validator` (existing) | Pure closed-world validation → `(kept, rejected)`. **Unchanged.** | `extraction.py` |
| `extract_with_llm` (existing) | Sole LLM boundary. **Unchanged.** | `extraction.py` |

## Recommended Project Structure

No restructuring needed — the four module slots exist. New code fills three stubs plus one new bootstrap function.

```
lore_graph/
├── extraction.py     # EXISTING, UNCHANGED — vocab, models, Gazetteer, Validator, extract_with_llm
├── parsing.py        # FILL STUB — Chunk dataclass + parse(path, profile) sourcebook profile
├── loader.py         # FILL STUB — Neo4j MERGE writer, review sink, content-hash idempotency,
│                     #             AND bootstrap_gazetteer(driver)
├── pipeline.py       # FILL STUB — ingest(source_id) orchestration loop + manifest I/O
└── __init__.py       # populate stable public API once loader/pipeline land (CONCERNS item)
```

### Structure Rationale

- **`bootstrap_gazetteer` belongs in `loader.py`, not `extraction.py`.** It is the only *other* code holding a Neo4j driver (read instead of write). Co-locating keeps all Neo4j handling in one file and avoids a circular dependency — `extraction.py` must stay free of the `neo4j` import to keep the Validator network-free. A standalone `gazetteer.py` is acceptable if `loader.py` grows large, but it imports from `extraction.py`, never the reverse. **Confidence: HIGH.**
- **`Chunk` is owned by `parsing.py`** — a new `@dataclass` carrying `text`, `source` (book+page string), `section`, `page`, `content_hash`. The `source` string later becomes `SourceContext.source`.
- **The orchestrator owns the manifest.** `ingest()` reads the source row, builds `SourceContext`, writes back `status` (`pending → parsed → loaded`). Keeping manifest I/O in the orchestrator preserves the loader as a pure write-to-graph component.

## Architectural Patterns

### Pattern 1: Gazetteer bootstrap as a read-only hydration step (resolves the headline CONCERN)

Before any parsing, `pipeline.ingest()` opens the bolt driver and calls `bootstrap_gazetteer(driver)`, which runs one Cypher read over the canonical spine and populates an in-memory `Gazetteer` via `.add(id, label, names)`. Threaded read-only into both resolve and the `Validator`.

```python
# loader.py — read-only; the ONLY non-write Cypher in the codebase
def bootstrap_gazetteer(driver, fuzzy_threshold: float = 90.0) -> Gazetteer:
    gaz = Gazetteer(fuzzy_threshold)
    q = """
    MATCH (n)
    WHERE n.id IS NOT NULL
      AND any(l IN labels(n) WHERE l IN
              ['Person','Organization','Power','Location','Plane','Item',
               'Goal','Event','Prophecy','Conflict','Capability'])
    RETURN n.id AS id, labels(n) AS labels, n.name AS name,
           coalesce(n.aliases, []) AS aliases
    """
    with driver.session() as s:
        for r in s.run(q):
            label = _primary_label(r["labels"])   # map multi-label -> NodeLabel
            names = [r["name"], *r["aliases"]]
            gaz.add(r["id"], label, [x for x in names if x])
    return gaz
```
> **Mapping gotcha (must handle):** schema nodes carry compound labels like `(:Power:Agent)` / `(:Organization:Agent)`. The `NodeLabel` enum has the *specific* label, not `Agent`. `_primary_label` must pick the specific one and drop the `Agent` marker, or resolution writes a wrong label and downstream TYPE checks misfire.

### Pattern 2: Idempotent MERGE writer with content-hash skip (resolves the "no idempotency" CONCERN)

Two-level idempotency. (1) **Chunk level:** before extracting, check whether the chunk's `content_hash` was already loaded; if so skip the whole chunk (no LLM call, no write). (2) **Edge level:** every write is `MERGE` on canonical id, never `CREATE`.

```python
STATE_FACTS = {RelType.RULES, RelType.ALLIED_WITH, RelType.IMPRISONED_IN,
               RelType.COMMANDS, RelType.MEMBER_OF, RelType.PART_OF}

def _write_edge(tx, e: ValidatedEdge):
    params = {"sid": e.source_id, "tid": e.target_id,
              "source": e.provenance.source, "canon": e.provenance.canon.value,
              "edition": e.provenance.edition, "canon_rank": e.provenance.canon_rank,
              "confidence": e.confidence, "evidence": e.evidence}
    tx.run("MERGE (s {id:$sid}) MERGE (t {id:$tid})", **params)
    set_clause = ("r.source=$source, r.canon=$canon, r.edition=$edition, "
                  "r.canon_rank=$canon_rank, r.confidence=$confidence, r.evidence=$evidence")
    if e.rel_type in STATE_FACTS:
        set_clause += ", r.valid_from=$valid_from, r.valid_to=$valid_to"
        params["valid_from"], params["valid_to"] = _dr_interval(e)
    tx.run(f"MATCH (s {{id:$sid}}),(t {{id:$tid}}) "
           f"MERGE (s)-[r:`{e.rel_type.value}`]->(t) SET {set_clause}", **params)
```
> **Two CONCERNS the loader defends against:** (1) `Item` has **no uniqueness constraint** — add one before MERGEing items. (2) Minted-but-unresolved ids use the `new::Label::norm-name` scheme; a `new::Person::...` reaching ACCEPT signals a resolution miss to monitor. **Idempotency requires the constraint:** MERGE without a backing unique constraint can race and duplicate.

### Pattern 3: Verdict-routed load — ACCEPT to graph, QUEUE to review sink, REJECT to log

`load(kept, rejected)` fans out by `ValidatedEdge.verdict`. `kept` mixes ACCEPT and QUEUE (the Validator returns them together); the loader splits them: ACCEPT → MERGE; QUEUE → review sink (`:ReviewItem` nodes carrying the edge + `reasons`, replayable on approval); REJECT → structured log only, never written. A full review UI is OUT this milestone (Phase 3).

### Pattern 4: Parse profile with quality-triage escalation (sourcebook only)

`parse(path, "sourcebook")` runs PyMuPDF4LLM as a fast CPU first pass, scores each page's reading-order quality, escalates only mangled pages to Marker `--use_llm`/Docling. Output is `list[Chunk]`. The `novel`/`wiki` profiles `raise NotImplementedError` (Phase 4/5), matching the stub discipline.

## Data Flow

### The exact shapes passed between stages (the integration contract)

```
manifest row {id,title,type,edition,canon,canon_rank}
    │  pipeline.ingest() builds:  SourceContext(source, canon, edition, canon_rank)
    ▼
parse(path, "sourcebook") → list[Chunk]   Chunk{text, source, section, page, content_hash}
    │
[ per chunk, skip if loader.is_chunk_loaded(chunk.content_hash) ]
    ▼ resolve  (Gazetteer, bootstrapped) → gazetteer_hints: list[str]  (exact canonical names)
    ▼ extract_with_llm(chunk.text, gazetteer_hints) → ExtractionResult{nodes, edges}
    ▼ Validator.validate_batch(result, ctx) → (kept, rejected)  : list[ValidatedEdge]
    │          ValidatedEdge{rel_type, source_id, target_id, confidence, evidence,
    │                        provenance:SourceContext, verdict:Verdict, reasons}
    ▼ loader.load(kept, rejected, ctx) → LoadReport
    │          ACCEPT→MERGE graph ; QUEUE→:ReviewItem ; REJECT→log
    ▼ loader.record_chunk(chunk.content_hash)   (in same tx as the writes)
    ▼ (after all chunks) pipeline updates manifest status → "loaded"
       returns IngestReport{chunks, accepted, queued, rejected, skipped}
```

**Critical contract details, verified against the existing code:**

1. **`SourceContext` is minted exactly once, by the pipeline**, from manifest fields — never by parse, never by the LLM (`build_extraction_prompt` rule 5 forbids the LLM emitting source/edition/canon). The same `ctx` is passed to `validate_batch` (which stamps it onto every `ValidatedEdge.provenance`) and to `load`.
2. **`gazetteer_hints` is `list[str]` of exact canonical names** — the pipeline resolves names found in the chunk and passes the *canonical* names so the LLM reuses them in `source_ref`/`target_ref` rather than inventing duplicates (the entity-fragmentation defense).
3. **`validate_batch` returns `(kept, rejected)` where `kept` mixes ACCEPT and QUEUE.** The loader, not the validator, splits them. Do not re-implement verdict logic in the loader.
4. **Minted node ids** for unresolved entities follow `new::{label}::{norm-name}` (set inside `validate_batch`). The loader MERGEs by whatever id it receives; it does not re-resolve.

### State Management

- **Durable state lives only in Neo4j** (graph + `:Chunk` hashes + `:ReviewItem` queue). The Python process is stateless between runs.
- **The gazetteer is reconstructed each run** by `bootstrap_gazetteer`. After a successful ingest, newly-minted nodes are in the graph, so the *next* run's bootstrap picks them up — the gazetteer "grows each pass" (PLAN step 10) with no extra wiring.

## Suggested Build Order (dependency-driven)

```
Track A (graph-write path — sequential, on the critical path)
  1. loader.py : MERGE writer + provenance/time-bounding   ──┐
  2. bootstrap_gazetteer(driver)  (lives with the loader)    ├─► both need a live
  3. content-hash idempotency (:Chunk) + :ReviewItem sink  ──┘    Neo4j + the schema

Track B (text path — independent, parallelizable)
  4. parsing.py : Chunk dataclass + sourcebook profile + triage

Convergence
  5. pipeline.py : ingest() ties register→parse→resolve→extract→validate→load
  6. End-to-end ingest of Rise of Tiamat + review + suspect-generator (Query B)
```

**Why this order:**

- **`loader.py` first.** It can be exercised against the *already-existing* `ValidatedEdge` output and schema — no parser, no LLM needed. Feed it the synthetic `kept`/`rejected` from the existing demo/tests and verify the MERGE round-trip against flagship Query A/B/C immediately. This unblocks the **highest-priority test gap** (extraction→Neo4j→query integration test).
- **`bootstrap_gazetteer` second, co-located.** Shares the driver; prerequisite for clean ACCEPTs. Small and testable on its own (bootstrap from the seed, assert `gaz.resolve("Severin")` hits `severin`). Validates the `:Power:Agent` → `NodeLabel` mapping early.
- **`parsing.py` in parallel (Track B).** Depends on nothing in the graph path — pure text-in/`Chunk`-out. The cleanest parallelization seam; tune two-column triage on the RoT PDF while the loader/bootstrap land.
- **`pipeline.py` last** — pure glue; every contract it threads is already verified in isolation.
- **End-to-end RoT ingest closes the milestone** — only then can the "done-when" be checked.

**Resolve-during-build CONCERNS (flag for the roadmap):**

| CONCERN | Where resolved | Build step |
|---|---|---|
| Gazetteer never bootstrapped | `bootstrap_gazetteer(driver)` | Step 2 (blocking) |
| No content-hash idempotency | `:Chunk {hash}` MERGE + skip | Step 3 (blocking) |
| QUEUE verdicts have nowhere to go | `:ReviewItem` sink | Step 3 (blocking) |
| `Item` has no uniqueness constraint | add constraint to schema | Step 1 (prereq) |
| `Gazetteer._norm` strips "the " mid-string | fix to leading-article strip | Step 2 |
| `RELATION_DOMAINS` `KeyError` | add `set(RelType)==set(RELATION_DOMAINS)` test | any time |
| No extraction→Neo4j→query integration test | add when loader lands | Step 1–3 |

## Anti-Patterns

- **Putting the Neo4j driver (or any I/O) inside `extraction.py`** — violates the pure-Validator rule. Keep hydration in `loader.py` as a free function returning a populated `Gazetteer`.
- **Letting the parser or LLM mint provenance/canon** — parser emits only a `source` string; the pipeline builds the authoritative `SourceContext` from the **manifest**.
- **Re-deriving verdicts in the loader, or writing QUEUE/REJECT to the graph** — trust `ValidatedEdge.verdict`; ACCEPT→graph, QUEUE→`:ReviewItem`, REJECT→log.
- **`CREATE` instead of `MERGE`, or MERGEing the relationship before the nodes exist** — MERGE each node by `id` first, then MERGE the relationship between matched nodes.

## Integration Points

| Service | Pattern | Notes |
|---------|---------|-------|
| Neo4j 5 (bolt) | `neo4j>=5.18` driver, sessions in `loader.py` only | Write path AND read-only bootstrap query. MCP stays read-only. |
| Anthropic API | Existing `extract_with_llm`, unchanged | Check `stop_reason=="max_tokens"` and split dense chunks; add an early `ANTHROPIC_API_KEY` guard. |
| PyMuPDF4LLM / Marker / Docling | Optional `parsing` deps, imported inside `parsing.py` | Keep imports inside `parse()` so the package imports without them (matches the deferred-import convention). |

| Boundary | Communication |
|----------|---------------|
| `pipeline.py` ↔ `parsing.py` | `parse() -> list[Chunk]`; `Chunk.source` → `SourceContext.source` |
| `pipeline.py` ↔ `extraction.py` | `Gazetteer.resolve`, `extract_with_llm`, `Validator.validate_batch` (all existing) |
| `pipeline.py` ↔ `loader.py` | `bootstrap_gazetteer(driver)` once; `load(kept, rejected, ctx)` per chunk; `is_chunk_loaded`/`record_chunk` |
| `loader.py` → `extraction.py` | imports `Gazetteer`, `NodeLabel`, `RelType`, `ValidatedEdge`, `Verdict` (one-directional; never the reverse) |

## Sources

- `CLAUDE.md` — settled architecture decisions (HIGH)
- `PLAN.md` — pipeline stages, Phase 1–2 definitions of done (HIGH)
- `lore_graph/extraction.py` — implemented contracts: `Gazetteer`, `Validator.validate_batch`, `SourceContext`, `ValidatedEdge`, `extract_with_llm`, `build_extraction_prompt`, minted-id scheme (HIGH)
- `lore_graph/{loader,parsing,pipeline}.py` — documented stub contracts (HIGH)
- `schema/lore_graph_schema.cypher` — constraints, multi-label `:Agent` convention, state-fact `valid_from/valid_to`, flagship Queries A/B/C (HIGH)
- `.planning/codebase/{ARCHITECTURE,CONCERNS,INTEGRATIONS,CONVENTIONS}.md` (HIGH)

---
*Architecture research for: idempotent LLM-extraction ingestion pipeline → Neo4j property graph (integration architecture for "first ingest")*
*Researched: 2026-06-15*
