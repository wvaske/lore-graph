# Pitfalls Research

**Domain:** RPG-sourcebook PDF → LLM-extraction → Neo4j graph ingestion (D&D / Forgotten Realms lore)
**Researched:** 2026-06-15
**Confidence:** HIGH for code-grounded pitfalls (read directly from `extraction.py`, stub contracts, `CONCERNS.md`); MEDIUM for external domain pitfalls (PyMuPDF reading-order, Neo4j MERGE cardinality, LLM coreference) — verified against official docs / issue trackers / arXiv and applied to this pipeline by reasoning.

This milestone ("First ingest", PLAN Phases 1–2) is exactly where lore-graph pipelines silently produce *plausible-looking but wrong* graphs. The recurring theme: **failures here are silent** — the pipeline runs green, loads edges, answers queries, but the answers are subtly fragmented, duplicated, or fabricated, and you only discover it when the suspect-generator returns nonsense or a re-run doubles the graph.

## Critical Pitfalls

### Pitfall 1: Empty gazetteer at runtime → every canonical entity fragments or dangles

**What goes wrong:** The `Gazetteer` is in-memory only and never loaded from Neo4j. The seeded spine + appendix NPCs are written to the graph but nothing reads them back. So "Severin" / "Cult of the Dragon" return no hit, get a `new::...` provisional id, and every edge touching them routes to QUEUE or dangles to REJECT. The graph fills with `new::person::severin` instead of the canonical node.

**Why it happens:** The seed-write path (Cypher → Neo4j) and the resolve-read path (Gazetteer in memory) were built at different times and never connected. The demo block calls `gaz.add(...)` by hand, masking the gap.

**How to avoid:** Build `bootstrap_gazetteer(driver)` as the *first* thing the pipeline does. Query resolvable labels and load id + name + every alias. Make the pipeline hard-error if the gazetteer comes back empty against a populated graph.

**Warning signs:** flood of `new::...` ids for seeded entities; QUEUE dominated by "touches a new entity that should resolve"; a canonical entity appearing as two nodes.

**Phase:** Phase 1 (gazetteer bootstrap), before any parsing.

---

### Pitfall 2: Non-idempotent writes → re-running a source doubles the graph

**What goes wrong:** No content-hash skip exists. Re-running RoT after a fix loads every relationship again; re-extraction mints fresh provisional ids and relationship MERGE with volatile properties in the pattern defeats dedup. The graph silently doubles, counts inflate, the suspect-generator over-weights duplicated goals.

**Why it happens:** Re-running during development is constant and assumed safe because "we use MERGE" — but MERGE only dedupes when the match pattern is fully specified and stable.

**How to avoid:** Two layers. (1) **Content-hash gate** — hash each chunk, record loaded hashes, skip unchanged. (2) **Stable MERGE keys** — MERGE nodes by canonical `id` only; MERGE relationships on `(type, source.id, target.id, valid_from)`; set provenance/confidence/evidence in `ON CREATE/ON MATCH SET`, never in the match pattern. Write the "ingest-twice-equals-once" test before the loader is "done".

**Warning signs:** counts grow on a re-run; duplicate relationships differing only in `confidence`/`evidence`.

**Phase:** Phase 1 (`loader.py` + manifest content-hash). The single highest-leverage correctness guarantee.

---

### Pitfall 3: Two-column reading-order corruption fabricates false adjacencies

**What goes wrong:** PyMuPDF emits text in PDF-creation order, not human reading order. On a two-column page with stat blocks and sidebars, columns interleave line-by-line and sidebars inject into body prose. The LLM sees "Severin commands… [sidebar about a different NPC]… the assassins" as one passage and extracts a false `COMMANDS` edge that *passes validation* because both endpoints resolve.

**Why it happens:** The fast extractor "works" — produces readable-looking text, no error. The corruption is invisible unless you diff against the rendered page.

**How to avoid:** Use block-level extraction with positional sort (`get_text("blocks")` sorted by column then y) as the fast pass — not raw `get_text()`. Add a per-page **quality check** (detect interleaving via x-gaps / broken sentences) and **escalate failing pages to Marker `--use_llm`/Docling**. Treat stat-block and sidebar regions as separate chunks. Tune on RoT's actual layout (Phase 2 says "tune the parser profile on its two-column layout" — that tuning *is* the fix).

**Warning signs:** prose with sentences that switch topic mid-line; edges between entities the source never connects; a sidebar NPC in body-NPC relationships.

**Phase:** Phase 2 (`parsing.py` + per-page quality gate + escalation). Do not skip the quality check to save time.

---

### Pitfall 4: Entity-resolution fragmentation — "Severin" / "Severin Silrajin" / "the cult leader" become three nodes

**What goes wrong:** The same character appears as full name, short name, epithet, and pronouns. Without collapse, goals attach to one node, command edges to another, the epithet dangles or mints a third. Queries walking from the canonical node silently miss half his edges; the suspect-generator under-counts his motive.

**Why it happens:** Three compounding causes — (a) the gazetteer bug above; (b) `Gazetteer._norm` strips "the " *anywhere* in the string, so "Lord of the Nine" → "Lord of Nine"; (c) epithets/pronouns are *coreference*, which fuzzy string matching cannot resolve.

**How to avoid:** (1) Fix `_norm` to strip only a *leading* article: `re.sub(r'^the\s+', '', s.lower()).strip()`. (2) Bootstrap the gazetteer and **seed aliases/epithets explicitly** ("the cult leader" → Severin, "the Dragon Queen" → Tiamat). (3) **Pass relevant gazetteer names into the extraction prompt as hints** so the LLM resolves coreference at extraction time. (4) Keep the `ambiguous` → QUEUE path so genuine ties get human eyes.

**Warning signs:** multiple nodes whose names are substrings/epithets of each other; an NPC with suspiciously few edges; epithet/pronoun-derived nodes existing at all.

**Phase:** Phase 1 (`_norm` fix + alias seeding) + Phase 2 (prompt-hint coreference + manual review). The `_norm` fix is one line and must ship before any ingest.

---

### Pitfall 5: Provenance / canon discipline lapses — unstamped edges are debt you can't pay down

**What goes wrong:** An edge enters without `source`/`canon`/`edition`, or the LLM invents provenance. Once unattributed edges mix with attributed ones, you cannot retroactively recover which book a fact came from. At scale this collapses the canon-tier resolution model.

**Why it happens:** During first ingest of a single book it feels harmless (everything is RoT/PUBLISHED/5e). Then DiA arrives and the un-tiered RoT edges can't participate in resolution. Also tempting: letting the LLM emit `source` — but it hallucinates page numbers.

**How to avoid:** The pipeline stamps provenance; the LLM never does (decision #4). Enforce at load time: the loader **rejects any edge lacking source/canon/edition**. Carry section+page provenance into every chunk at parse time. Keep evidence <25 words. Flag the unverified RoT→DiA seam edge as `FORESHADOWED` until checked.

**Warning signs:** any node/edge with null `source`/`canon`; nonexistent page numbers; the seam edge still PUBLISHED without verification.

**Phase:** Phase 1 (loader enforces) + Phase 2 (parser carries page). Make "load an unstamped edge" a test that must fail.

---

### Pitfall 6: `RELATION_DOMAINS` KeyError aborts the whole batch

**What goes wrong:** `validate_batch` does `RELATION_DOMAINS[e.rel_type]` with no `.get()` guard. Add a `RelType` without its domain entry and validation raises an unhandled `KeyError` mid-batch — the *entire* batch is lost, not just the bad edge.

**How to avoid:** Add a module-load assertion `assert set(RelType) == set(RELATION_DOMAINS.keys())` (fail fast at import) + the matching test. Defensively, `RELATION_DOMAINS.get(...)` → REJECT that one edge rather than crashing the batch.

**Warning signs:** `KeyError` naming a `RelType`; a batch that extracted fine but produced zero validated edges.

**Phase:** Phase 1 (cheap guard + test, alongside the loader).

---

### Pitfall 7: Missing `Item` uniqueness constraint → silent MERGE duplicates

**What goes wrong:** The schema constrains Agent/Location/Plane/Event/Goal/Prophecy/Conflict/Capability — but **not Item** (a valid resolvable target: the Draakhorn, dragon masks). `MERGE (n:Item {id:...})` without a constraint can create duplicates under concurrent/rapid writes (confirmed in Neo4j's issue tracker) → fragmented edges, invisible because it's the loader's fault not resolution's.

**How to avoid:** Add `CREATE CONSTRAINT item_id IF NOT EXISTS FOR (n:Item) REQUIRE n.id IS UNIQUE;`. Better: a test asserting every `RESOLVABLE_LABELS` label has a uniqueness constraint in the Cypher file.

**Warning signs:** duplicate Item nodes with the same name/id; constraint count < resolvable-label count.

**Phase:** Phase 1 (schema fix + enum-vs-constraint cross-check). Must precede any Item-bearing ingest.

---

### Pitfall 8: Silent LLM truncation drops the densest extractions

**What goes wrong:** `extract_with_llm` caps `max_tokens=4096`. A dense RoT page (appendix NPC list, faction roster) overflows; the API truncates silently; `model_validate` fails or returns a *partial* result with no signal. The richest pages lose the most data.

**How to avoid:** Check `msg.stop_reason`; if `"max_tokens"`, split the chunk and re-extract (idempotency + MERGE dedupes the overlap). Log a warning. Consider raising `max_tokens`. Pair with structure-aware chunking.

**Warning signs:** `stop_reason == "max_tokens"`; appendix/roster pages yielding far fewer entities than they contain; Pydantic errors on long pages only.

**Phase:** Phase 2 (pipeline wires extraction over real chunks).

## Technical Debt Patterns

| Shortcut | Long-term Cost | When Acceptable |
|----------|----------------|-----------------|
| Hand-call `gaz.add()` instead of `load_from_neo4j` | Production runs start empty; mass fragmentation | Never — bootstrap is the point of Phase 1 |
| Skip content-hash, "clear the DB between runs" | Re-runs double; no incremental updates | Never for a MERGE pipeline |
| Raw `get_text()` instead of block/column-aware | Reading-order corruption → false edges that pass validation | OK only for single-column novel prose later |
| Let the LLM emit `source`/page | Hallucinated provenance pollutes the canon-tier system irreversibly | Never — violates decision #4 |
| Stamp everything `PUBLISHED` without verifying the RoT→DiA seam | Abductive queries on Tiamat's location silently wrong | Only if the seam edge is `FORESHADOWED` until verified |
| Skip the per-page quality gate | No page escalates → silent corruption on hard pages | Never — the gate is what makes triage real |
| Loose `marker-pdf`/`docling`/`pymupdf4llm` versions | Breaking releases silently change reading-order behavior | Only until parsing is implemented; pin a floor before Phase 2 ships |

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| Neo4j MERGE | Volatile props in the MERGE pattern → new edge every run; trusting MERGE without a constraint | MERGE on stable identity only; set props in `ON CREATE/ON MATCH SET`; back every resolvable label with a uniqueness constraint |
| Neo4j writes via MCP | Writing through the read-only MCP server | Python bolt driver owns all writes; MCP read-only |
| Neo4j concurrent MERGE | Parallel sessions MERGE the same node and duplicate | Single-writer ingestion; rely on constraints; batch via `UNWIND` in one transaction |
| Anthropic | Client construction succeeds with no key; first call throws opaque `AuthenticationError` mid-ingest | Validate `ANTHROPIC_API_KEY` before any LLM call; fail fast |
| Anthropic | Ignoring `stop_reason` → silent truncation | Check `stop_reason == "max_tokens"`, split+re-extract |
| PyMuPDF | Assuming `get_text()` returns reading order | Block extraction + positional sort or multi-column detection; quality-gate and escalate |
| rapidfuzz | Silent fallback to exact-match-only if import fails | Already a hard dep; emit a loud `warnings.warn` on the fallback path |
| `data/manifest.json` | Treating it as decorative | Pipeline reads+writes it; it's the idempotency ledger |

## Performance Traps

| Trap | Prevention | When It Breaks |
|------|------------|----------------|
| O(n) gazetteer fuzzy scan per mention | `rapidfuzz.process.extractOne` with cutoff; partition by label; embedding hook at scale | Fine for one book; bottleneck at tens of thousands of entities (Phase 5) |
| Re-parsing unchanged PDF pages every run | Cache parse output by content-hash; escalate only failing pages | Noticeable from the first re-run |
| Marker `--use_llm` / Docling on every page | Triage: fast pass, escalate only failing pages | Breaks as soon as you stop escalating selectively |
| `max_tokens=4096` on dense pages | Stop-reason check + chunk splitting | Dense appendix/roster pages, immediately |

For the *first ingest* (one book, manually reviewable), correctness — not raw scale — is the binding constraint. Don't over-optimize the O(n) gazetteer now; do implement parse caching (dev re-runs are frequent).

## Security Mistakes

| Mistake | Risk | Prevention |
|---------|------|------------|
| Default password `change-me` committed in `.mcp.json` | Cloners run Neo4j with a known password | Reference `${NEO4J_PASSWORD}`; template `.mcp.json` like `.env.example` |
| `make schema` passes password as a CLI arg to `cypher-shell` | Visible via `/proc/<pid>/cmdline`, `ps aux` | Use `--password-file` or the env var `cypher-shell` reads natively |
| Committing `data/sources/` | Copyright violation | Keep gitignored; evidence spans <25 words |

Local-dev-acceptable today but fix before sharing the repo or exposing the MCP server beyond localhost.

## "Looks Done But Isn't" Checklist

- [ ] **Idempotent loader:** verify by ingesting RoT twice and asserting identical counts (not just "MERGE is used").
- [ ] **Gazetteer bootstrap:** verify `load_from_neo4j` populates from the seed and the pipeline errors on an empty gazetteer.
- [ ] **Two-column parser:** verify hard RoT pages escalate and reading order matches the rendered page on a spot-check.
- [ ] **Coreference resolution:** verify "the cult leader" + name variants of Severin all resolve to one node; `_norm` fix landed.
- [ ] **Provenance stamping:** verify the loader *rejects* an edge with null source/canon/edition; no LLM-invented page numbers.
- [ ] **RELATION_DOMAINS completeness:** verify the `set(RelType)==set(RELATION_DOMAINS)` test + import assertion.
- [ ] **Item constraint:** verify a uniqueness constraint exists for every `RESOLVABLE_LABELS` label.
- [ ] **Review-queue sink:** verify QUEUE verdicts land somewhere replayable, not `/dev/null`.
- [ ] **Truncation handling:** verify `stop_reason` is checked and dense pages split.
- [ ] **Suspect-generator (Query B):** verify on reviewed RoT data that surfaced agents' goals genuinely align with the event, with traceable reasons.

## Pitfall-to-Phase Mapping

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| Empty gazetteer / no bootstrap | Phase 1 | Pipeline errors on empty gazetteer; seeded entities resolve, no `new::` for known entities |
| Non-idempotent writes | Phase 1 | Ingest RoT twice → identical counts |
| `_norm` "the " mid-string strip | Phase 1 | "Lord of the Nine" normalizes without losing chars |
| Entity-resolution fragmentation / coreference | Phase 1 (aliases) + Phase 2 (prompt hints, review) | Severin variants + "the cult leader" → one node |
| RELATION_DOMAINS KeyError | Phase 1 | `set(RelType)==set(RELATION_DOMAINS)` test passes; import asserts |
| Missing Item constraint | Phase 1 | Every `RESOLVABLE_LABELS` label has a uniqueness constraint |
| Provenance/canon discipline | Phase 1 (loader) + Phase 2 (parser) | Loader rejects unstamped edge; no null source/canon |
| Two-column reading-order corruption | Phase 2 | Hard pages escalate; reading order matches rendered page |
| Silent LLM truncation | Phase 2 | `stop_reason` checked; dense pages split |
| RoT→DiA seam unverified | Phase 1 seed / Phase 2 review | Seam edge marked `FORESHADOWED` until source-verified |

## Sources

- **Internal (HIGH):** `PROJECT.md`, `CLAUDE.md` (Gotchas), `PLAN.md` (Known hard parts), `.planning/codebase/CONCERNS.md`, `lore_graph/extraction.py`, `loader.py`/`parsing.py` stubs.
- **Neo4j MERGE duplication (MEDIUM):** [neo4j/neo4j #3437](https://github.com/neo4j/neo4j/issues/3437); [#12674](https://github.com/neo4j/neo4j/issues/12674); [neo4j-java-driver #239](https://github.com/neo4j/neo4j-java-driver/issues/239).
- **PDF two-column reading order (MEDIUM):** [PyMuPDF — Common Issues](https://pymupdf.readthedocs.io/en/latest/recipes-common-issues-and-their-solutions.html); [Extract Text From a Multi-Column Document Using PyMuPDF](https://medium.com/@pymupdf/extract-text-from-a-multi-column-document-using-pymupdf-in-python-a0395ebc8e28).
- **LLM coreference / fragmentation (MEDIUM):** [Coreference-Resolved KGs (arXiv 2510.26486)](https://arxiv.org/pdf/2510.26486); [Constructing KGs from text (LangChain)](https://blog.langchain.com/constructing-knowledge-graphs-from-text-using-openai-functions/); [Text to KG pipeline (Neo4j)](https://neo4j.com/blog/genai/text-to-knowledge-graph-information-extraction-pipeline/).

---
*Pitfalls research for: RPG-PDF → LLM-extraction → Neo4j graph ingestion (lore-graph "First ingest" milestone)*
*Researched: 2026-06-15*
