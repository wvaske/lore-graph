"""
pipeline.py — STUB. Orchestrates the repeatable ingestion loop.

Contract (see PLAN, "generalized ingestion pipeline"):
    ingest(source_id: str) -> IngestReport

Steps: register (manifest) -> parse (profile) -> chunk (provenance) ->
resolve mentions (Gazetteer) -> extract (extract_with_llm) ->
validate (Validator) -> load (loader) -> embed -> detect contradictions.

Same shape for every source type; only the parser profile and canon tier change.
Must be idempotent and re-runnable as new sources are added.
"""
raise NotImplementedError("pipeline: see contract above")
