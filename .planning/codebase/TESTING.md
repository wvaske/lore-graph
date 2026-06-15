# Testing Patterns

**Analysis Date:** 2026-06-15

## Test Framework

**Runner:**
- pytest `>=8` (specified in `[project.optional-dependencies]` dev group, `pyproject.toml`)
- No `pytest.ini`, `setup.cfg`, or `[tool.pytest]` section — pytest runs with defaults
- Config: none (default discovery)

**Assertion Library:**
- pytest's built-in `assert` statements only — no third-party assertion library

**Run Commands:**
```bash
make test          # pip install -e . -q && pytest -q
pytest -q          # run directly after installing
```

## Test File Organization

**Location:**
- Separate `tests/` directory at repo root: `tests/test_validation.py`
- Not co-located with source modules

**Naming:**
- Test files: `test_<module_or_concern>.py`
- Test functions: `test_<what_is_being_verified>()` — descriptive snake_case names

**Structure:**
```
tests/
  test_validation.py    # tests for lore_graph/extraction.py Validator (pure layer)
```

## Test Structure

**Suite Organization:**

Tests are flat functions (no class wrappers). Module-level constants and private helper functions provide shared fixtures.

```python
# Module-level constant for shared context
CTX = SourceContext("test", CanonTier.MY_CANON, "5e", canon_rank=1)

# Private helper functions return fresh objects (not pytest fixtures)
def _gaz() -> Gazetteer:
    g = Gazetteer()
    g.add("cult_dragon", NodeLabel.ORGANIZATION, ["Cult of the Dragon", "the Cult"])
    g.add("severin", NodeLabel.PERSON, ["Severin Silrajin", "Severin"])
    g.add("goal_free_tiamat", NodeLabel.GOAL, ["Free Tiamat"])
    return g

def _batch() -> ExtractionResult:
    return ExtractionResult(nodes=[...], edges=[...])

def test_valid_edges_accept():
    kept, _ = Validator(_gaz()).validate_batch(_batch(), CTX)
    accepted = [e for e in kept if e.verdict is Verdict.ACCEPT]
    rels = {e.rel_type for e in accepted}
    assert rels == {RelType.INSTIGATED_BY, RelType.THREATENS}
```

**Patterns:**
- Each test constructs objects directly — no mocking, no external dependencies
- Tests call `_gaz()` and `_batch()` (or inline equivalents) to get fresh state per test
- Results are unpacked into `kept, _` or `_, rejected` to focus assertions on one side
- Verdict routing is validated with `is` identity check: `e.verdict is Verdict.ACCEPT`

## Mocking

**Framework:** None — no mocking library used (no `unittest.mock`, no `pytest-mock`)

**Strategy:** The `Validator` is kept pure (no I/O, no network, no DB), so all tests run against real objects with no mocking required. This is a core architectural constraint documented in `CLAUDE.md`: "Keep `Validator` pure. No I/O, no network. Test it directly."

**What to Mock:**
- `extract_with_llm` in `lore_graph/extraction.py` is the single LLM boundary. When tests for the pipeline (`pipeline.py`) are written, this is the only function that needs mocking — inject a fake `ExtractionResult` instead.
- Neo4j bolt calls (not yet implemented) — mock the driver when writing `loader.py` tests.

**What NOT to Mock:**
- `Validator`, `Gazetteer`, `ExtractionResult`, `ExtractedNode`, `ExtractedEdge` — always test these with real instances. They are pure and cheap to construct.

## Fixtures and Factories

**Test Data Pattern:**

Private helper functions (prefixed with `_`) construct shared test data. They are called fresh per test, not shared as module-level instances (preventing cross-test state).

```python
def _gaz() -> Gazetteer:
    """Returns a fresh Gazetteer seeded with canonical test entities."""
    g = Gazetteer()
    g.add("cult_dragon", NodeLabel.ORGANIZATION, ["Cult of the Dragon", "the Cult"])
    g.add("severin", NodeLabel.PERSON, ["Severin Silrajin", "Severin"])
    g.add("goal_free_tiamat", NodeLabel.GOAL, ["Free Tiamat"])
    return g
```

**Inline Batch Construction:**

For tests that need a specific scenario not covered by `_batch()`, construct `ExtractionResult` inline within the test function. See `test_low_confidence_unknown_org_routes_to_review` in `tests/test_validation.py` for the pattern.

**Location:**
- Fixtures are private functions in the same test file — no `conftest.py` yet

## Coverage

**Requirements:** None enforced (no coverage plugin configured, no minimum threshold)

**View Coverage:**
```bash
pytest --cov=lore_graph   # requires pytest-cov (not currently in dev deps)
```

Note: `pytest-cov` is not in `pyproject.toml` dev dependencies. Add `pytest-cov` to dev extras before running coverage reports.

## Test Types

**Unit Tests:**
- All current tests are pure unit tests for `lore_graph/extraction.py`'s `Validator`
- Scope: one module, no external dependencies, no network, no DB
- Location: `tests/test_validation.py`

**Integration Tests:**
- Not yet written. Will be needed for `loader.py` (Neo4j MERGE paths) and `pipeline.py` (end-to-end ingest)
- These will require a live or Docker Neo4j instance; scope to a separate file `tests/test_loader.py` / `tests/test_pipeline.py`

**E2E Tests:**
- Not used. The `make extract-demo` target (`python -m lore_graph.extraction`) serves as a manual smoke test for the extraction + validation path without network.

## Common Patterns

**Testing a Routing Decision (ACCEPT / QUEUE / REJECT):**
```python
def test_valid_edges_accept():
    kept, _ = Validator(_gaz()).validate_batch(_batch(), CTX)
    accepted = [e for e in kept if e.verdict is Verdict.ACCEPT]
    rels = {e.rel_type for e in accepted}
    assert rels == {RelType.INSTIGATED_BY, RelType.THREATENS}
```

**Testing Rejection with Reason String:**
```python
def test_type_violation_rejected():
    _, rejected = Validator(_gaz()).validate_batch(_batch(), CTX)
    bad = [e for e in rejected if e.rel_type is RelType.PURSUES]
    assert bad and any("must be {Goal}" in r for r in bad[0].reasons)

def test_dangling_edge_rejected():
    _, rejected = Validator(_gaz()).validate_batch(_batch(), CTX)
    bad = [e for e in rejected if e.rel_type is RelType.ALLIED_WITH]
    assert bad and any("dangling" in r for r in bad[0].reasons)
```

**Testing QUEUE Routing for Unresolved Entities:**
```python
def test_low_confidence_unknown_org_routes_to_review():
    batch = ExtractionResult(
        nodes=[
            ExtractedNode(temp_id="o1", label=NodeLabel.ORGANIZATION, name="The Unseen Hand"),
            ExtractedNode(temp_id="g1", label=NodeLabel.GOAL, name="Free Tiamat"),
        ],
        edges=[ExtractedEdge(rel_type=RelType.PURSUES, source_ref="o1", target_ref="g1", confidence=0.95)],
    )
    kept, _ = Validator(_gaz()).validate_batch(batch, CTX)
    assert kept and kept[0].verdict is Verdict.QUEUE
```

## Key Files

- `tests/test_validation.py` — all current tests (4 test functions)
- `lore_graph/extraction.py` — the pure `Validator` class under test
- `Makefile` — `make test` runs `pip install -e . -q && pytest -q`
- `pyproject.toml` — dev dependencies: `pytest>=8`, `ruff>=0.5`

---

*Testing analysis: 2026-06-15*
