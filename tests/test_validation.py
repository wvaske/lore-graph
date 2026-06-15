"""Tests for the pure validation layer — no network, no DB."""
from lore_graph.extraction import (
    Gazetteer, Validator, SourceContext, CanonTier, NodeLabel, RelType,
    ExtractionResult, ExtractedNode, ExtractedEdge, Verdict,
)


def _gaz() -> Gazetteer:
    g = Gazetteer()
    g.add("cult_dragon", NodeLabel.ORGANIZATION, ["Cult of the Dragon", "the Cult"])
    g.add("severin", NodeLabel.PERSON, ["Severin Silrajin", "Severin"])
    g.add("goal_free_tiamat", NodeLabel.GOAL, ["Free Tiamat"])
    return g


def _batch() -> ExtractionResult:
    return ExtractionResult(
        nodes=[
            ExtractedNode(temp_id="e1", label=NodeLabel.EVENT, name="Assassination attempt on the child"),
            ExtractedNode(temp_id="g1", label=NodeLabel.GOAL, name="Free Tiamat"),
            ExtractedNode(temp_id="p1", label=NodeLabel.PERSON, name="Severin"),
        ],
        edges=[
            ExtractedEdge(rel_type=RelType.INSTIGATED_BY, source_ref="e1", target_ref="p1", confidence=0.9),
            ExtractedEdge(rel_type=RelType.THREATENS, source_ref="e1", target_ref="g1", confidence=0.8),
            ExtractedEdge(rel_type=RelType.PURSUES, source_ref="p1", target_ref="e1", confidence=0.7),
            ExtractedEdge(rel_type=RelType.ALLIED_WITH, source_ref="p1", target_ref="The Shadow Broker", confidence=0.6),
        ],
    )


CTX = SourceContext("test", CanonTier.MY_CANON, "5e", canon_rank=1)


def test_valid_edges_accept():
    kept, _ = Validator(_gaz()).validate_batch(_batch(), CTX)
    accepted = [e for e in kept if e.verdict is Verdict.ACCEPT]
    rels = {e.rel_type for e in accepted}
    assert rels == {RelType.INSTIGATED_BY, RelType.THREATENS}


def test_type_violation_rejected():
    _, rejected = Validator(_gaz()).validate_batch(_batch(), CTX)
    bad = [e for e in rejected if e.rel_type is RelType.PURSUES]
    assert bad and any("must be {Goal}" in r for r in bad[0].reasons)


def test_dangling_edge_rejected():
    _, rejected = Validator(_gaz()).validate_batch(_batch(), CTX)
    bad = [e for e in rejected if e.rel_type is RelType.ALLIED_WITH]
    assert bad and any("dangling" in r for r in bad[0].reasons)


def test_low_confidence_unknown_org_routes_to_review():
    # A new Organization (resolvable type) at low confidence should QUEUE, not ACCEPT.
    batch = ExtractionResult(
        nodes=[
            ExtractedNode(temp_id="o1", label=NodeLabel.ORGANIZATION, name="The Unseen Hand"),
            ExtractedNode(temp_id="g1", label=NodeLabel.GOAL, name="Free Tiamat"),
        ],
        edges=[ExtractedEdge(rel_type=RelType.PURSUES, source_ref="o1", target_ref="g1", confidence=0.95)],
    )
    kept, _ = Validator(_gaz()).validate_batch(batch, CTX)
    assert kept and kept[0].verdict is Verdict.QUEUE
