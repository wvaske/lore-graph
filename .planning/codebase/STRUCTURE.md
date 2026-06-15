# Codebase Structure

**Analysis Date:** 2026-06-15

## Directory Layout

```
lore-graph/
├── lore_graph/                  # The pipeline Python package
│   ├── __init__.py              # Empty (package marker)
│   ├── extraction.py            # IMPLEMENTED: vocab enums, models, Gazetteer, Validator, LLM boundary
│   ├── parsing.py               # STUB: per-source-type parser profiles
│   ├── loader.py                # STUB: idempotent Neo4j MERGE writer + review queue
│   └── pipeline.py              # STUB: orchestrates the full ingest loop
├── schema/
│   └── lore_graph_schema.cypher # Neo4j constraints, seed data, flagship queries
├── tests/
│   └── test_validation.py       # Unit tests for the pure Validator
├── data/
│   ├── manifest.json            # Source registry (title, edition, canon tier, status)
│   └── sources/                 # Raw books — GITIGNORED, never commit copyrighted text
├── .planning/
│   └── codebase/                # GSD codebase map documents (this directory)
├── docker-compose.yml           # Neo4j 5 Community + APOC + GDS for local dev
├── pyproject.toml               # Project metadata, dependencies, build config
├── Makefile                     # Dev commands: up, down, schema, test, extract-demo, lint
├── .env.example                 # Environment variable template (copy to .env)
├── .mcp.json                    # MCP server config for Claude Code (read-only Neo4j)
├── .gitignore                   # Excludes .env, data/sources/, neo4j_data/, build artifacts
├── CLAUDE.md                    # Architecture decisions, conventions, repo orientation
├── PLAN.md                      # Phased build plan (Phases 0–6)
└── README.md                    # Human onboarding / quickstart
```

## Directory Purposes

**`lore_graph/` (Python package):**
- Purpose: The ingestion pipeline — parsing, extraction, validation, loading
- Contains: Four modules; `extraction.py` is the only fully-implemented module
- Key files: `lore_graph/extraction.py` (the heart: Enums, Pydantic models, Gazetteer, Validator, LLM boundary)

**`schema/`:**
- Purpose: Cypher schema definition applied to Neo4j via `make schema`
- Contains: Uniqueness constraints per node type, MERGE-based seed data, flagship query patterns (A: goal lookup, B: suspect-generator, C: spatiotemporal scope)
- Key files: `schema/lore_graph_schema.cypher`

**`tests/`:**
- Purpose: Pytest unit tests for the pure validation layer
- Contains: Tests for ACCEPT/QUEUE/REJECT routing in `Validator`
- Key files: `tests/test_validation.py`

**`data/`:**
- Purpose: Source registry (committed) and raw source material (gitignored)
- Contains: `manifest.json` (source registry), `sources/` directory (raw PDFs/EPUBs — never committed)
- Key files: `data/manifest.json`

**`neo4j_data/` (runtime volume):**
- Purpose: Neo4j persistent data volume, created by Docker
- Generated: Yes (by `make up`)
- Committed: No (in `.gitignore`)

## Key File Locations

**Entry Points:**
- `lore_graph/extraction.py:400`: Network-free demo / module `__main__` block
- `tests/test_validation.py`: All unit tests for the Validator
- `schema/lore_graph_schema.cypher`: Neo4j schema — run via `make schema`

**Configuration:**
- `.env.example`: Template for `.env`; defines `NEO4J_URI`, `NEO4J_PASSWORD`, `ANTHROPIC_API_KEY`, `EXTRACTION_MODEL`, `ACCEPT_THRESHOLD`, `FUZZY_THRESHOLD`
- `.mcp.json`: MCP server wiring for Claude Code (read-only Neo4j via Docker)
- `docker-compose.yml`: Neo4j 5 Community image configuration (ports 7474/7687, APOC + GDS plugins)
- `pyproject.toml`: Project dependencies and optional dependency groups (`parsing`, `dev`)

**Core Logic:**
- `lore_graph/extraction.py`: Controlled vocabulary Enums (`NodeLabel`, `RelType`), `RELATION_DOMAINS` type matrix, `ExtractionResult` Pydantic model, `Gazetteer`, `Validator`, `extract_with_llm`, `build_extraction_prompt`
- `lore_graph/loader.py`: STUB — documented contract for `load(kept, rejected) -> LoadReport`
- `lore_graph/parsing.py`: STUB — documented contract for `parse(path, profile) -> list[Chunk]`
- `lore_graph/pipeline.py`: STUB — documented contract for `ingest(source_id) -> IngestReport`

**Documentation:**
- `CLAUDE.md`: Architecture decisions and conventions reference (read before changing anything)
- `PLAN.md`: Phased build plan with definitions of done

**Testing:**
- `tests/test_validation.py`: Four pytest tests covering all Verdict routing paths

## Naming Conventions

**Files:**
- Module names: `snake_case.py` — `extraction.py`, `loader.py`, `parsing.py`, `pipeline.py`
- Test files: `test_{module}.py` — `tests/test_validation.py`
- Config files: lowercase with dots — `.env.example`, `.mcp.json`
- Schema files: `snake_case.cypher`

**Directories:**
- Python package: `snake_case` — `lore_graph/`
- Test directory: `tests/`
- Non-Python assets: lowercase noun — `schema/`, `data/`

**Python identifiers:**
- Classes: `PascalCase` — `Gazetteer`, `Validator`, `ExtractionResult`, `SourceContext`, `ValidatedEdge`
- Enums: `PascalCase` with `UPPER_SNAKE_CASE` members — `NodeLabel.PERSON`, `RelType.INSTIGATED_BY`, `CanonTier.PUBLISHED`
- Functions: `snake_case` — `extract_with_llm`, `build_extraction_prompt`, `validate_batch`
- Constants / dicts: `UPPER_SNAKE_CASE` — `RELATION_DOMAINS`, `AGENT_LABELS`, `RESOLVABLE_LABELS`

**Neo4j naming (in Cypher):**
- Node labels: `PascalCase` — `:Person`, `:Organization`, `:Event`, `:Goal`
- Relationship types: `UPPER_SNAKE_CASE` — `INSTIGATED_BY`, `PURSUES`, `ALLIED_WITH`
- Node/edge properties: mixed — `valid_from`, `canon_rank`, `dr_year`

## Where to Add New Code

**New node label or relation type:**
1. Add to `NodeLabel` or `RelType` Enum in `lore_graph/extraction.py`
2. Add entry to `RELATION_DOMAINS` in `lore_graph/extraction.py` (same change)
3. Add corresponding label/relationship definition in `schema/lore_graph_schema.cypher`
4. Update prompt in `build_extraction_prompt` if the type needs special rules

**New parser profile (sourcebook, novel, wiki):**
- Implementation: `lore_graph/parsing.py` (currently a stub)
- Returns `list[Chunk]` where each Chunk carries text + provenance

**New ingestion source:**
- Register in `data/manifest.json` with `id`, `title`, `type`, `edition`, `canon`, `canon_rank`, `status`

**New validation rule:**
- Add to `Validator.validate_batch` in `lore_graph/extraction.py`
- Add corresponding test in `tests/test_validation.py`

**New Cypher query pattern:**
- Add to `schema/lore_graph_schema.cypher` as a documented comment block

**New tests:**
- Place in `tests/` as `test_{area}.py`
- Import from `lore_graph.extraction`; keep Validator tests network-free (no Neo4j, no Anthropic)

## Special Directories

**`data/sources/`:**
- Purpose: Raw copyrighted source material (PDFs, EPUBs)
- Generated: No (user-provided)
- Committed: No (in `.gitignore`) — never commit copyrighted content

**`neo4j_data/`:**
- Purpose: Neo4j persistent data volume created by Docker Compose
- Generated: Yes (`make up`)
- Committed: No (in `.gitignore`)

---

*Structure analysis: 2026-06-15*
