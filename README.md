# Lore Graph

A self-hosted knowledge graph + hybrid retrieval pipeline for D&D / Forgotten
Realms lore, exposed to a DM companion over MCP. It models people, organizations,
goals, and **reified events** across in-world time, scoped to where and when a
party is, and can generate plausible instigators for an event you want to seed.

See **`CLAUDE.md`** for architecture decisions and **`PLAN.md`** for the phased
build plan.

## Quickstart

```bash
cp .env.example .env          # set NEO4J_PASSWORD, ANTHROPIC_API_KEY
make up                       # start Neo4j (browser :7474, bolt :7687)
make schema                   # apply constraints + seed
pip install -e .              # install the package
make test                     # run the validator test suite
make extract-demo             # network-free demo of the validation layer
```

## Status

Schema and the extraction + validation layer are in place and tested. The LLM
call is isolated behind `lore_graph.extraction.extract_with_llm`. Next up:
the idempotent loader, gazetteer bootstrap, sourcebook parser, and the
orchestrating pipeline — then ingest Rise of Tiamat end to end. See PLAN Phases 1–3.

## Layout

- `schema/` — Cypher schema (constraints, conventions, seed, flagship queries).
- `lore_graph/` — the pipeline package. `extraction.py` is built; `loader.py`,
  `parsing.py`, `pipeline.py` are stubs with documented contracts.
- `data/sources/` — raw books, **gitignored**. Never commit copyrighted text.
