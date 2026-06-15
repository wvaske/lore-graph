# External Integrations

**Analysis Date:** 2026-06-15

## APIs & External Services

**LLM / AI:**
- Anthropic Messages API — schema-constrained lore extraction from text chunks
  - SDK/Client: `anthropic>=0.40` (Python SDK)
  - Auth: `ANTHROPIC_API_KEY` (env var)
  - Usage: forced tool-use (`tool_choice: {"type": "tool", "name": "emit_lore"}`) to produce structured `ExtractionResult` JSON
  - Isolation: exclusively called via `extract_with_llm()` in `lore_graph/extraction.py`; validation layer is pure and has no dependency on this call
  - Default model: `claude-sonnet-4-6` (configurable via `EXTRACTION_MODEL` env var)
  - Token budget: `max_tokens=4096` per extraction call

## Data Storage

**Databases:**
- Neo4j 5 Community Edition — primary knowledge graph store
  - Docker image: `neo4j:5-community` (via `docker-compose.yml`)
  - Container name: `lore-graph-neo4j`
  - Ports: `7474` (browser UI), `7687` (Bolt protocol)
  - Connection env vars: `NEO4J_URI`, `NEO4J_USERNAME`, `NEO4J_PASSWORD`
  - Python client: `neo4j>=5.18` (official Bolt driver; Python pipeline owns all writes)
  - Plugins: APOC (`apoc.*` unrestricted), Graph Data Science (`gds.*` unrestricted)
  - Native vector index: built into Neo4j 5.x — no separate vector database needed
  - Data volume: `./neo4j_data/` (mounted Docker volume, gitignored)
  - Schema: `schema/lore_graph_schema.cypher` (applied via `make schema`)

**File Storage:**
- Local filesystem only
  - Raw source material at `data/sources/` (gitignored; copyrighted books not committed)
  - Source registry at `data/manifest.json` (lightweight JSON; committed)

**Caching:**
- None currently; idempotency via content-hash chunk skipping is planned for `loader.py`

## Authentication & Identity

**Auth Provider:**
- No user-facing authentication; single-user local tool
- Neo4j authentication: username/password (`NEO4J_AUTH` in docker-compose, sourced from `NEO4J_PASSWORD` env var; default `change-me`)

## Companion / MCP Bridge

**Model Context Protocol (MCP):**
- Official Neo4j MCP server (`mcp/neo4j` Docker image)
- Configured in `.mcp.json`; wires Claude Code (DM companion) to the graph as a read-only tool
- Transport: Docker (`docker run -i --rm --network host`) to sidestep binary PATH issues
- Mode: `NEO4J_READ_ONLY=true` — companion can only query, never write
- Telemetry: `NEO4J_TELEMETRY=false`
- Database: `NEO4J_DATABASE=neo4j`
- Auth passed via env vars at runtime: `NEO4J_URI`, `NEO4J_USERNAME`, `NEO4J_PASSWORD`
- **Architectural rule:** All writes go through the Python Bolt driver only; MCP server is strictly read-only

## Monitoring & Observability

**Error Tracking:**
- None configured

**Logs:**
- Standard Python `print()` used in demo/CLI (`lore_graph/extraction.py` `__main__` block)
- No structured logging framework in place

## CI/CD & Deployment

**Hosting:**
- Self-hosted; no cloud platform or deployment pipeline specified

**CI Pipeline:**
- None detected (no `.github/`, `.gitlab-ci.yml`, or similar)

## Environment Configuration

**Required env vars:**
- `NEO4J_URI` — Bolt URI (e.g. `bolt://localhost:7687`)
- `NEO4J_USERNAME` — Neo4j username
- `NEO4J_PASSWORD` — Neo4j password (used by docker-compose and Python driver)
- `ANTHROPIC_API_KEY` — required for live extraction calls; NOT needed for validation tests or `make extract-demo`
- `EXTRACTION_MODEL` — Anthropic model name (optional; defaults to `claude-sonnet-4-6` in code)
- `ACCEPT_THRESHOLD` — float confidence threshold (optional; defaults to `0.75`)
- `FUZZY_THRESHOLD` — integer rapidfuzz cutoff (optional; defaults to `90`)

**Secrets location:**
- `.env` file at repo root (gitignored; never committed); template at `.env.example`
- Neo4j password also referenced in `docker-compose.yml` via `${NEO4J_PASSWORD:-change-me}` shell expansion

## Webhooks & Callbacks

**Incoming:**
- None

**Outgoing:**
- None

## Planned Integrations (not yet implemented)

**Embeddings:**
- Local embedding model (e.g. BGE, nomic-embed) planned for Phase 4
- Embeddings to be stored in Neo4j 5's native vector index on nodes
- No embedding provider currently wired

**Review Queue:**
- A `QUEUE` verdict sink is planned in `loader.py` (stub); may become `:ReviewItem` nodes in Neo4j or an external store

**GNN / Graph ML:**
- Graph Data Science (GDS) plugin is loaded but not yet used; reserved for Phase 6 structural similarity and community detection

---

*Integration audit: 2026-06-15*
