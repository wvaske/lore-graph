<!-- refreshed: 2026-06-15 -->
# Architecture

**Analysis Date:** 2026-06-15

## System Overview

```text
┌─────────────────────────────────────────────────────────────────────┐
│                     Ingestion Pipeline                              │
│                   `lore_graph/pipeline.py` (stub)                   │
├──────────────┬────────────────┬──────────────────┬──────────────────┤
│   Parsing    │  Extraction    │   Validation     │    Loading       │
│ `parsing.py` │`extraction.py` │  `extraction.py` │  `loader.py`     │
│   (stub)     │  extract_with_ │   Validator      │   (stub)         │
│              │  llm()         │   (pure, no I/O) │                  │
└──────┬───────┴───────┬────────┴────────┬─────────┴────────┬─────────┘
       │               │                 │                   │
       ▼               ▼                 ▼                   ▼
┌─────────────┐ ┌──────────────┐ ┌────────────────┐ ┌──────────────────┐
│ Source PDFs │ │ Anthropic    │ │  Gazetteer     │ │  Neo4j 5 Graph   │
│ / EPUBs     │ │ API (LLM)    │ │  (in-memory    │ │  + Vector Index  │
│data/sources/│ │ forced tool  │ │  name→id idx)  │ │  bolt :7687      │
└─────────────┘ │ use)         │ └────────────────┘ └──────────────────┘
                └──────────────┘
                                                            │
                                                            ▼
                                               ┌──────────────────────┐
                                               │  MCP Server          │
                                               │  (read-only Docker   │
                                               │  mcp/neo4j image)    │
                                               │  .mcp.json           │
                                               └──────────────────────┘
                                                            │
                                                            ▼
                                               ┌──────────────────────┐
                                               │  DM Companion / AI   │
                                               │  (Claude Code or     │
                                               │  external agent)     │
                                               └──────────────────────┘
```

## Component Responsibilities

| Component | Responsibility | File |
|-----------|----------------|------|
| `pipeline.py` | Orchestrates the full ingest loop: register→parse→chunk→resolve→extract→validate→load→embed | `lore_graph/pipeline.py` |
| `parsing.py` | Per-source-type parser profiles; converts PDFs/EPUBs to provenance-tagged text chunks | `lore_graph/parsing.py` |
| `extraction.py` | Controlled vocabulary (Enums), Pydantic models, prompt builder, Gazetteer, Validator, `extract_with_llm` boundary | `lore_graph/extraction.py` |
| `loader.py` | Idempotent MERGE writer to Neo4j via bolt; routes QUEUE verdicts to review sink | `lore_graph/loader.py` |
| `Gazetteer` | In-memory name/alias→canonical_id index with fuzzy resolution via `rapidfuzz` | `lore_graph/extraction.py` |
| `Validator` | Pure, network-free deterministic validation: dangling-edge rejection, type-domain checking, ACCEPT/QUEUE/REJECT routing | `lore_graph/extraction.py` |
| `extract_with_llm` | Sole LLM boundary; forced tool-use call to Anthropic API returning `ExtractionResult` | `lore_graph/extraction.py` |
| Schema / Cypher | Constraints, seed data, and flagship query patterns for Neo4j | `schema/lore_graph_schema.cypher` |
| Manifest | JSON source registry: title, edition, canon tier, parse status | `data/manifest.json` |
| MCP config | Wires read-only Neo4j MCP server into Claude Code via Docker | `.mcp.json` |

## Pattern Overview

**Overall:** Schema-constrained LLM extraction pipeline feeding a property graph with closed-world edge validation and human-in-the-loop review routing.

**Key Characteristics:**
- The LLM is deliberately isolated behind a single function (`extract_with_llm`) — the validation layer is pure Python with no network dependency
- Events are reified as graph nodes (never entity→entity verb edges), enabling time and causality on the data model
- All writes flow through the Python bolt driver; the MCP server is strictly read-only
- Provenance (`source`, `canon`, `edition`) is pipeline-stamped, never LLM-generated
- State-facts carry `valid_from`/`valid_to` in DR years for temporal interval queries

## Layers

**Parse Layer (stub):**
- Purpose: Convert raw source material (PDFs, EPUBs) to provenance-tagged `Chunk` objects
- Location: `lore_graph/parsing.py`
- Contains: Per-source-type parser profiles (`sourcebook`, `novel`, `wiki`)
- Depends on: PyMuPDF4LLM, Marker, Docling, ebooklib, BeautifulSoup (optional deps)
- Used by: `pipeline.py`

**Extraction + Validation Layer (implemented):**
- Purpose: LLM-driven entity/relation extraction constrained to a closed vocabulary; deterministic validation of results
- Location: `lore_graph/extraction.py`
- Contains: `NodeLabel` Enum, `RelType` Enum, `RELATION_DOMAINS` type matrix, Pydantic models (`ExtractedNode`, `ExtractedEdge`, `ExtractionResult`), `SourceContext`, `Gazetteer`, `Validator`, `extract_with_llm`, `build_extraction_prompt`
- Depends on: `pydantic`, `rapidfuzz`, `anthropic` (only for `extract_with_llm`)
- Used by: `pipeline.py`

**Load Layer (stub):**
- Purpose: Idempotent MERGE write path to Neo4j; routes verdicts to graph or review queue
- Location: `lore_graph/loader.py`
- Contains: `load(kept, rejected) -> LoadReport` (contract documented, not yet implemented)
- Depends on: `neo4j` bolt driver
- Used by: `pipeline.py`

**Pipeline Orchestration (stub):**
- Purpose: Top-level ingest entrypoint; ties all layers together as a repeatable, idempotent loop
- Location: `lore_graph/pipeline.py`
- Contains: `ingest(source_id: str) -> IngestReport` (contract documented, not yet implemented)
- Depends on: `parsing.py`, `extraction.py`, `loader.py`

**Graph / Schema Layer:**
- Purpose: Neo4j 5 schema definition, constraints, seed data, and flagship Cypher queries
- Location: `schema/lore_graph_schema.cypher`
- Contains: Uniqueness constraints per node type, comment conventions, seed MERGE statements, Query A (goal lookup), Query B (suspect-generator), Query C (spatiotemporal scope)

## Data Flow

### Primary Ingestion Path

1. **Register** source in manifest (`data/manifest.json`) — source id, title, edition, canon tier, type
2. **Parse** source file to `Chunk` list with section/page provenance (`lore_graph/parsing.py` — stub)
3. **Resolve mentions** against `Gazetteer` to get canonical entity hints
4. **Extract** — `extract_with_llm(chunk, gazetteer_hints)` in `lore_graph/extraction.py:372` calls Anthropic API with forced tool-use; returns `ExtractionResult` (nodes + edges)
5. **Validate** — `Validator.validate_batch(result, ctx)` in `lore_graph/extraction.py:258`:
   - Resolves all node refs (batch temp_id or Gazetteer lookup)
   - Rejects DANGLING edges (endpoint resolves to nothing)
   - Rejects TYPE-VIOLATING edges (outside `RELATION_DOMAINS` matrix)
   - Routes survivors to ACCEPT (confidence ≥ threshold, no review-flagged nodes) or QUEUE
   - Returns `(kept: list[ValidatedEdge], rejected: list[ValidatedEdge])`
6. **Load** — ACCEPT edges → Neo4j MERGE; QUEUE edges → review sink (`lore_graph/loader.py` — stub)
7. **Embed** node text into Neo4j native vector index (planned, not yet implemented)

### Retrieval Path (planned)

1. Agent or DM companion issues natural language query via MCP server
2. MCP server (read-only `mcp/neo4j` Docker container, `.mcp.json`) runs Cypher
3. Retrieval = vector seed on node embeddings → graph walk for context
4. Results scoped by canon tier (`PUBLISHED` > `MY_CANON` > `CAMPAIGN_ACTUAL`) and DR year interval

### Validation Routing

```
ExtractionResult (from LLM)
        │
        ▼
Validator.validate_batch()
        │
        ├── DANGLING endpoint ──────────────────► REJECT (drop, log reason)
        ├── TYPE violation (RELATION_DOMAINS) ──► REJECT (drop, log reason)
        ├── confidence < threshold OR             QUEUE (human review)
        │   new RESOLVABLE entity ───────────────►
        └── confidence ≥ threshold AND ──────────► ACCEPT → Neo4j MERGE
            all endpoints known
```

**State Management:**
- `Gazetteer` is in-memory; populated from Neo4j-backed canonical entity set before each pipeline run
- All durable state lives in Neo4j; the Python process is stateless between runs
- Idempotency enforced by content-hash chunk deduplication + MERGE semantics

## Key Abstractions

**`NodeLabel` / `RelType` Enums:**
- Purpose: Closed vocabulary; single source of truth for what the LLM may emit and what the schema accepts
- Location: `lore_graph/extraction.py:40-94`
- Pattern: `str, Enum` — values match Neo4j label/relationship-type strings exactly

**`RELATION_DOMAINS`:**
- Purpose: Type matrix mapping each `RelType` to `(permitted_source_labels, permitted_target_labels)`; the type-check gate in `Validator`
- Location: `lore_graph/extraction.py:99-124`
- Pattern: `dict[RelType, tuple[set[NodeLabel], set[NodeLabel]]]` — consulted on every edge during `validate_batch`

**`ExtractionResult` (Pydantic):**
- Purpose: LLM tool-call output shape; nodes carry `temp_id` (batch-local), edges carry `source_ref`/`target_ref` that are either temp_ids or canonical names
- Location: `lore_graph/extraction.py:155-158`

**`SourceContext` (dataclass):**
- Purpose: Provenance carrier — `source`, `canon` (CanonTier), `edition`, `canon_rank`; stamped by the pipeline, never by the LLM
- Location: `lore_graph/extraction.py:171-176`

**`Gazetteer`:**
- Purpose: Normalized name/alias → canonical_id index; fuzzy match via `rapidfuzz.fuzz.token_sort_ratio`; ambiguity detection (score gap < 5 between top two candidates)
- Location: `lore_graph/extraction.py:189-229`

**`Validator`:**
- Purpose: Pure, deterministic, network-free integrity gate; only component with direct unit tests
- Location: `lore_graph/extraction.py:253-329`

## Entry Points

**Extraction demo (network-free):**
- Location: `lore_graph/extraction.py:400` (`if __name__ == "__main__"`)
- Triggers: `python -m lore_graph.extraction` / `make extract-demo`
- Responsibilities: Exercises validation on a synthetic assassination scenario without any network calls

**Test suite:**
- Location: `tests/test_validation.py`
- Triggers: `make test` / `pytest`
- Responsibilities: Four unit tests covering ACCEPT routing, type-violation rejection, dangling-edge rejection, and QUEUE routing for new resolvable entities

**Neo4j schema application:**
- Location: `schema/lore_graph_schema.cypher` applied via `make schema`
- Triggers: `make schema`
- Responsibilities: Creates uniqueness constraints + seed nodes; must be run against a live Neo4j instance

## Architectural Constraints

- **LLM isolation:** `extract_with_llm` is the only function that makes network calls in the extraction layer. The `Validator` and `Gazetteer` must stay pure and network-free to remain unit-testable without credentials.
- **Write ownership:** Only the Python bolt driver (`loader.py`) writes to Neo4j. The MCP server is configured read-only (`NEO4J_READ_ONLY=true` in `.mcp.json`). Never write through MCP.
- **Vocabulary discipline:** Adding a `RelType` requires a simultaneous entry in `RELATION_DOMAINS` in `lore_graph/extraction.py`. The Cypher schema in `schema/lore_graph_schema.cypher` must also agree.
- **Evidence length:** `ExtractedEdge.evidence` is hard-truncated to 25 words by a Pydantic `field_validator` (`lore_graph/extraction.py:148-151`) — never store verbatim copyrighted passages.
- **Global state:** `Gazetteer` instances are created per pipeline run; no module-level singletons outside the demo `__main__` block.
- **Idempotency:** All Neo4j writes use MERGE; re-running the pipeline on the same source must be a no-op.

## Anti-Patterns

### Entity-to-entity verb edges

**What happens:** Writing a direct relationship like `(:Person)-[:BETRAYED]->(:Person)` instead of reifying the event.
**Why it's wrong:** Direct edges cannot carry a DR year, a canon tier, causal links, or multiple participants. The entire "suspect-generator" query relies on `(:Event)-[:INSTIGATED_BY]->(:Agent)` chains.
**Do this instead:** Emit an `Event` node and connect participants with role edges (`INSTIGATED_BY`, `EXECUTED_BY`, `TARGETED`) — see pattern in `lore_graph/extraction.py` prompt rules and `schema/lore_graph_schema.cypher:62-65`.

### Inventing provenance in the LLM prompt

**What happens:** Asking the LLM to supply `source`, `edition`, or `canon` values in the extraction output.
**Why it's wrong:** The model will hallucinate or misattribute provenance, making the canon-tier axis unreliable at scale.
**Do this instead:** Pass a `SourceContext` from the pipeline; provenance is stamped post-validation in `loader.py`, never returned by the LLM. See `lore_graph/extraction.py:335-362` (prompt explicitly excludes provenance fields).

### Writing through the MCP server

**What happens:** Using the Neo4j MCP tool to execute CREATE or MERGE statements from an agent session.
**Why it's wrong:** MCP is configured read-only; the Python bolt driver is the only authorized write path, and it enforces idempotency and provenance stamping.
**Do this instead:** All writes go through `loader.py` via the `neo4j` Python driver.

## Error Handling

**Strategy:** Fail-explicit with structured reasons at the validation boundary; human review queue for uncertainty.

**Patterns:**
- Invalid edges collect `reasons: list[str]` and are returned in the `rejected` list from `Validator.validate_batch` — callers decide how to log/store them
- Low-confidence or ambiguous-entity edges are routed to QUEUE (not silently dropped) so a human can accept or reject them
- `extract_with_llm` returns an empty `ExtractionResult()` if no tool-use block is found in the LLM response (graceful fallback, `lore_graph/extraction.py:393-394`)
- Stubs (`pipeline.py`, `loader.py`, `parsing.py`) raise `NotImplementedError` immediately to prevent silent no-ops

## Cross-Cutting Concerns

**Logging:** None currently implemented — stubs use `raise NotImplementedError`. The demo prints structured output to stdout.
**Validation:** Centralized in `Validator.validate_batch`; all extraction output passes through before any write.
**Authentication:** Neo4j credentials via environment variables (`NEO4J_PASSWORD`, `NEO4J_USERNAME`); Anthropic API key via `ANTHROPIC_API_KEY`. See `.env.example`.

---

*Architecture analysis: 2026-06-15*
