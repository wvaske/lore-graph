"""
parsing.py — STUB. Per-source-type parser profiles.

Contract (see PLAN Phase 2):
    parse(path: str, profile: str) -> list[Chunk]   # Chunk carries text + provenance

Profiles:
  * "sourcebook": two-column layout, stat blocks, sidebars. Triage with
    PyMuPDF4LLM (fast, CPU); escalate pages it mangles to Marker --use_llm or
    Docling. Carry section + page into each chunk's provenance.
  * "novel": EPUB / narrative prose. Chapter is the natural unit. ebooklib +
    BeautifulSoup, or Marker for EPUB. No tables/stat blocks.
  * "wiki": MediaWiki export. Wikilinks are hand-authored lore edges — import
    directly rather than re-extracting. Session logs feed CAMPAIGN_ACTUAL events.
"""
raise NotImplementedError("parsing: see contract above")
