# Feature Research

**Domain:** Knowledge-graph ingestion pipeline for tabletop RPG lore (graph-backed, query-by-Cypher slice; live companion + hybrid retrieval explicitly OUT for this milestone)
**Researched:** 2026-06-15
**Confidence:** HIGH

## Scope Note (read first)

This is a SUBSEQUENT milestone — "first ingest" (PLAN Phases 1–2). The vision is settled in `CLAUDE.md` / `PROJECT.md` / `PLAN.md`. The extraction + pure `Validator` layer is **already built and tested**; this milestone implements the write/ingest path: `loader.py`, gazetteer bootstrap, `parsing.py` (sourcebook profile), and `pipeline.py`, then ingests Rise of Tiamat (RoT) end-to-end and proves the suspect-generator (Query B) returns plausible results.

Features below are framed around one question: **what must an ingestion pipeline + graph-backed lore store DO to be trustworthy and usable for a DM via Cypher — not the full companion UX.** "Users" here = the DM/operator running ingestion and querying the graph directly (Neo4j browser / read-only MCP), not an end-user chatting with a companion.

## Feature Landscape

### Table Stakes (the graph becomes untrustworthy without these)

Missing any of these means the graph silently lies — duplicated nodes, edges with no source, hallucinated relationships, or non-reproducible state.

| Feature | Why Expected (trust failure if absent) | Complexity | Notes |
|---------|----------------------------------------|------------|-------|
| **Idempotent load (`MERGE`, never `CREATE`)** | Re-running a source must not duplicate. Without it, every re-run after a bug fix doubles the graph. | MEDIUM | `loader.py`. MERGE idempotent *only* with a uniqueness constraint backing the merge key. **`Item` has no constraint (CONCERNS.md)** — fix in the same change or `Item` MERGEs silently duplicate. |
| **Content-hash chunk skip** | Re-ingest of an unchanged source must be a true no-op. Manifest `status` is decorative until this exists. | MEDIUM | Hash each provenance-tagged chunk; record; skip unchanged. Also gates re-parse cost (parsing is the expensive stage). |
| **Provenance enforcement at load time** | Every node/edge carries `source`+`canon`+`edition`. An edge without a source is "debt you can't pay down later." LLM must NEVER supply these. | LOW–MEDIUM | Mechanism exists (`SourceContext`, evidence <25 words). Table stakes is *enforcing* it in the loader: refuse to write any edge lacking provenance. |
| **Dangling-edge rejection (closed-world validation)** | An edge whose endpoint resolves to nothing is the #1 hallucination vector. | DONE | Reuse `Validator` as-is. Loader must respect REJECT verdicts and never write them. |
| **Type-matrix edge validation** | `RELATION_DOMAINS` rejects structurally nonsensical lore. | DONE | One fragility: `RELATION_DOMAINS[rel_type]` has no `KeyError` guard. Add `set(RelType)==set(RELATION_DOMAINS)` test. |
| **Gazetteer bootstrap from Neo4j** | Entity-resolution fragmentation is "the silent killer." Today gazetteer is in-memory only and starts empty, so even Tiamat/Severin route to QUEUE/REJECT. | MEDIUM | `Gazetteer.load_from_neo4j(driver)` from the seeded spine + appendix NPC lists. **Hard dependency for everything downstream.** Fix `_norm` "the " bug here too. |
| **Sourcebook PDF parsing with triage** | Two-column layout + stat blocks + sidebars scramble reading order; garbage in → garbage graph. | HIGH | `parsing.py`. PyMuPDF4LLM fast pass → escalate mangled pages to Marker `--use_llm`/Docling. Pin heavy deps. |
| **Confidence-routed verdicts (ACCEPT/QUEUE/REJECT)** | Auto-accepting low-confidence edges pollutes canon; auto-rejecting loses signal. 0.75 threshold + novelty check is the right default. | DONE (routing) / LOW (wiring) | `validate_batch` produces verdicts. Loader honors all three. |
| **Review sink for QUEUE verdicts** | QUEUE edges currently have nowhere to go — the primary human-in-the-loop defense is unwired. | LOW–MEDIUM | Minimal: write to `:ReviewItem` nodes / flat table with reasons, reviewable in Neo4j browser. **Full review-queue UX is Phase 3 / OUT.** |
| **End-to-end idempotent pipeline orchestration** | Stages exist in isolation; trust requires one re-runnable loop. | MEDIUM | `pipeline.py`. Same shape for every source; only parser profile + canon tier vary. Updates manifest `status`; respects content-hash skip. |
| **Flagship queries return sensible results (A + B + spatiotemporal)** | A graph you can't query usefully is unverified. Milestone DoD is literally "suspect-generator returns plausible results." | LOW (queries exist) / MEDIUM (validating post-ingest) | Real work is an integration test: do validated edges survive MERGE and satisfy Query A/B/C? (HIGH-priority gap per CONCERNS.) |

### Differentiators (what makes THIS lore graph better than a wiki or flat RAG)

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| **Suspect-generator (abductive Query B)** | "Who could plausibly be behind this event?" — finds agents whose goals an event ADVANCES, with a traversable reason (motive: aligned goal; means: COMMANDS→CAPABLE_OF). The headline feature + a milestone DoD. | MEDIUM (query exists; HIGH to validate *good* suspects) | Built on goals-as-first-class + events-reified. Quality depends on resolution + goal edges from RoT. *The* thing to validate this milestone. |
| **Reified-event time model** | Events are nodes with role + causal edges + DR-year — things an entity→entity verb edge structurally cannot carry. | MEDIUM | The decision "the whole model hangs on." Verify the extractor isn't collapsing RoT plot events into flat relationships. |
| **Canon-tier + edition resolution axis** | Every fact tagged `canon` + edition + `canon_rank`, so contradictory facts coexist with attribution and resolve by preference at query time. | LOW (this milestone) | RoT is single-source, so the axis isn't *exercised* yet — but stamping it now is what lets Phase 5 avoid a retrofit. Differentiator-in-waiting. |
| **Time-bounded state facts (`valid_from`/`valid_to`)** | "Who ruled Avernus in 1490 DR" resolves by interval overlap, not flat truth. | MEDIUM | Loader stamps validity intervals. MERGE-key subtlety: a new interval must not silently overwrite an existing one — decide whether the merge key includes `valid_from`. |
| **Short-evidence provenance snippets (<25 words)** | Every edge carries a short verbatim span — explainability AND copyright-safety. | DONE | Enforced in the Pydantic model. Most KG pipelines store either no evidence or full passages; this is the explainable-and-legal middle. |

### Anti-Features (deliberately NOT this milestone — documented to prevent scope creep)

| Feature | Why Problematic now | Alternative |
|---------|---------------------|-------------|
| **Contradiction auto-resolution** | RoT is single-source — nothing to resolve. Building it now risks silently discarding facts, violating "hold contradictions with attribution." | Detect+flag only (and even that is Phase 5-primary). Stamp canon-tier; resolve nothing. |
| **The live companion / chat UX** | Explicitly OUT (Phase 4). Can't build/test retrieval without graph content — this milestone *produces* that content. | Ingest-and-query-by-Cypher slice; validate via Neo4j browser / read-only MCP. |
| **Hybrid vector retrieval + embeddings** | Pipeline step 8 is real but premature; retrieval is Phase 4 and needs real data + tuned queries first. | Defer. Neo4j native vector index means zero retrofit cost later. |
| **GNNs / graph ML** | Needs tens of thousands of nodes for signal; one book is nowhere near. Never replaces the explainable LLM+Cypher path. | Phase 6, optional. The suspect-generator already gives explainable abductive suggestions. |
| **Novel / EPUB parser profile** | Different extraction problem; reusing the sourcebook prompt produces garbage. Phase 5. | Sourcebook profile only. Keep `parse` profile-dispatched so adding "novel" later is additive. |
| **Descent into Avernus / RoT→DiA seam** | Phase 3. Prove the pipeline on ONE book first. The DiA seam seed edge is even flagged unverified. | RoT only; generalize from Phase 2 learnings. |
| **Blood War `Conflict` modeling** | Phase 3. Needs the pipeline hardened + a second book (Avernus) to be meaningful. | Defer. `Conflict` type exists; don't populate it. |
| **Writing through MCP** | Architectural red line: companion/MCP is read-only; breaks provenance + idempotency. | Python `loader.py` is the sole write path. |
| **Full review-queue UI / confidence-tuning UX** | Phase 3. For RoT the dataset is small enough to review every edge manually. | A flat review *sink* (`:ReviewItem` + reasons) + manual Cypher inspection. |
| **Game-mechanics layer** | Lower-priority, separate concern; stat-block text is the *hardest* parsing case. | Lore only. In parsing, stat blocks are pages to get reading-order-correct or skip. |

## Feature Dependencies

```
Gazetteer bootstrap (load_from_neo4j)
    └──requires──> Hand-seeded spine in Neo4j (schema seed, Phase 1)
    └──enables───> Entity resolution quality
                       └──enables──> Clean ACCEPT verdicts (vs QUEUE/REJECT noise)
                                          └──enables──> Suspect-generator plausibility

Sourcebook parser (parsing.py, triage)
    └──requires──> PyMuPDF4LLM + Marker/Docling (pin versions)
    └──feeds─────> Provenance-tagged chunks
                       └──requires──> Content-hash (idempotency + parse-cache)

Idempotent loader (loader.py)
    └──requires──> Uniqueness constraints on ALL node types (fix Item gap)
    └──requires──> Validator verdicts (DONE)
    └──requires──> Provenance stamping (SourceContext, DONE) — enforced at write
    └──provides──> Review sink (QUEUE destination)
    └──provides──> Time-bounded fact stamping (valid_from/valid_to merge-key care)

End-to-end pipeline (pipeline.py)
    └──requires──> ALL of: gazetteer bootstrap, parser, loader, manifest I/O
    └──provides──> RoT ingested with provenance

Flagship queries (A / B / spatiotemporal)
    └──requires──> RoT ingested (real data)
    └──validated-by──> Integration test (MERGE round-trip → query)

Embeddings / hybrid retrieval ──conflicts (scope)──> "first ingest"  [DEFER Phase 4]
Contradiction auto-resolution ──conflicts (principle)──> "hold with attribution" [DEFER/flag-only]
```

### Dependency Notes

- **Gazetteer bootstrap is the lynchpin.** Build it before parser/pipeline are useful. Empty gazetteer → mass QUEUE/REJECT → suspect-generator has no goal edges → milestone DoD unreachable.
- **Loader requires the `Item` uniqueness constraint** to be idempotent. Ship the constraint in the same change as the loader.
- **Content-hash serves two masters:** ingestion idempotency *and* PDF-parse caching. Implement once, gate both.
- **Suspect-generator quality is downstream of extraction accuracy**, not Cypher. The query is written; plausibility depends on goals/means edges landing correctly → depends on resolution → depends on the gazetteer.
- **Time-bounded MERGE keys need a deliberate decision:** does a relationship's merge identity include `valid_from`? Otherwise re-runs overwrite history.

## MVP Definition

### Launch With (this milestone = "first ingest", PLAN Phases 1–2)

- [ ] Gazetteer bootstrap from Neo4j — without it resolution fails and the graph fragments
- [ ] Idempotent loader (MERGE + provenance stamping + verdict routing)
- [ ] `Item` uniqueness constraint (+ remaining schema gaps)
- [ ] Content-hash chunk skip
- [ ] Review sink for QUEUE verdicts — minimal `:ReviewItem`, not a UI
- [ ] Sourcebook parser with PyMuPDF4LLM→Marker/Docling triage
- [ ] End-to-end pipeline orchestration (idempotent) + manifest I/O
- [ ] Rise of Tiamat ingested with provenance — all edges manually reviewable
- [ ] Suspect-generator (Query B) returns plausible results over RoT — the headline DoD
- [ ] Integration test: validated edge → MERGE round-trip → flagship query

### Add After Validation (Phase 3)

- [ ] Confidence-scored review queue + auto-accept policy
- [ ] Descent into Avernus ingest + RoT→DiA seam verification
- [ ] Blood War `Conflict` modeling
- [ ] Generalized extraction prompts/resolution

### Future Consideration (Phase 4+)

- [ ] Embeddings + hybrid retrieval (vector seed → graph walk) — Phase 4
- [ ] Live companion over read-only MCP — Phase 4
- [ ] Novel/EPUB parser profile + multi-edition batch ingest — Phase 5
- [ ] Contradiction detection + canon-tier query resolution — Phase 5
- [ ] GNNs (structural similarity, speculative link suggestion) — Phase 6

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| Gazetteer bootstrap | HIGH | MEDIUM | P1 |
| Idempotent loader (MERGE + provenance + verdicts) | HIGH | MEDIUM | P1 |
| Schema constraint gaps (`Item`, RELATION_DOMAINS guard) | HIGH | LOW | P1 |
| Content-hash idempotency / parse cache | HIGH | MEDIUM | P1 |
| Sourcebook parser triage | HIGH | HIGH | P1 |
| Pipeline orchestration + manifest I/O | HIGH | MEDIUM | P1 |
| Review sink (minimal) | MEDIUM | LOW | P1 |
| RoT ingested with provenance | HIGH | MEDIUM | P1 |
| Suspect-generator plausibility over RoT | HIGH | MEDIUM | P1 |
| Integration round-trip test | HIGH | LOW | P1 |
| Time-bounded fact stamping | MEDIUM | MEDIUM | P2 |
| Confidence-scored review queue (full) | MEDIUM | HIGH | P3 (Phase 3) |
| Embeddings / hybrid retrieval | HIGH | HIGH | P3 (Phase 4) |
| Contradiction detection | MEDIUM | HIGH | P3 (Phase 5) |
| GNNs | LOW | HIGH | P3 (Phase 6) |

**Priority key:** P1 = must have for this milestone · P2 = should have · P3 = deferred to a named later phase

## Sources

- Repo (HIGH — authoritative): `CLAUDE.md`, `PROJECT.md`, `PLAN.md`, `schema/lore_graph_schema.cypher`, `lore_graph/extraction.py`, stub contracts, `.planning/codebase/CONCERNS.md` + `ARCHITECTURE.md`, `data/manifest.json`, `pyproject.toml`
- PDF-parsing landscape (MEDIUM, June 2026): [OpenDataLoader vs Docling vs Marker vs PyMuPDF4LLM benchmark](https://docs.bswen.com/blog/2026-06-04-benchmark-comparison/), [Best Open-Source PDF-to-Markdown Tools 2026](https://themenonlab.blog/blog/best-open-source-pdf-to-markdown-tools-2026)
- KG ingestion idempotency/provenance (MEDIUM): [Idempotency in Data Pipelines (apxml)](https://apxml.com/courses/building-scalable-data-warehouses/chapter-3-high-throughput-ingestion/idempotency-pipelines)
- Neo4j MERGE semantics (HIGH): [MERGE — Cypher Manual](https://neo4j.com/docs/cypher-manual/current/clauses/merge/)

---
*Feature research for: D&D/Forgotten Realms lore knowledge-graph ingestion pipeline (first-ingest milestone)*
*Researched: 2026-06-15*
