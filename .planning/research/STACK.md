# Stack Research

**Domain:** RPG sourcebook PDF → schema-constrained LLM extraction → Neo4j 5 property graph (closed-world, provenance-first ingestion pipeline)
**Researched:** 2026-06-15
**Confidence:** HIGH (parsing + driver versions verified against PyPI / official docs); MEDIUM on the precise "hard-page" heuristic thresholds (those are empirical, tune on RoT)

> Scope note: the core stack (Python 3.11+, Pydantic v2, Neo4j 5 Community, Anthropic forced-tool-use extraction, rapidfuzz resolution) is **settled** and is not relitigated here. This document answers only the two open milestone questions: (a) the PDF-parsing toolchain + triage strategy for two-column RPG sourcebooks, and (b) the idempotent batched Neo4j write path. It closes with an explicit "what NOT to use" for this design.

## Recommended Stack

### Core Technologies

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| `pymupdf4llm` | `>=1.27,<2` (1.27.2.x current) | Fast first-pass extraction → per-page Markdown chunks with metadata for triage | No ML, no GPU, no heavy deps; by far the fastest path for native (text-layer) PDFs. `to_markdown(..., page_chunks=True)` returns one dict per page with `text`, `tables`, `images`, `toc_items`, and bbox metadata — exactly the provenance-tagged unit this pipeline needs. Handles the *easy* 80%+ of RoT pages alone. |
| `marker-pdf` | `>=1.10,<2` (1.10.2, Jan 2026) | Layout-aware escalation parser for hard pages (two-column reading order, stat blocks, sidebars) | Strong reading-order reconstruction on multi-column native PDFs. `use_llm=True` (Gemini/Ollama backend) merges split tables and cleans messy layout. Used **only** on pages flagged hard by triage — not the whole book. |
| `neo4j` (official Bolt driver) | `>=5.18,<6` (pin `5.28.3`, Jan 2026) | All graph writes (`loader.py`) | Already settled at `>=5.18`. **Stay on the 5.x line for a Neo4j 5 Community server** — see Version Compatibility below. `driver.execute_query()` + `UNWIND $rows ... MERGE` is the canonical idempotent batch write. |
| `hashlib` (stdlib) | — | Content-hash chunk idempotency (`:Chunk {content_hash}`) | No dependency needed. `sha256` over normalized chunk text gives the skip-on-reingest key required by CLAUDE.md's idempotency rule. |

### Supporting Libraries

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `docling` | `>=2.10` (2.102.x current) | Third-tier escalation parser (heaviest) | Only if Marker `use_llm` still mangles a specific page class. Its Heron/RT-DETRv2 layout models are accurate but GPU-oriented (28 ms/img on A100) — overkill for a one-book milestone. Keep behind the `parsing` extra; treat as an opt-in fallback, **not** the default. |
| `PyMuPDF` (`fitz`) | pulled by `pymupdf4llm` | Low-level page introspection for the triage heuristic | Use `page.get_text("dict")` / `page.find_tables()` / text-block bbox geometry to *score* page difficulty before deciding whether to escalate. This is the engine that powers the hard-page detector. |
| `rapidfuzz` | `>=3.6` (settled) | Entity resolution (existing Gazetteer) | Already in use; no change. Listed for completeness — the parser feeds resolved chunks into it. |
| `ebooklib` + `beautifulsoup4` | latest | EPUB novel profile | **Out of scope this milestone** (PLAN Phase 5). Keep in the `parsing` extra but do not wire now. |

### Development Tools

| Tool | Purpose | Notes |
|------|---------|-------|
| `pytest>=8` | Unit tests | Test the triage scorer and the loader's MERGE/UNWIND query builders against an ephemeral Neo4j (or pure string-assertion on generated Cypher) without touching the network for the scorer. |
| `ruff>=0.5` | Lint | Already configured (`make lint`). |
| Neo4j Browser (`:7474`) | Manual verification of ingested RoT edges | Phase 2 done-criteria requires manually reviewing *all* extracted edges; browser is the review surface until the review queue exists. |

## Triage Strategy — detecting and routing a "hard page" (the core question)

The plan is correct: **PyMuPDF4LLM fast pass → escalate only hard pages.** The missing piece is *how to decide*. Compute a per-page difficulty score from cheap PyMuPDF geometry **before** committing the page's text. Recommended signals (all available from `page.get_text("dict")` + `page.find_tables()`):

| Signal | How to compute | Why it predicts trouble |
|--------|----------------|-------------------------|
| Column count | Cluster text-block `bbox` x-midpoints; >1 cluster spanning the page width = multi-column | Two-column is the primary reading-order scrambler in RPG books |
| Span interleave | Sort blocks by y, check whether x-position oscillates left↔right within a y-band | Detects when PyMuPDF flowed columns together (the failure mode), not just that columns exist |
| Table density | `len(page.find_tables().tables)` and table-area / page-area ratio | Stat blocks render as tables/grids that fast extraction garbles |
| Sidebar / boxed regions | Vector-graphics rectangles (`page["blocks"]` drawings) enclosing text | Sidebars break linear reading order |
| Text yield ratio | extracted char count ÷ (page area · expected density) | Very low yield ⇒ image/scanned page ⇒ needs OCR-capable tool |

Route: if `score < threshold` keep the PyMuPDF4LLM Markdown; else re-extract that page with Marker (`use_llm=True`). Persist the chosen tool per page as provenance (`parser=`, `parser_pass=fast|llm`) so reruns are auditable and the heuristic can be retuned. Calibrate the threshold by hand-checking ~10 known-hard RoT pages (Council of Waterdeep tables, monster stat blocks, episode sidebars) — thresholds are empirical (MEDIUM confidence) and the one-book scale makes manual calibration cheap.

Keep the parser **page-addressable**: every emitted chunk carries `{source_id, page, section_heading, parser, content_hash}`. This is what makes copyright-safe (<25-word evidence spans) provenance and idempotency both work.

## Idempotent batched Neo4j write path (the second open question)

Canonical pattern for `loader.py` using the official driver:

```python
# Chunk idempotency: skip unchanged content on re-ingest
driver.execute_query(
    """
    UNWIND $chunks AS c
    MERGE (ch:Chunk {content_hash: c.hash})
      ON CREATE SET ch.source = c.source, ch.page = c.page,
                    ch.section = c.section, ch.created = timestamp()
    """,
    chunks=batch, database_="neo4j",
)

# Nodes: MERGE on the canonical key only, stamp provenance on create
driver.execute_query(
    """
    UNWIND $nodes AS n
    MERGE (e {id: n.id})          // label set dynamically via APOC or per-label query
      ON CREATE SET e += n.props, e.source = n.source, e.canon = n.canon, e.edition = n.edition
      ON MATCH  SET e += n.merge_props   // only fields safe to re-stamp
    """,
    nodes=node_batch, database_="neo4j",
)

# Edges: UNWIND the validated ACCEPT batch; MATCH both endpoints, MERGE the rel
driver.execute_query(
    """
    UNWIND $edges AS r
    MATCH (a {id: r.start}), (b {id: r.end})
    CALL apoc.merge.relationship(a, r.type, {key: r.key}, {}, b, {}) YIELD rel
    SET rel.source = r.source, rel.canon = r.canon, rel.edition = r.edition,
        rel.valid_from = r.valid_from, rel.valid_to = r.valid_to
    """,
    edges=edge_batch, database_="neo4j",
)
```

Rules this encodes (all from CLAUDE.md / PROJECT.md constraints):

- **`MERGE`, never `CREATE`** — re-running a source is a no-op past the content-hash gate.
- **`UNWIND $rows`** is the one true batch idiom — one round-trip per batch, parameterized (no string interpolation, no injection, plan cache reuse). Batch size ~1k–10k rows; one book fits comfortably.
- **Provenance/edition/`valid_from`/`valid_to` stamped by the loader**, never by the LLM. `ON CREATE` for immutable provenance, `ON MATCH` only for fields explicitly safe to refresh.
- **Endpoints `MATCH`ed, not `MERGE`d, for edges** — the Validator already guarantees closed-world (no dangling edges) upstream, so the loader should `MATCH` both ends; a failed match is a *bug to surface*, not a node to silently create. (If you prefer defense-in-depth, log + drop rows where either `MATCH` misses rather than creating phantom nodes.)
- **Dynamic relationship types**: Cypher can't parameterize a rel type, so use `apoc.merge.relationship` (APOC is already loaded) rather than building one query per `RelType`. Same applies to dynamic node labels via `apoc.merge.node`.
- **Constraints first**: ensure uniqueness constraints exist for every MERGE key (note CONCERNS.md flags `Item` is missing one) — MERGE without a backing unique constraint risks duplicate nodes under concurrency and is slow.
- **Managed transactions**: `execute_query()` (auto-retry on transient errors) for the common path; drop to explicit `session.execute_write()` only if you need multiple statements in one atomic unit (e.g. chunk + its derived nodes + edges as one transaction).

## Installation

```bash
# Core write path (already present; pin the driver to the 5.x line)
pip install "neo4j>=5.18,<6"          # resolves to 5.28.3 — matches Neo4j 5 server

# Parsing extra (this milestone makes it real)
pip install "pymupdf4llm>=1.27,<2"    # pulls PyMuPDF (fitz)
pip install "marker-pdf>=1.10,<2"     # escalation parser; configure use_llm backend (Gemini/Ollama)

# Optional third-tier fallback (install only if Marker proves insufficient)
pip install "docling>=2.10"

# Deferred (Phase 5 novels) — keep declared, do not wire
pip install ebooklib beautifulsoup4
```

## Alternatives Considered

| Recommended | Alternative | When to Use Alternative |
|-------------|-------------|-------------------------|
| PyMuPDF4LLM (triage) + Marker (escalate) | Docling as the *primary* parser | If you had a GPU budget and many scanned/image-heavy books. For one native-text 5e PDF it's heavier setup for no payoff — keep as third-tier only. |
| Marker `use_llm` for hard pages | MinerU / pdf-craft | Competitive 2026 PDF→MD tools; defensible but add a new dependency and a new failure surface for marginal gain over Marker on this layout class. Revisit only if Marker visibly fails on RoT stat blocks. |
| `neo4j` 5.28.x driver | `neo4j` 6.x driver | Only after upgrading the server to Neo4j 6. With a Neo4j 5 Community server, the 6.x driver gives you only the common feature subset and drops older-Python support — no benefit, added risk. Stay 5.x. |
| `apoc.merge.relationship` for dynamic rel types | One hand-written MERGE per `RelType` | Acceptable if you want to avoid APOC in the write path; trades a small dependency for N near-duplicate queries. APOC is already loaded, so the dynamic form is cleaner. |
| stdlib `hashlib` content hashing | A SQLite manifest of seen hashes | The graph already stores `:Chunk {content_hash}`; an extra SQLite layer is redundant for one book. (Manifest stays JSON per existing design.) |

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| **LlamaIndex `PropertyGraphIndex` / `SchemaLLMPathExtractor`** | It re-implements the exact layer you've already built and validated — schema-constrained extraction + graph writes — but with **looser guarantees**. Its `strict=True` is best-effort schema filtering, not your *pure, unit-tested, closed-world* Validator with `RELATION_DOMAINS` type-matrix and dangling-edge rejection. Adopting it means either fighting it to disable its extractor/writer (net negative) or ceding integrity control and provenance stamping to a framework that treats provenance as optional. It also wants to own the Neo4j write path, conflicting with "Python bolt driver owns all writes, MERGE not CREATE, loader stamps provenance." **High-confidence: it fights this design.** | Keep the lean custom pipeline. Use the official `neo4j` driver directly for writes. |
| **A separate vector DB** (Pinecone/Weaviate/Qdrant/Chroma) | Settled against in CLAUDE.md — Neo4j 5 native vector index keeps embeddings + graph in one store. (Also out of scope until Phase 4.) | Neo4j 5 native vector index. |
| **`neo4j` 6.x driver against a Neo4j 5 server** | Major-version skew; you get only the common feature subset and risk subtle protocol/behavior mismatches for zero benefit on a 5.x Community server. | `neo4j>=5.18,<6` (5.28.3). |
| **`CREATE` for ingest writes** | Breaks idempotency — re-running RoT would duplicate nodes/edges. | `MERGE` on canonical keys, gated by content-hash chunk skip. |
| **String-interpolated Cypher / per-row queries in a loop** | Injection risk, no plan caching, N network round-trips — slow and unsafe. | Parameterized `UNWIND $rows ... MERGE` batches via `execute_query()`. |
| **One parser for both sourcebooks and novels** | Different problems (tabular two-column layout vs. linear prose); CLAUDE.md explicitly warns against reusing the sourcebook profile for novels. | Separate parser profiles; novels deferred to Phase 5 anyway. |
| **`instructor` for extraction** (an option in PLAN's table) | The forced-tool-use Anthropic boundary + Pydantic models already exist and are tested; adding `instructor` is a second way to do a solved thing. | Keep `extract_with_llm` as-is. |
| **Letting the LLM emit provenance/canon/edition** | Load-bearing integrity rule — these are stamped by the loader, never invented. | Loader sets them on `MERGE ... ON CREATE`. |

## Version Compatibility

| Package A | Compatible With | Notes |
|-----------|-----------------|-------|
| `neo4j` 5.28.3 (driver) | Neo4j 5 Community server | **Use this.** Driver 5.x ↔ server 5.x is the matched pair. |
| `neo4j` 6.2 (driver) | Neo4j 6.x server | Aligns with server 6; against a 5.x server you'd get only the common subset. Avoid until a server upgrade. |
| `pymupdf4llm` 1.27.x | `PyMuPDF` (auto-resolved) | Let pip resolve the compatible `PyMuPDF` rather than pinning `fitz` separately. |
| `marker-pdf` 1.10.2 | Python 3.11+ | `use_llm` needs an LLM backend configured (Gemini API key, or local Ollama). CPU-only works but slower; fine because it runs on *few* pages. |
| `apoc.*` | Neo4j 5 Community | Already loaded (docker-compose). Required for `apoc.merge.relationship`/`apoc.merge.node` dynamic-type writes. |

## Sources

- [PyPI: neo4j](https://pypi.org/project/neo4j/) — 5.28.3 latest 5.x (2026-01-12); 6.2 current major. HIGH
- [Neo4j Python Driver Manual — Performance](https://neo4j.com/docs/python-manual/current/performance/) — `UNWIND`+`MERGE` batch idiom, `execute_query`. HIGH
- [Neo4j driver-server compatibility](https://neo4j.com/developer/kb/neo4j-supported-versions/) — version alignment policy. HIGH
- [PyPI: marker-pdf](https://pypi.org/project/marker-pdf/) — 1.10.2 (2026-01-31); `use_llm`. HIGH
- [GitHub: datalab-to/marker](https://github.com/datalab-to/marker) — two-column reading order. HIGH
- [PyMuPDF4LLM API docs](https://pymupdf.readthedocs.io/en/latest/pymupdf4llm/api.html) — `page_chunks=True` per-page dict. HIGH
- [PyPI: docling](https://pypi.org/project/docling/) + [arXiv 2509.11720](https://arxiv.org/html/2509.11720v1) — 2.102.x, GPU-oriented perf. HIGH
- [LlamaIndex PropertyGraph docs](https://docs.llamaindex.ai/en/stable/examples/property_graph/property_graph_advanced/) + [GH issue #14324](https://github.com/run-llama/llama_index/issues/14324) — `strict` is best-effort. MEDIUM
- [Best Open-Source PDF-to-Markdown Tools 2026](https://themenonlab.blog/blog/best-open-source-pdf-to-markdown-tools-2026) — ecosystem comparison. MEDIUM

---
*Stack research for: RPG sourcebook PDF parsing + idempotent Neo4j 5 ingestion (closed-world, provenance-first)*
*Researched: 2026-06-15*
