# Codebase Concerns

**Analysis Date:** 2026-06-15

## Tech Debt

**Three of four pipeline modules are stubs — the system cannot ingest anything:**
- Issue: `loader.py`, `parsing.py`, and `pipeline.py` each consist of a docstring contract and a bare `raise NotImplementedError(...)`. No runnable code exists beyond the validation layer.
- Files: `lore_graph/loader.py`, `lore_graph/parsing.py`, `lore_graph/pipeline.py`
- Impact: The pipeline is entirely blocked. No source material can be ingested, no edges written to Neo4j, no gazetteer populated beyond the three seed entries in `extraction.py`'s demo block.
- Fix approach: Implement in priority order per PLAN.md: `loader.py` first (idempotent MERGE writer + review queue), then gazetteer bootstrap, then `parsing.py` (sourcebook profile), then `pipeline.py`.

**Gazetteer is not persisted or bootstrapped from the schema seed:**
- Issue: The `Gazetteer` class is in-memory only. The hand-seeded spine in `schema/lore_graph_schema.cypher` writes entities to Neo4j, but nothing loads those back into a `Gazetteer` instance at runtime. Every pipeline run starts with an empty gazetteer unless the caller manually calls `gaz.add(...)`.
- Files: `lore_graph/extraction.py` (Gazetteer class, ~lines 189–229), `schema/lore_graph_schema.cypher`
- Impact: Entity resolution silently fails on every canonical entity that should be resolvable (Tiamat, Severin, Cult of the Dragon, etc.) until the gazetteer is bootstrapped from Neo4j at startup. All their edges route to `QUEUE` or produce dangling-edge `REJECT`s instead of clean `ACCEPT`s.
- Fix approach: Add a `Gazetteer.load_from_neo4j(driver)` classmethod in `loader.py` or a dedicated `gazetteer.py` that queries `MATCH (n:Agent) RETURN n.id, labels(n), n.name, n.aliases` and populates the in-memory index.

**`__init__.py` is empty — package exposes nothing:**
- Issue: `lore_graph/__init__.py` contains no imports. Users must import directly from submodules (`from lore_graph.extraction import ...`).
- Files: `lore_graph/__init__.py`
- Impact: Low — the package still works. But the public surface is undefined and imports will change as modules are built, potentially breaking callers.
- Fix approach: Populate `__init__.py` with the stable public API once `loader.py` and `pipeline.py` are implemented.

**`data/manifest.json` has no implementation backing it:**
- Issue: The manifest lists sources with `"status": "pending"`. No code reads the manifest, updates it, or uses it to drive idempotency (content hashing is mentioned in `loader.py`'s contract but not implemented).
- Files: `data/manifest.json`
- Impact: The manifest is decorative until `pipeline.py` registers sources and `loader.py` implements the content-hash skip.
- Fix approach: Implement manifest read/write in `pipeline.py`. The existing structure (`id`, `status`, `canon_rank`) is adequate.

## Known Bugs

**`Gazetteer._norm` strips "the " anywhere in the string, not just as a leading article:**
- Symptoms: Any entity name containing the substring "the " (with a trailing space) loses characters mid-word.
- Files: `lore_graph/extraction.py` (~line 201): `return " ".join(s.lower().replace("the ", "").split())`
- Trigger: Any canonical name where "the " appears mid-string (e.g., "Lord of the Nine", "Athenaeum of Fire").
- Fix: Replace with a leading-article strip: `re.sub(r'^the\s+', '', s.lower()).strip()` or `s.lower().removeprefix("the ").strip()`.

**`Gazetteer.resolve` fuzzy-match runner-up tracking can spuriously flag ambiguity:**
- Symptoms: When iterating candidates, the runner-up is tracked without confirming it belongs to a *different* canonical entity. Two aliases for the same canonical entity can trigger a spurious `ambiguous=True`.
- Files: `lore_graph/extraction.py` (~lines 217–226)
- Trigger: A gazetteer with multiple aliases for the same entity where both score highly against the same mention.
- Fix: Track runner-up only when `cid != best_id`.

**`ValidatedEdge` stores the string `"None"` when an endpoint is dangling:**
- Symptoms: When a dangling edge is rejected, `sid`/`tid` is `None`; `str(sid)` yields the string `"None"` before being appended to the rejected edge's `source_id`/`target_id`.
- Files: `lore_graph/extraction.py` (~lines 313–315)
- Trigger: Any edge with a dangling source or target reference.
- Fix: Use `sid or ""` or make the field `Optional[str]`.

## Security Considerations

**Default password `change-me` hardcoded in `.mcp.json` (committed to the repo):**
- Risk: `.mcp.json` is committed to git with the Neo4j password in plaintext. Anyone who clones the repo and forgets to change it runs Neo4j with the publicly known default.
- Files: `.mcp.json`
- Current mitigation: `.env` is gitignored; the password in `.mcp.json` is only a dev default.
- Recommendations: Replace the hardcoded value with an environment variable reference (`"${NEO4J_PASSWORD}"`) and document the requirement in the README. Consider gitignoring `.mcp.json` or templating it like `.env.example`.

**`Makefile` schema target passes the Neo4j password as a shell argument:**
- Risk: `make schema` passes the password via `-p "$${NEO4J_PASSWORD:-change-me}"` as a command-line argument to `cypher-shell`. On Linux, process arguments are visible to all users via `/proc/<pid>/cmdline` and `ps aux`.
- Files: `Makefile`
- Current mitigation: Local dev only; acceptable for a single-user laptop.
- Recommendations: Use `cypher-shell`'s `--password-file` option or the `NEO4J_PASSWORD` env var it respects natively, removing the secret from args.

**LLM extraction has no API key validation:**
- Risk: If `ANTHROPIC_API_KEY` is unset, the `anthropic.Anthropic()` client construction succeeds but the first API call raises an `AuthenticationError` with no actionable message.
- Files: `lore_graph/extraction.py` (`extract_with_llm`)
- Current mitigation: None.
- Recommendations: Add an early guard that raises a clear error if `ANTHROPIC_API_KEY` is missing, or validate in the pipeline before any LLM calls.

## Performance Bottlenecks

**Gazetteer fuzzy resolution is O(n) over all known entity names — linear scan per mention:**
- Problem: `Gazetteer.resolve` iterates every entry computing `fuzz.token_sort_ratio`. At target scale (tens of thousands of entities), this becomes the ingestion bottleneck; each chunk may contain dozens of mentions.
- Files: `lore_graph/extraction.py` (~lines 216–226)
- Cause: No index on the fuzzy side; correct but naive MVP.
- Improvement path: Use `rapidfuzz.process.extractOne` with a cutoff (vectorized in C), or partition by first character / label type. Long-term: the embedding-similarity hook is the right answer at scale.

**PDF parsing (not yet implemented) is a known-hard performance problem:**
- Problem: Two-column RPG PDFs with stat blocks and sidebars scramble naive reading order. The triage approach (PyMuPDF4LLM fast pass → Marker `--use_llm` / Docling for hard pages) adds significant per-page latency.
- Files: `lore_graph/parsing.py` (stub), `pyproject.toml` (optional `parsing` group)
- Cause: Fundamental domain problem; not a code deficiency yet.
- Improvement path: Implement triage so only pages that fail quality checks escalate. Cache parse output by content-hash to avoid re-parsing unchanged pages.

## Fragile Areas

**`RELATION_DOMAINS` dict is the sole enforcement point — one missing entry is a `KeyError`:**
- Files: `lore_graph/extraction.py` (~lines 98–124, and lookup in `validate_batch`)
- Why fragile: `validate_batch` accesses `RELATION_DOMAINS[e.rel_type]` with no `.get()`/default. A new `RelType` without a matching entry raises an unhandled `KeyError` mid-batch, aborting validation for the whole batch. CLAUDE.md documents the convention but nothing enforces it.
- Safe modification: Always add the `RELATION_DOMAINS` entry in the same commit as a new `RelType`. Add a test asserting `set(RelType) == set(RELATION_DOMAINS.keys())`.

**Schema vocabulary is duplicated between Python enums and Cypher with no cross-validation:**
- Files: `lore_graph/extraction.py` (enums), `schema/lore_graph_schema.cypher`
- Why fragile: Node labels and relationship types must match between the Python enums and Cypher. No test or CI check compares them.
- Safe modification: Add a test that reads the schema file and asserts every `RelType`/`NodeLabel` value appears in the Cypher definitions.

**`Item` node type has no uniqueness constraint in the Cypher schema:**
- Files: `lore_graph/extraction.py` (`NodeLabel.ITEM`, `RESOLVABLE_LABELS`), `schema/lore_graph_schema.cypher`
- Why fragile: Constraints exist for `Agent`, `Location`, `Plane`, `Event`, `Goal`, `Prophecy`, `Conflict`, `Capability` — but not `Item`. Any MERGE on an `Item` without a constraint can silently create duplicates.
- Safe modification: Add `CREATE CONSTRAINT item_id IF NOT EXISTS FOR (n:Item) REQUIRE n.id IS UNIQUE;` to the schema.

**The RoT→DiA seam relationship in seed data is flagged as unverified:**
- Files: `schema/lore_graph_schema.cypher` (`// the RoT->DiA seam (verify specifics)`)
- Why fragile: This seam is the primary inter-book narrative hook. If the seed relationship is canonically wrong, abductive queries involving Tiamat's location produce incorrect results, invisibly, until cross-checked against the sourcebooks.
- Safe modification: Verify against the source texts before relying on query results. Flag the node/edge with `canon:'FORESHADOWED'` until confirmed.

## Scaling Limits

**In-memory Gazetteer does not survive process restarts:**
- Limit: All entity data must be re-loaded from Neo4j (or re-seeded manually) on every process start. At scale, cold-start load time becomes significant.
- Scaling path: Implement `Gazetteer.load_from_neo4j(driver)` and cache the populated instance; or back the gazetteer with a persistent index (e.g., SQLite FTS5).

**`max_tokens=4096` cap on LLM extraction may truncate dense chunks:**
- Limit: Densely populated sourcebook pages may require more output tokens; the API truncates silently and `model_validate` then fails or returns a partial result with no signal.
- Scaling path: Check `msg.stop_reason`; if `"max_tokens"`, split the chunk and re-extract. Consider raising `max_tokens`.

## Dependencies at Risk

**`rapidfuzz` degradation is silent if the import fails:**
- Risk: `extraction.py` wraps the import in `try/except ImportError` and falls back to exact-match-only resolution. If `rapidfuzz` is missing, fuzzy resolution silently disappears — any non-exact mention returns no hit.
- Impact: Mass dangling-edge rejections on nicknames/partial names/variant spellings. The pipeline appears to run but produces far fewer accepted edges.
- Migration plan: `rapidfuzz` is already a hard dependency in `pyproject.toml`; at minimum emit a prominent `warnings.warn` when the fallback path is taken.

**Heavy parsing dependencies are not version-pinned:**
- Risk: The optional `parsing` group lists `marker-pdf`, `docling`, `pymupdf4llm` with loose/no constraints. These are large, fast-moving packages with breaking releases.
- Migration plan: Add version floor constraints once the parsing implementation is underway.

## Missing Critical Features

**No content-hash idempotency — re-ingestion will duplicate:**
- Problem: The loader contract specifies content-hash skip, but no implementation exists. Running the pipeline twice on the same source will load all edges twice.
- Blocks: Reliable re-ingestion, safe re-runs after fixes, incremental source updates.

**No review queue — QUEUE verdicts have nowhere to go:**
- Problem: `validate_batch` produces `QUEUE`-verdicted edges, but `loader.py` is a stub. No storage, no review UI/CLI, no replay path.
- Blocks: Human-in-the-loop validation — the primary defense against hallucinated edges.

**No embedding step — hybrid retrieval (Phase 4) is unimplemented:**
- Problem: Node text-to-vector embedding (pipeline step 8) is required for hybrid retrieval (vector seed → graph walk). No embedding model is wired, no Neo4j vector index is populated.
- Blocks: The companion's primary retrieval path once `pipeline.py` exists.

**No contradiction detection — conflicting canon loads silently:**
- Problem: Contradiction detection across canon tiers is documented in the plan but has no implementation even as a stub.
- Blocks: Multi-edition ingestion (Phase 5), where contradiction handling becomes primary.

## Test Coverage Gaps

**Only four tests, all covering `Validator` happy-path + error cases:**
- What's not tested: Gazetteer fuzzy matching, alias normalization edge cases (the "the " bug above), `build_extraction_prompt` output shape, Pydantic field validation, `evidence` truncation validator, all three stub modules.
- Files: `tests/test_validation.py`
- Risk: The `Gazetteer._norm` "the " bug and the runner-up tracking bug are not caught by any test.
- Priority: Medium — the `Validator` is the most critical pure logic and is already tested; the `Gazetteer` bugs should be covered next.

**No integration tests for the extraction → Neo4j → query round-trip:**
- What's not tested: Whether validated edges survive a `MERGE` round-trip and can be retrieved by the flagship Cypher queries (A, B, C).
- Files: `tests/` (only one file exists)
- Risk: A schema constraint mismatch or property-name typo could silently fail at load time; pure validator tests would not catch it.
- Priority: High — add when `loader.py` is implemented.

---

*Concerns audit: 2026-06-15*
