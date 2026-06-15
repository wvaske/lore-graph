# Project Research Summary

**Project:** Lore Graph
**Domain:** RPG-sourcebook PDF → schema-constrained LLM extraction → Neo4j 5 property-graph ingestion pipeline (closed-world, provenance-first)
**Researched:** 2026-06-15
**Confidence:** HIGH

## Executive Summary

Lore Graph's integrity-critical layer — controlled vocabulary, the pure `Validator` (dangling-edge rejection, type-matrix, ACCEPT/QUEUE/REJECT routing), and the `extract_with_llm` boundary — is already built and tested. This milestone ("first ingest", PLAN Phases 1–2) is therefore not about *inventing* trust; it is about **wiring trust into the write/ingest path**: an idempotent Neo4j loader, a gazetteer bootstrapped from the graph, a two-column sourcebook PDF parser, and an orchestration pipeline — then ingesting Rise of Tiamat end-to-end so the suspect-generator (Query B) returns plausible, traceable results.

Research converged on three things the roadmap must respect. First, the **gazetteer bootstrap is the lynchpin**: the gazetteer is in-memory and starts empty every run, so even canonical entities (Tiamat, Severin) fail to resolve and their edges fragment to QUEUE/REJECT — nothing downstream works until `bootstrap_gazetteer(driver)` exists. Second, **idempotency has a hidden hard dependency**: Neo4j MERGE only dedupes with a uniqueness constraint backing the merge key, and `Item` has no constraint — ship the constraint with the loader or items silently duplicate. Third, the **PDF parsing track is the one genuinely hard, high-variance problem**: PyMuPDF emits PDF-creation order (not reading order), so two-column pages with stat blocks and sidebars fabricate false adjacencies that *pass validation*. The fix is a per-page quality gate that escalates only hard pages to Marker `--use_llm`/Docling.

The dominant risk class is **silent correctness failure** — the pipeline runs green but produces fragmented, duplicated, or fabricated edges. Mitigation is front-loaded: the integrity guards (bootstrap, content-hash idempotency, schema-constraint fixes, provenance enforcement) land in the first phase; reading-order correctness and truncation handling land in the parsing/pipeline phase; and the "review all RoT edges manually" gate is the only real backstop against reading-order false edges, so it must be a hard exit criterion.

## Key Findings

### Recommended Stack

The core stack is settled (Python 3.11+, Pydantic v2, Neo4j 5 Community, Anthropic forced-tool-use, rapidfuzz) and was not relitigated. Research answered the two open questions — the parsing toolchain and the idempotent write path — and was prescriptive about what *not* to add. Full detail in `STACK.md`.

**Core technologies:**
- `pymupdf4llm>=1.27,<2`: fast first-pass PDF extraction (per-page Markdown + bbox metadata) — handles the easy 80%+ of pages; the triage engine.
- `marker-pdf>=1.10,<2` (`use_llm`): layout-aware escalation parser — best two-column reading-order reconstruction; runs *only* on hard pages. `docling` is an opt-in third tier.
- `neo4j>=5.18,<6` (pin 5.28.x): all writes via `UNWIND $rows ... MERGE` + `apoc.merge.relationship` for dynamic rel types. **Stay on the 5.x driver line** for a Neo4j 5 server (the 6.x driver is for a 6.x server).
- `hashlib` (stdlib): content-hash chunk idempotency via `:Chunk {content_hash}`.

**Explicit "do not use":** LlamaIndex `PropertyGraphIndex`/`SchemaLLMPathExtractor` (its `strict` is best-effort, not the pure closed-world Validator; it wants to own writes and treats provenance as optional — it fights this design); a separate vector DB; the 6.x driver on a 5.x server; `CREATE`; string-interpolated Cypher; one parser for both sourcebooks and novels; `instructor` (extraction is solved).

### Expected Features

Detail in `FEATURES.md`. Framed around the ingest-and-query-by-Cypher slice (the live companion is OUT).

**Must have (table stakes — the graph is untrustworthy without these):**
- Idempotent load (`MERGE`, never `CREATE`) + content-hash chunk skip
- Provenance enforcement at load time (refuse to write an unstamped edge)
- Gazetteer bootstrap from Neo4j (resolution fails without it)
- Sourcebook PDF parsing with quality-gated triage
- Review sink for QUEUE verdicts (minimal `:ReviewItem`, not a UI)
- End-to-end idempotent pipeline orchestration + manifest I/O
- Flagship queries validated against real RoT data (integration round-trip test)

**Should have (differentiators — uniquely enabled by the settled model):**
- Suspect-generator (abductive Query B) returning *plausible* results — the headline DoD
- Reified-event time model + canon-tier/edition axis (plumbing now; exercised at scale)
- Time-bounded state facts (`valid_from`/`valid_to`)

**Defer (named later phases):** hybrid vector retrieval + live companion (Phase 4); contradiction resolution, novels, multi-edition (Phase 5); GNNs (Phase 6); DiA + Blood War + full review-queue UX (Phase 3).

### Architecture Approach

Detail in `ARCHITECTURE.md`. No restructuring — fill three stubs plus one new bootstrap function. The settled contract is register → parse → resolve → extract → validate → load. The single load-bearing integration fact: the `Validator` is pure and the `Gazetteer` is in-memory, so the **read-only gazetteer bootstrap is the bridge that makes closed-world validation work** without violating purity.

**Major components (new this milestone):**
1. `bootstrap_gazetteer(driver)` — read-only Neo4j → in-memory hydration (lives in `loader.py`; keeps `neo4j` out of `extraction.py`).
2. `loader.py` — the only write path: MERGE-by-id + relationship, provenance/time-bound stamping, verdict routing (ACCEPT→graph, QUEUE→`:ReviewItem`, REJECT→log), content-hash idempotency.
3. `parsing.py` — `Chunk` dataclass + sourcebook profile with PyMuPDF4LLM→Marker triage (pure text transform; novel/wiki profiles `raise NotImplementedError`).
4. `pipeline.py` — orchestrator; mints the single `SourceContext` from the manifest, threads the bootstrapped gazetteer, updates manifest status.

### Critical Pitfalls

Top 5 of 8 from `PITFALLS.md` (all silent failures):

1. **Empty gazetteer at runtime** → every canonical entity fragments/dangles. Avoid: `bootstrap_gazetteer` first; hard-error on empty gazetteer against a populated graph.
2. **Non-idempotent writes** → re-running RoT doubles the graph. Avoid: content-hash skip + stable MERGE keys (props in `ON CREATE/ON MATCH SET`, never in the match pattern); ingest-twice-equals-once test.
3. **Two-column reading-order corruption** → fabricated edges that pass validation. Avoid: block/column-aware extraction + per-page quality gate + escalation; manual review of all RoT edges.
4. **Entity-resolution fragmentation / coreference** ("Severin" / "Severin Silrajin" / "the cult leader"). Avoid: fix `_norm` (leading-article strip only), seed aliases/epithets, pass gazetteer hints into the prompt.
5. **Provenance discipline lapse** → unstamped edges are unrecoverable debt. Avoid: loader rejects any edge lacking source/canon/edition; LLM never mints provenance.

Plus: `RELATION_DOMAINS` KeyError aborts a batch (add `set(RelType)==set(RELATION_DOMAINS)` guard); missing `Item` uniqueness constraint (silent MERGE dupes); silent LLM truncation at `max_tokens=4096` on dense pages (check `stop_reason`).

## Implications for Roadmap

Research strongly suggests a structure mirroring the dependency-driven build order: an **integrity-foundation phase** (graph-write track) running before/parallel to a **parsing phase** (text track), converging in an **end-to-end ingest phase**. At Coarse granularity this is ~3–4 phases.

### Phase 1: Schema hardening + gazetteer bootstrap + idempotent loader
**Rationale:** This is the integrity foundation and the critical path. The loader can be exercised against the *existing* `ValidatedEdge` output with no parser or LLM, so it lands first and immediately unblocks the highest-priority test gap (extraction→Neo4j→query round-trip). The gazetteer bootstrap is the lynchpin every later phase depends on.
**Delivers:** `bootstrap_gazetteer(driver)`; idempotent `loader.py` (MERGE + provenance stamping + verdict routing + `:ReviewItem` sink + content-hash `:Chunk` skip); schema fixes (`Item` constraint, enum-vs-constraint cross-check, `_norm` leading-article fix, `RELATION_DOMAINS` guard); integration round-trip test.
**Addresses:** idempotency, provenance enforcement, gazetteer bootstrap, review sink (table stakes).
**Avoids:** Pitfalls 1, 2, 4 (partial), 5, 6, 7.

### Phase 2: Sourcebook PDF parser (two-column triage)
**Rationale:** Independent of the graph-write path — pure text-in/`Chunk`-out — so it can proceed in parallel, but it is the highest-variance work and most likely to need deeper per-phase research.
**Delivers:** `Chunk` dataclass + `parse(path, "sourcebook")` with PyMuPDF4LLM fast pass, per-page quality gate, and Marker `--use_llm`/Docling escalation; parse-output caching by content-hash.
**Uses:** `pymupdf4llm`, `marker-pdf`, `PyMuPDF` geometry for the difficulty scorer.
**Avoids:** Pitfall 3 (reading-order corruption); the parse-cache performance trap.

### Phase 3: End-to-end pipeline + Rise of Tiamat ingest + suspect-generator validation
**Rationale:** Pure glue that converges the two tracks; can only be meaningfully built/tested once both exist. Closes the milestone against PLAN's "done-when".
**Delivers:** `pipeline.py` (`ingest(source_id)`, manifest I/O, single `SourceContext`, per-chunk loop with truncation handling); RoT ingested with provenance, all edges manually reviewed; Query B returns plausible, traceable suspects.
**Avoids:** Pitfall 8 (silent truncation); validates the manual-review backstop.

### Phase Ordering Rationale
- **Dependency-driven:** loader+bootstrap unblock everything and are testable against existing output → build first. Parser is fully independent → parallel. Pipeline is glue → last. RoT ingest needs all of the above → closes the milestone.
- **Risk-front-loaded:** all integrity guards land in Phase 1; the one hard/uncertain problem (PDF reading order) is isolated to Phase 2 where it can't block the write path.
- **Avoids the silent-failure class** by making idempotency, provenance, and resolution preconditions rather than afterthoughts.

### Research Flags
Phases likely needing deeper research during planning:
- **Phase 2 (parser):** two-column reading-order is the genuinely hard problem; the difficulty-score threshold and the Marker `use_llm` backend choice (Gemini API vs local Ollama) are empirical decisions requiring hands-on calibration on the RoT PDF.

Phases with standard patterns (can skip research-phase):
- **Phase 1 (loader/bootstrap):** canonical Neo4j `UNWIND`/`MERGE` idioms; well-documented, low uncertainty.
- **Phase 3 (pipeline):** glue over already-verified contracts.

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | Versions verified against PyPI/official docs; MEDIUM only on empirical triage thresholds |
| Features | HIGH | Grounded in repo's settled decisions, schema, Validator code, CONCERNS.md |
| Architecture | HIGH | Derived directly from implemented contracts + documented stub contracts |
| Pitfalls | HIGH (code-grounded) / MEDIUM (external domain) | Five concrete CONCERNS.md bugs elevated to actionable pitfalls |

**Overall confidence:** HIGH

### Gaps to Address
- **PDF triage threshold + Marker backend:** empirical; calibrate on ~10 known-hard RoT pages during Phase 2 planning.
- **Time-bounded MERGE key:** decide whether a state-fact relationship's merge identity includes `valid_from` (else re-runs overwrite history) — resolve when designing `loader.py`.
- **DR-year provenance for state facts:** where `valid_from`/`valid_to` values originate (LLM attribute? manual seed?) is unpinned — needs a Phase 1/3 decision.
- **"Plausible suspects" acceptance bar:** the DoD is qualitative — define a concrete exit checklist (a known RoT instigator surfaces with correct motive+means) so Phase 3 has an objective test.

## Sources

### Primary (HIGH confidence)
- Repo: `CLAUDE.md`, `PLAN.md`, `PROJECT.md`, `schema/lore_graph_schema.cypher`, `lore_graph/extraction.py`, stub contracts, `.planning/codebase/*` — authoritative for settled design and contracts.
- [PyPI: neo4j](https://pypi.org/project/neo4j/), [Neo4j Python Driver Manual — Performance](https://neo4j.com/docs/python-manual/current/performance/), [Cypher MERGE Manual](https://neo4j.com/docs/cypher-manual/current/clauses/merge/) — driver version + idempotent write idioms.
- [PyPI: marker-pdf](https://pypi.org/project/marker-pdf/), [PyMuPDF4LLM API docs](https://pymupdf.readthedocs.io/en/latest/pymupdf4llm/api.html) — parsing toolchain.

### Secondary (MEDIUM confidence)
- [Best Open-Source PDF-to-Markdown Tools 2026](https://themenonlab.blog/blog/best-open-source-pdf-to-markdown-tools-2026); PDF-parsing benchmarks — tool comparison.
- Neo4j issue tracker ([#3437](https://github.com/neo4j/neo4j/issues/3437), [#12674](https://github.com/neo4j/neo4j/issues/12674)) — MERGE-without-constraint duplication.
- [Coreference-Resolved KGs (arXiv 2510.26486)](https://arxiv.org/pdf/2510.26486) — coreference needs prompt-time resolution.

---
*Research completed: 2026-06-15*
*Ready for roadmap: yes*
