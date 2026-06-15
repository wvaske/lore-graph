# CLAUDE.md — Lore Graph

Context for working in this repo. Read this before changing anything. `PLAN.md`
has the full phased build plan; this file is the orientation + the list of
decisions that are **settled** (don't relitigate them without a stated reason).

## What this is

A self-hosted knowledge graph + hybrid (graph + vector) retrieval pipeline for
D&D / Forgotten Realms lore, exposed to a DM companion over MCP. It ingests
sourcebooks and novels, builds a graph of people, organizations, goals, and
**reified events** across time, and answers session-time lore questions scoped
to where/when the party is — including a "who could plausibly be behind this
event" generator for building plots.

Primary focus is **lore** (people, canonical events, goals, politics, the Blood
War), not game mechanics. Mechanics are a separate, lower-priority layer.

## Settled architecture decisions (and why)

1. **Events are reified as nodes, not edges.** `(:Event)` with role edges
   (`INSTIGATED_BY`, `EXECUTED_BY`, `TARGETED`, `OCCURRED_AT`) and causal edges
   (`CAUSED`/`ENABLED`/`PREVENTED`). An entity-to-entity verb like "X betrayed Y"
   cannot carry time or causality; an event node can. This is the decision the
   whole model hangs on.
2. **Goals are first-class nodes.** `(:Agent)-[:PURSUES]->(:Goal)`, goals relate
   to each other (`SERVES`/`ALIGNS_WITH`/`CONFLICTS_WITH`) independently of who
   holds them. This powers both "what is X trying to do" and the suspect-generator
   (find agents whose goals an event advances). The two features are the same
   query run in opposite directions.
3. **Closed-world edge validation.** Every edge endpoint must resolve to a known
   canonical node or a node declared in the same batch; edges to nothing are
   **dangling** and rejected. This is only possible because the entity set is
   largely enumerable, and it's the main defense against hallucinated edges.
4. **Provenance + canon are load-bearing, not metadata.** Every node/edge carries
   `source`, `canon` (`PUBLISHED`/`MY_CANON`/`CAMPAIGN_ACTUAL`/`FORESHADOWED`),
   and edition. At full scale (all editions + novels) the corpus contradicts
   itself; the graph holds contradictions *with attribution* and resolves them at
   query time by canon-tier preference. The pipeline stamps provenance — **the LLM
   never invents it.**
5. **Time-bounded facts.** State-facts (`RULES`, `ALLIED_WITH`, `IMPRISONED_IN`…)
   carry `valid_from`/`valid_to` in in-world (DR) years. "Who ruled Avernus in
   1490 DR" resolves by interval overlap, not a flat truth.
6. **Hybrid retrieval in one store.** Neo4j 5 has a native vector index, so node
   text + embeddings + graph live together. Retrieval = vector seed → graph walk.
   Don't add a separate vector DB.
7. **The LLM is isolated behind one function** (`extract_with_llm`). Everything
   that protects graph integrity — the `Validator` — is pure and deterministic.
   Keep it that way: validation must stay unit-testable without a network call.
8. **GNNs are deferred to Phase 6** (post-scale, optional). Purpose: structural
   similarity ("NPCs like this one" by graph position), speculative link
   suggestion as a creativity aid, community detection. They do **not** replace
   the LLM+Cypher path, because that path produces *explainable* results and a DM
   tool's deliverable is the reason, not a likelihood score.

## Repo map

```
CLAUDE.md                     this file
PLAN.md                       full phased build plan + known hard parts
README.md                     human onboarding / quickstart
docker-compose.yml            Neo4j 5 Community (+ APOC, GDS) for local dev
.mcp.json                     wires the read-only Neo4j MCP server into Claude Code
.env.example                  copy to .env; creds, model, thresholds
schema/lore_graph_schema.cypher   constraints, conventions, seed, flagship queries
lore_graph/
  extraction.py               DONE: vocab enums, Pydantic models, prompt,
                              Gazetteer, Validator (pure), extract_with_llm.
                              `python -m lore_graph.extraction` runs a network-free demo.
  parsing.py                  STUB: per-source-type parser profiles
  loader.py                   STUB: idempotent MERGE writer + review queue sink
  pipeline.py                 STUB: orchestrates register→parse→extract→validate→load
tests/test_validation.py      tests for the pure Validator (accept/queue/reject)
data/sources/                 raw books — GITIGNORED, never commit copyrighted text
data/manifest.json            source registry (title, edition, canon tier, status)
```

## Current state

- **Schema** (`schema/`): complete starter. Apply with `make schema`.
- **Extraction + validation** (`lore_graph/extraction.py`): working, with a
  passing test. Controlled vocabulary (`NodeLabel`, `RelType`), the
  `RELATION_DOMAINS` type matrix, dangling-edge rejection, and accept/queue/reject
  routing all implemented. The LLM call is stubbed behind `extract_with_llm`.
- **Next, in order** (see PLAN Phases 1–3):
  1. `loader.py` — idempotent `MERGE` writer; stamps `valid_from`/`valid_to` +
     canon; sends `QUEUE` verdicts to a review table; `ACCEPT`s to the graph.
  2. Gazetteer bootstrap — seed canonical entities from the hand-authored spine
     (nine Hells layers + archdukes, Council of Waterdeep factions) and the
     RoT/DiA appendix NPC lists, so resolution works before parsing.
  3. `parsing.py` — sourcebook profile first (two-column triage:
     PyMuPDF4LLM → escalate hard pages to Marker `--use_llm`/Docling).
  4. `pipeline.py` — tie it together; ingest Rise of Tiamat end to end.

## Conventions

- **Python 3.11+, Pydantic v2.** The Enums in `extraction.py` are the single
  source of truth for the vocabulary; the Cypher schema must agree with them. If
  you add a `RelType`, add its entry to `RELATION_DOMAINS` in the same change.
- **Keep `Validator` pure.** No I/O, no network. Test it directly.
- **Idempotency:** writes use `MERGE`, never `CREATE`. Content-hash chunks; skip
  unchanged ones on re-ingest.
- **Evidence spans stay short** (<25 words, enforced in the model). These are
  provenance snippets — never store long verbatim passages from copyrighted books.
- **The agent (and companion) query via the read-only Neo4j MCP server. The
  Python pipeline owns all writes via the bolt driver.** Don't write through MCP.

## Stack / commands

- `make up` / `make down` — Neo4j via docker-compose (browser at :7474, bolt :7687).
- `make schema` — apply `schema/lore_graph_schema.cypher`.
- `make test` — `pip install -e .` then pytest.
- `make extract-demo` — runs the network-free validation demo.

## Gotchas

- **Two-column RPG PDFs** (stat blocks, sidebars) scramble naive reading order.
  Don't trust a single extractor; triage and escalate. Novels are a different
  profile (EPUB, prose, chapter units) — don't reuse the sourcebook parser.
- **Entity-resolution fragmentation** is the silent killer: "Severin" /
  "Severin Silrajin" / "the cult leader" must collapse to one node. Bootstrap the
  gazetteer and pass relevant names into the extraction prompt as hints.
- **Neo4j MCP via Claude Code:** a known PATH issue can hide the server binary.
  `.mcp.json` here uses the `docker run` form to sidestep it.
- **Contradiction at scale** is the real project past two books — the canon-tier
  axis exists from the start specifically so it doesn't need retrofitting.
- **Never commit `data/sources/`** — those are books you own, not repo content.
