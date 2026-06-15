# Coding Conventions

**Analysis Date:** 2026-06-15

## Naming Patterns

**Files:**
- `snake_case.py` for all module files: `extraction.py`, `loader.py`, `parsing.py`, `pipeline.py`
- Test files prefixed with `test_`: `tests/test_validation.py`

**Functions:**
- `snake_case` for all functions: `validate_batch`, `build_extraction_prompt`, `extract_with_llm`, `resolve_ref`
- Private / internal helpers prefixed with `_`: `_norm`, `_short_evidence`, `_gaz`, `_batch`
- Factory/helper functions in tests use `_` prefix to signal non-test callables: `_gaz()`, `_batch()`

**Classes:**
- `PascalCase`: `NodeLabel`, `RelType`, `ExtractedNode`, `ExtractedEdge`, `ExtractionResult`, `CanonTier`, `SourceContext`, `ResolutionHit`, `Gazetteer`, `Verdict`, `ValidatedEdge`, `Validator`
- Pydantic models (`BaseModel` subclasses) represent LLM output shapes
- `dataclass` used for pipeline-internal data containers: `SourceContext`, `ResolutionHit`, `ValidatedEdge`

**Variables / Parameters:**
- `snake_case` throughout: `canonical_id`, `fuzzy_threshold`, `accept_threshold`, `source_ref`, `target_ref`
- Module-level constants in `UPPER_SNAKE_CASE`: `AGENT_LABELS`, `PLACE_LABELS`, `RESOLVABLE_LABELS`, `RELATION_DOMAINS`, `DEFAULT_MODEL`
- Local temporaries use short, descriptive names: `ref_id`, `ref_label`, `review_ids`, `kept`, `rejected`

**Enums:**
- Class name `PascalCase`, member values `UPPER_SNAKE_CASE` matching their string value: `NodeLabel.PERSON = "Person"`, `RelType.INSTIGATED_BY = "INSTIGATED_BY"`, `CanonTier.CAMPAIGN_ACTUAL = "CAMPAIGN_ACTUAL"`
- All enums inherit from `(str, Enum)` so values serialize directly to strings

## Code Style

**Formatting:**
- `ruff` is the sole linter/formatter (`ruff>=0.5` in `[project.optional-dependencies]` dev group)
- Lint target: `ruff check lore_graph tests` (invoked via `make lint`)
- No `pyproject.toml` `[tool.ruff]` section present — ruff defaults apply

**Python Version:**
- `requires-python = ">=3.11"`; use Python 3.11+ syntax freely (e.g., `match`, `|` union types in annotations)

**Type Annotations:**
- All public functions and methods carry return type annotations: `def resolve(self, mention: str) -> ResolutionHit`, `def validate_batch(...) -> tuple[list[ValidatedEdge], list[ValidatedEdge]]`
- `from __future__ import annotations` is present in `extraction.py` to enable forward references
- `Optional[X]` used (not `X | None`) for optional fields: `Optional[str]`, `Optional[NodeLabel]`
- Built-in generics used directly: `list[str]`, `dict[str, str]`, `set[str]`, `tuple[...]`

**Imports:**
- Standard library first, then third-party, then local (PEP 8 order observed in `extraction.py`)
- `try/except ImportError` for optional dependencies: `rapidfuzz` wrapped in try/except with fallback to `fuzz = None`
- Heavy imports (`anthropic`) are deferred inside the function that needs them (`extract_with_llm`), keeping the module importable without optional dependencies

## Module Structure

**Sections:**
- Modules use visual section banners with `# ──────────────────────────...──` separators to group logical sections. Each section has a descriptive header comment. See `lore_graph/extraction.py` for the canonical style.

**Stub Modules:**
- Stub modules (`loader.py`, `parsing.py`, `pipeline.py`) follow a consistent pattern: module docstring with the contract (function signatures, rules, steps), then a single `raise NotImplementedError("modulename: see contract above")`. Do not add more code until implementing the contract.

**`__init__.py`:**
- Package init is empty; modules are imported directly by consumers.

## Pydantic Usage

- Pydantic v2 (`pydantic>=2.6`) is required.
- Models use `Field(...)` for required fields with `description=` to double as LLM schema documentation.
- Models use `Field(default_factory=list)` / `Field(default_factory=dict)` for mutable defaults.
- `@field_validator("field")` + `@classmethod` pattern for field-level validation: `_short_evidence` in `ExtractedEdge`.
- `model_json_schema()` used to produce the forced-tool schema for the Anthropic API call.
- `model_validate(block.input)` used for parsing LLM tool-use output.

## Dataclass Usage

- `@dataclass` (stdlib) for pipeline-internal data transfer objects that don't need JSON schema: `SourceContext`, `ResolutionHit`, `ValidatedEdge`.
- `field(default_factory=list)` for mutable defaults in dataclasses.

## Enum Design

- Enums are the single source of truth for all controlled-vocabulary terms. The Cypher schema must agree with them.
- When adding a `RelType`, its entry in `RELATION_DOMAINS` must be added in the same commit.
- Set constants (`AGENT_LABELS`, `PLACE_LABELS`, `RESOLVABLE_LABELS`) capture semantic groupings of labels for use in domain checks.

## Error Handling

- The `Validator` accumulates `reasons: list[str]` per edge and routes to `REJECT`/`QUEUE`/`ACCEPT` — no exceptions thrown for validation failures. Callers inspect the returned lists.
- `NotImplementedError` is raised immediately at module level in stubs — import-time failure is intentional so stubs cannot be called silently.
- The `extract_with_llm` function returns an empty `ExtractionResult()` if no tool-use block is found, rather than raising.
- `Optional` return values (e.g., `resolve_ref` returns `(None, None)`) are checked by callers; `None` signals "not found" rather than raising.

## Comments

**Module Docstrings:**
- Every module has a top-level docstring explaining pipeline position, design rules enforced, and key invariants. Use this for orientation, not just function listings.

**Section Comments:**
- Group related definitions with `# ──── SECTION TITLE ────` banners (visual separators).

**Inline Comments:**
- Used freely to explain *why*, especially for non-obvious logic: `# hook: embedding_resolve(...)`, `# near-tie between two different entities -> flag for human review`.
- Step labels in algorithms: `# 1. Resolve every node ref...`, `# (a) DANGLING:`, `# (b) TYPE:`, `# (c) CONFIDENCE`.

**CLAUDE.md Conventions Block:**
- Architecture decisions and invariants that must be preserved are documented in `CLAUDE.md` under "Settled architecture decisions" and "Conventions". Read this before making changes.

## Demo / Runnable Block

- The `if __name__ == "__main__":` block in `extraction.py` is a network-free demo that exercises the validation layer. Maintain this pattern for all modules with non-trivial logic so `make extract-demo` continues to work without network access.

---

*Convention analysis: 2026-06-15*
