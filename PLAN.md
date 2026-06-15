# Lore Graph — Build Plan

A self-hosted knowledge-graph + hybrid-retrieval pipeline for D&D / Forgotten
Realms lore, exposed to a DM companion over MCP. This document is written to be
handed to Claude Code as a working spec. Schema lives in `lore_graph_schema.cypher`.

## Guiding principles

- **Closed-world where possible, open-world where forced.** Named entities
  (NPCs, deities, archdevils, factions, locations) are largely enumerable up
  front; build a gazetteer first and resolve mentions against it. Events, goals,
  and lore relationships are prose-bound and need LLM extraction.
- **Provenance and canon are load-bearing, not metadata.** Every node and edge
  carries `source` (book+page / "session N") and `canon`
  (`PUBLISHED` | `MY_CANON` | `CAMPAIGN_ACTUAL` | `FORESHADOWED`). At full scale
  (all editions + novels) the corpus *will* contradict itself; the graph's job
  is to hold contradictions with attribution, not resolve them silently.
- **Edition + source tier is a first-class axis.** A 2e fact and a 5e fact about
  the same entity are both true-in-context. Tag every fact with edition and a
  canon-tier ordering so queries can prefer (e.g.) 5e-sourcebook over novel over
  earlier-edition when resolving conflicts.
- **Idempotent ingestion.** Re-running on the same source must not duplicate.
  Content-hash every chunk; `MERGE` not `CREATE`; skip unchanged chunks.
- **Human in the loop on low-confidence edges.** Extraction proposes; a review
  queue disposes. Auto-accept high-confidence/validated edges; queue the rest.

## Tooling stack

| Concern | Choice | Notes |
|---|---|---|
| Graph DB | **Neo4j 5 Community**, Docker | Native vector index → graph + embeddings in one store (hybrid retrieval). APOC + GDS plugins. |
| Companion bridge | **Official Neo4j MCP server** (`mcp/neo4j` Docker image) | Read-only mode for the companion; separate write-enabled instance/config for ingestion. Schema introspection + Cypher tools. |
| Sourcebook PDF parse | **Marker** (`--use_llm` for messy pages) or **Docling** | Two-column layout + stat blocks + sidebars scramble naive extractors. Marker's LLM pass or Docling's layout model handle reading order. PyMuPDF4LLM as a fast first pass to triage which pages need the heavy tool. |
| Novel parse (EPUB) | **Marker** or **ebooklib + BeautifulSoup** | Narrative prose — chapter is the natural unit. No tables/stat blocks; different extractor profile. |
| Structure-aware chunking | Custom, driven by parsed headings/chapters | Respect document structure; carry section + page provenance into every chunk. |
| Embeddings | Local model (e.g. BGE / nomic-embed via your existing LLM tooling) | Store on nodes in Neo4j vector index. |
| Entity resolution | `rapidfuzz` (alias/fuzzy) + embedding similarity + LLM disambiguation for hard cases | Resolve mention → canonical node. Bootstrapped from the gazetteer. |
| Schema-constrained extraction | Anthropic API tool-use / forced JSON, or `instructor` + Pydantic | Fixed node-type + relation + event-role vocab. Validate every edge against the entity set; reject dangling edges. |
| Orchestration | Lean custom Python pipeline; optionally LlamaIndex `PropertyGraphIndex` as accelerator | Framework optional — idempotency and provenance matter more than framework choice. |
| Source registry | Small SQLite/JSON manifest | Tracks each source: title, edition, canon tier, parse status, content hashes. |

## The generalized ingestion pipeline (the repeatable loop)

Every source — sourcebook, novel, your wiki — runs the same stages. What
changes per source type is the *parser profile* and the *canon tier*, not the
shape of the pipeline.

1. **Register** the source in the manifest: title, edition, canon tier, type
   (sourcebook | novel | wiki | session-log).
2. **Parse** to clean structured text/markdown using the type's parser profile.
3. **Segment** into provenance-tagged chunks (section/chapter + page).
4. **Recognize & resolve** entity mentions against the gazetteer; create new
   canonical nodes for confirmed-new entities (queued for review at scale).
5. **Extract** schema-constrained: entities→nodes, relationships→edges, events
   reified with roles, goals captured with `PURSUES`/`SERVES`/`ALIGNS_WITH`.
6. **Validate**: type-check against schema; reject edges to nonexistent nodes;
   score confidence; route low-confidence to the review queue.
7. **Load** idempotently (`MERGE`) with `source`, `canon`, edition, and
   `valid_from`/`valid_to` on time-bounded facts.
8. **Embed** node text → vector index.
9. **Detect contradictions** across canon tiers; flag, don't auto-resolve.
10. **Iterate**: add next source, re-run; gazetteer and graph grow each pass.

## Phased milestones

Each phase has a definition of done. Don't advance until met.

### Phase 0 — Environment
- Neo4j (Docker, APOC + GDS), write-enabled ingestion config + read-only MCP config.
- Repo scaffold, manifest store, `.env`, healthcheck script.
- **Done when:** `MERGE`/read round-trips via the Neo4j MCP server from Claude Code.

### Phase 1 — Schema + hand-seeded spine
- Apply `lore_graph_schema.cypher` (constraints, conventions).
- Hand-author the stable skeleton: nine Hells layers + archdukes, Asmodeus's
  hierarchy, the Council of Waterdeep factions (RoT), top-level Faerûn geography.
- Seed the initial gazetteer (canonical names + aliases) from this spine plus the
  RoT/DiA appendix NPC lists.
- **Done when:** Query A ("what is X trying to accomplish") and the spatiotemporal
  query return sensible results on hand-entered data.

### Phase 2 — One book, end to end (Rise of Tiamat)
- Parse RoT; tune the sourcebook parser profile on its two-column layout.
- Run the full pipeline; manually review *all* extracted edges (small enough to).
- **Done when:** RoT events, NPCs, goals, and factions are in the graph with
  provenance, and the suspect-generator (Query B) returns plausible results.

### Phase 3 — Pipeline hardening + Descent into Avernus
- Generalize extraction prompts + resolution from Phase 2 learnings.
- Build the review queue (confidence-scored auto-accept vs. human review).
- Ingest DiA; verify the RoT→DiA seams (e.g. Tiamat/Avernus) resolve as edges.
- Model the **Blood War** as a `Conflict` node: slow-changing front-state +
  a stream of battle/campaign events; Avernus as its front line.
- **Done when:** adding a book is mostly running the pipeline + clearing the queue.

### Phase 4 — Hybrid retrieval + companion
- Vector index over node text; retrieval = vector seed → graph traversal.
- Wire the read-only MCP server to the companion; author the query patterns it
  uses (spatiotemporal scope, goal lookup, suspect-generation).
- Import MediaWiki wikilinks as hand-authored lore edges; session logs as
  `CAMPAIGN_ACTUAL` event feed.
- **Done when:** the companion answers a session-time lore question by combining
  vector entry + graph walk, scoped to party time/place, respecting canon tier.

### Phase 5 — Scale-out (all editions + novels)
- Add the **novel parser profile** (EPUB, narrative prose, chapter units).
- Batch-ingest prior editions + FR novels at lower canon tiers.
- **Contradiction tooling becomes primary:** detect, attribute, and let queries
  resolve by canon-tier preference. Expect this phase to dominate the effort.
- **Done when:** conflicting facts across editions/novels coexist with
  attribution and the companion prefers the configured canon tier.

### Phase 6 — Graph ML (optional, post-scale experiment)

Only worth attempting once the graph is large (all editions + novels → tens of
thousands of nodes). A GNN learns a vector embedding per node by repeated
"message passing" — each node absorbs a summary of its neighbors, so after a few
layers its embedding encodes its multi-hop *structural* position. Two nodes end
up similar when they sit in similar relational contexts, even if their text
differs. This is distinct from text embeddings, which is the whole point of
doing it. **It does not replace the LLM+Cypher path** — that path stays primary
because it produces *explainable* results (a traversable reason: "suspect because
goal aligns + commands assassins"), and a DM tool's deliverable is the reason,
not a bare likelihood score.

Purpose / what this phase would buy us:
- **Structural similarity search** — "find me NPCs *like* this one," where "like"
  means similar goals, allegiances, and narrative role rather than similar prose.
  Text vectors cannot give this; graph position can.
- **Speculative link suggestion (creativity aid)** — surface pairs never linked in
  canon that structurally resemble pairs that usually are, as candidate plot
  seams for the DM to accept or reject. This is link prediction used as
  inspiration, not as ground truth.
- **Community / cluster detection** — find implicit factions or thematic clusters
  the curated edges don't name explicitly.

Prerequisites: a large, well-populated graph; otherwise there's too little signal
to learn from. Treat outputs as suggestions for human judgment, never as facts
written back to the graph without review.

## Known hard parts (budget for these)

- **Two-column RPG PDFs** with stat blocks/sidebars wreck naive reading order.
  Triage with PyMuPDF4LLM, escalate hard pages to Marker `--use_llm`/Docling.
- **Entity resolution drift:** "Severin" / "Severin Silrajin" / "the cult leader"
  must collapse to one node, or queries silently miss. Invest in the gazetteer.
- **Novels vs. sourcebooks** are different extraction problems; don't reuse one
  prompt for both.
- **Contradiction at scale** is the real project once you go past two books;
  the canon-tier axis must exist from Phase 1, not be retrofitted.
- **Provenance discipline:** an edge without a source is technically debt you
  can't pay down later — enforce it at load time.
