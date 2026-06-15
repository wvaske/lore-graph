# Technology Stack

**Analysis Date:** 2026-06-15

## Languages

**Primary:**
- Python 3.11+ — entire pipeline: extraction, validation, loading, parsing, orchestration

**Secondary:**
- Cypher (Neo4j query language) — schema definition, constraints, seed data, flagship queries (`schema/lore_graph_schema.cypher`)

## Runtime

**Environment:**
- Python 3.11 minimum (required by `pyproject.toml`: `requires-python = ">=3.11"`)
- Docker for Neo4j (via docker-compose)

**Package Manager:**
- pip with setuptools 68+
- Lockfile: Not present (no `requirements.txt` or `uv.lock`; dependencies specified as version bounds in `pyproject.toml`)

## Frameworks

**Core:**
- None (lean custom Python pipeline; no application framework)

**Data Modeling:**
- Pydantic v2 (`>=2.6`) — LLM output schema, extraction result models, field validators (`lore_graph/extraction.py`)

**Testing:**
- pytest `>=8` — unit tests for pure validation layer (`tests/test_validation.py`)

**Linting:**
- Ruff `>=0.5` — code linting; run via `make lint` (`ruff check lore_graph tests`)

**Build:**
- setuptools `>=68` — package build backend

## Key Dependencies

**Critical:**
- `pydantic>=2.6` — defines the schema-constrained LLM output types (`ExtractedNode`, `ExtractedEdge`, `ExtractionResult`); Pydantic v2 is required (v1 is not compatible)
- `anthropic>=0.40` — Anthropic Python SDK; used in `extract_with_llm()` for forced-tool-use extraction; isolated behind a single function in `lore_graph/extraction.py`
- `neo4j>=5.18` — official Bolt driver; Python pipeline owns all writes to Neo4j; MCP server handles reads
- `rapidfuzz>=3.6` — fuzzy name matching for entity resolution in `Gazetteer.resolve()`; gracefully degrades to exact-match only if missing

**Optional — Parsing (`parsing` extra):**
- `pymupdf4llm>=0.0.17` — fast first-pass PDF extraction; used to triage which pages need heavier tools
- `marker-pdf` — layout-aware PDF parser with `--use_llm` for two-column RPG sourcebook pages
- `docling` — alternative layout model for PDFs when Marker is insufficient
- `ebooklib` — EPUB novel ingestion
- `beautifulsoup4` — HTML/EPUB parsing for novel profile

**Dev:**
- `pytest>=8` — test runner
- `ruff>=0.5` — linter

## Configuration

**Environment:**
- Configured via `.env` file (copy from `.env.example`); `.env` is gitignored
- Required variables:
  - `NEO4J_URI` — bolt connection URI (default: `bolt://localhost:7687`)
  - `NEO4J_USERNAME` — database username
  - `NEO4J_PASSWORD` — database password
  - `ANTHROPIC_API_KEY` — required for live LLM extraction calls
  - `EXTRACTION_MODEL` — Anthropic model name (default: `claude-sonnet-4-6`)
  - `ACCEPT_THRESHOLD` — float; edges above this confidence are auto-accepted (default: `0.75`)
  - `FUZZY_THRESHOLD` — integer; rapidfuzz score cutoff for entity resolution (default: `90`)

**Build:**
- `pyproject.toml` — single source for project metadata, dependencies, build config
- `Makefile` — developer commands: `make up`, `make down`, `make schema`, `make test`, `make extract-demo`, `make lint`

## Platform Requirements

**Development:**
- Python 3.11+
- Docker (for Neo4j via `docker-compose.yml`)
- `make` (GNU make for developer commands)
- `.env` file with `NEO4J_PASSWORD` and `ANTHROPIC_API_KEY`

**Production:**
- Self-hosted deployment; no cloud platform specified
- Neo4j 5 Community Edition via Docker (`neo4j:5-community`)
- Data volume at `./neo4j_data/` (gitignored)
- Raw source books at `data/sources/` (gitignored; never committed)

---

*Stack analysis: 2026-06-15*
