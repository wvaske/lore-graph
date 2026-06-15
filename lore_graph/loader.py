"""
loader.py — STUB. Idempotent writer + review-queue sink.

Contract (build this next; see PLAN Phase 1):
    load(kept: list[ValidatedEdge], rejected: list[ValidatedEdge]) -> LoadReport

Rules:
  * ACCEPT edges -> MERGE into Neo4j (never CREATE). MERGE nodes by canonical id,
    then MERGE the relationship; set source/canon/edition and, for state-facts
    (RULES/ALLIED_WITH/IMPRISONED_IN/...), valid_from/valid_to.
  * QUEUE edges -> write to a review table (e.g. a :ReviewItem node or external
    store) with reasons, for human accept/reject. Accepted-on-review items are
    replayed through the same MERGE path.
  * REJECT edges -> log with reasons; do not write.
  * Idempotency: content-hash the source chunk; skip if already loaded unchanged.
  * The Python bolt driver owns ALL writes. The MCP server stays read-only.
"""
raise NotImplementedError("loader: see contract above")
