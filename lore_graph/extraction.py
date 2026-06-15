"""
extraction.py — Schema-constrained lore extraction + validation.

Pipeline position (see PLAN.md, stages 4-6):
    parsed chunk ──> LLM extraction ──> resolve refs ──> VALIDATE ──> {accept | queue | reject}

Design rules this module enforces:
  * Controlled vocabulary only. Node labels and relation types are closed Enums;
    anything off-vocab is rejected, not coerced.
  * Events are reified. The LLM emits Event nodes with role EDGES
    (INSTIGATED_BY, EXECUTED_BY, ...), never entity-to-entity verbs.
  * Closed-world edge validation. Every edge endpoint must resolve to a known
    canonical node (in the gazetteer) or a node declared new in the same batch.
    Edges to nothing are DANGLING and rejected — the core integrity guarantee.
  * Provenance is stamped by the pipeline, not invented by the LLM. The model
    never supplies source/canon/edition; SourceContext does.

The LLM call lives behind one function (`extract_with_llm`); swap it for a local
model without touching the validation layer. Run `python extraction.py` for a
network-free demo of validation on the assassination example.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator

try:
    from rapidfuzz import fuzz
except ImportError:  # resolution falls back to exact-match only
    fuzz = None


# ─────────────────────────────────────────────────────────────────────────────
# CONTROLLED VOCABULARY
# ─────────────────────────────────────────────────────────────────────────────
class NodeLabel(str, Enum):
    PERSON = "Person"            # named NPC / PC          (Agent)
    ORGANIZATION = "Organization"  # cult, faction, legion (Agent)
    POWER = "Power"              # deity / archdevil        (Agent)
    LOCATION = "Location"
    PLANE = "Plane"
    GOAL = "Goal"
    EVENT = "Event"
    PROPHECY = "Prophecy"
    CONFLICT = "Conflict"
    CAPABILITY = "Capability"
    ITEM = "Item"


AGENT_LABELS = {NodeLabel.PERSON, NodeLabel.ORGANIZATION, NodeLabel.POWER}
PLACE_LABELS = {NodeLabel.LOCATION, NodeLabel.PLANE}

# Labels for entities expected to already exist in canon. A *new* node of one of
# these types is a likely resolution miss (duplicate risk) and warrants review.
# Events, Goals, Prophecies, Conflicts, Capabilities are routinely created fresh
# and do NOT trigger review by novelty alone.
RESOLVABLE_LABELS = AGENT_LABELS | PLACE_LABELS | {NodeLabel.ITEM}


class RelType(str, Enum):
    # goals
    PURSUES = "PURSUES"
    SERVES = "SERVES"
    ALIGNS_WITH = "ALIGNS_WITH"
    CONFLICTS_WITH = "CONFLICTS_WITH"
    TARGETS = "TARGETS"
    # events
    ADVANCES = "ADVANCES"
    THREATENS = "THREATENS"
    INSTIGATED_BY = "INSTIGATED_BY"
    EXECUTED_BY = "EXECUTED_BY"
    TARGETED = "TARGETED"
    OCCURRED_AT = "OCCURRED_AT"
    CAUSED = "CAUSED"
    ENABLED = "ENABLED"
    PREVENTED = "PREVENTED"
    # structure / means
    COMMANDS = "COMMANDS"
    INFLUENCES = "INFLUENCES"
    CAPABLE_OF = "CAPABLE_OF"
    MEMBER_OF = "MEMBER_OF"
    # state-facts (time-bounded at load)
    RULES = "RULES"
    ALLIED_WITH = "ALLIED_WITH"
    PART_OF = "PART_OF"
    IMPRISONED_IN = "IMPRISONED_IN"
    # prophecy
    FORETELLS = "FORETELLS"
    SUBJECT_OF = "SUBJECT_OF"


# (source labels, target labels) permitted for each relation. The validation
# layer rejects any edge whose endpoints' labels fall outside this matrix.
ALL = set(NodeLabel)
RELATION_DOMAINS: dict[RelType, tuple[set[NodeLabel], set[NodeLabel]]] = {
    RelType.PURSUES:        (AGENT_LABELS, {NodeLabel.GOAL}),
    RelType.SERVES:         ({NodeLabel.GOAL}, {NodeLabel.GOAL}),
    RelType.ALIGNS_WITH:    ({NodeLabel.GOAL}, {NodeLabel.GOAL}),
    RelType.CONFLICTS_WITH: ({NodeLabel.GOAL}, {NodeLabel.GOAL}),
    RelType.TARGETS:        ({NodeLabel.GOAL}, AGENT_LABELS | PLACE_LABELS | {NodeLabel.ITEM}),
    RelType.ADVANCES:       ({NodeLabel.EVENT}, {NodeLabel.GOAL}),
    RelType.THREATENS:      ({NodeLabel.EVENT}, {NodeLabel.GOAL}),
    RelType.INSTIGATED_BY:  ({NodeLabel.EVENT}, AGENT_LABELS),
    RelType.EXECUTED_BY:    ({NodeLabel.EVENT}, AGENT_LABELS),
    RelType.TARGETED:       ({NodeLabel.EVENT}, AGENT_LABELS | PLACE_LABELS),
    RelType.OCCURRED_AT:    ({NodeLabel.EVENT}, PLACE_LABELS),
    RelType.CAUSED:         ({NodeLabel.EVENT}, {NodeLabel.EVENT}),
    RelType.ENABLED:        ({NodeLabel.EVENT}, {NodeLabel.EVENT}),
    RelType.PREVENTED:      ({NodeLabel.EVENT}, {NodeLabel.EVENT}),
    RelType.COMMANDS:       (AGENT_LABELS, AGENT_LABELS),
    RelType.INFLUENCES:     (AGENT_LABELS, AGENT_LABELS),
    RelType.CAPABLE_OF:     (AGENT_LABELS, {NodeLabel.CAPABILITY}),
    RelType.MEMBER_OF:      ({NodeLabel.PERSON, NodeLabel.POWER}, {NodeLabel.ORGANIZATION}),
    RelType.RULES:          (AGENT_LABELS, PLACE_LABELS),
    RelType.ALLIED_WITH:    (AGENT_LABELS, AGENT_LABELS),
    RelType.PART_OF:        (PLACE_LABELS, PLACE_LABELS),
    RelType.IMPRISONED_IN:  (AGENT_LABELS, PLACE_LABELS),
    RelType.FORETELLS:      ({NodeLabel.PROPHECY}, {NodeLabel.EVENT, NodeLabel.GOAL}),
    RelType.SUBJECT_OF:     (AGENT_LABELS, {NodeLabel.PROPHECY}),
}


# ─────────────────────────────────────────────────────────────────────────────
# LLM OUTPUT SHAPE (what the model is constrained to return)
# ─────────────────────────────────────────────────────────────────────────────
class ExtractedNode(BaseModel):
    """An entity mentioned in the chunk. `temp_id` is batch-local; resolution
    maps it to a canonical graph id (existing or freshly minted)."""
    temp_id: str = Field(..., description="Unique within this extraction only, e.g. 'n1'.")
    label: NodeLabel
    name: str = Field(..., description="Surface name as written, e.g. 'Severin Silrajin'.")
    aliases: list[str] = Field(default_factory=list)
    attributes: dict[str, str] = Field(default_factory=dict)
    evidence: str = Field("", description="Short verbatim span (<25 words) that supports this node.")


class ExtractedEdge(BaseModel):
    rel_type: RelType
    source_ref: str = Field(..., description="A node temp_id, or the exact name of a known canonical entity.")
    target_ref: str
    confidence: float = Field(..., ge=0.0, le=1.0)
    evidence: str = Field("", description="Short verbatim span (<25 words) supporting this edge.")

    @field_validator("evidence")
    @classmethod
    def _short_evidence(cls, v: str) -> str:
        # keep evidence to a short snippet; never reproduce long passages
        return " ".join(v.split()[:25])


class ExtractionResult(BaseModel):
    """Top-level tool-call schema handed to the LLM."""
    nodes: list[ExtractedNode] = Field(default_factory=list)
    edges: list[ExtractedEdge] = Field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# PROVENANCE (stamped by the pipeline, never by the LLM)
# ─────────────────────────────────────────────────────────────────────────────
class CanonTier(str, Enum):
    PUBLISHED = "PUBLISHED"
    MY_CANON = "MY_CANON"
    CAMPAIGN_ACTUAL = "CAMPAIGN_ACTUAL"
    FORESHADOWED = "FORESHADOWED"


@dataclass
class SourceContext:
    source: str          # "Rise of Tiamat p.94" / "session 42"
    canon: CanonTier
    edition: str         # "5e" / "2e" / "novel:Avatar Trilogy"
    canon_rank: int      # lower = more authoritative when resolving conflicts


# ─────────────────────────────────────────────────────────────────────────────
# ENTITY RESOLUTION (mention -> canonical id)
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class ResolutionHit:
    canonical_id: Optional[str]
    score: float
    ambiguous: bool = False


class Gazetteer:
    """In-memory canonical name/alias index. In production this is backed by
    Neo4j (and ideally a second embedding-similarity pass + LLM disambiguation
    for the hard cases) — both are clean hooks below."""

    def __init__(self, fuzzy_threshold: float = 90.0):
        self._by_norm: dict[str, str] = {}          # normalized name/alias -> canonical_id
        self._labels: dict[str, NodeLabel] = {}     # canonical_id -> label
        self.fuzzy_threshold = fuzzy_threshold

    @staticmethod
    def _norm(s: str) -> str:
        return " ".join(s.lower().replace("the ", "").split())

    def add(self, canonical_id: str, label: NodeLabel, names: list[str]) -> None:
        self._labels[canonical_id] = label
        for n in names:
            self._by_norm[self._norm(n)] = canonical_id

    def label_of(self, canonical_id: str) -> Optional[NodeLabel]:
        return self._labels.get(canonical_id)

    def resolve(self, mention: str) -> ResolutionHit:
        key = self._norm(mention)
        if key in self._by_norm:                     # exact / alias
            return ResolutionHit(self._by_norm[key], 100.0)
        if fuzz is None:
            return ResolutionHit(None, 0.0)
        best_id, best_score, runner = None, 0.0, 0.0
        for norm, cid in self._by_norm.items():
            s = fuzz.token_sort_ratio(key, norm)
            if s > best_score:
                best_id, runner, best_score = cid, best_score, s
            elif s > runner:
                runner = s
        if best_score >= self.fuzzy_threshold:
            # near-tie between two different entities -> flag for human review
            return ResolutionHit(best_id, best_score, ambiguous=(best_score - runner) < 5)
        return ResolutionHit(None, best_score)

    # hook: embedding_resolve(mention) and llm_disambiguate(mention, candidates)


# ─────────────────────────────────────────────────────────────────────────────
# VALIDATION  (the deterministic heart — pure, testable, no LLM)
# ─────────────────────────────────────────────────────────────────────────────
class Verdict(str, Enum):
    ACCEPT = "ACCEPT"    # validated + confident -> load to graph
    QUEUE = "QUEUE"      # valid but uncertain  -> human review
    REJECT = "REJECT"    # structurally invalid -> dropped (with reason)


@dataclass
class ValidatedEdge:
    rel_type: RelType
    source_id: str
    target_id: str
    confidence: float
    evidence: str
    provenance: SourceContext
    verdict: Verdict
    reasons: list[str] = field(default_factory=list)


class Validator:
    def __init__(self, gazetteer: Gazetteer, accept_threshold: float = 0.75):
        self.gaz = gazetteer
        self.accept_threshold = accept_threshold

    def validate_batch(
        self, result: ExtractionResult, ctx: SourceContext
    ) -> tuple[list[ValidatedEdge], list[ValidatedEdge]]:
        """Returns (kept, rejected). `kept` carries per-edge ACCEPT/QUEUE verdicts."""
        # 1. Resolve every node ref in the batch to a canonical id + label.
        #    A ref resolves if it's a temp_id declared in this batch OR a known
        #    gazetteer entity. Anything else makes its edges DANGLING.
        ref_id: dict[str, str] = {}
        ref_label: dict[str, NodeLabel] = {}
        review_ids: set[str] = set()   # minted ids that need human eyes

        for node in result.nodes:
            hit = self.gaz.resolve(node.name)
            if hit.canonical_id and not hit.ambiguous:
                ref_id[node.temp_id] = hit.canonical_id
                ref_label[node.temp_id] = self.gaz.label_of(hit.canonical_id) or node.label
            else:
                # New (or ambiguous) entity: mint a provisional id. Only flag for
                # review if it's a type that should have pre-existed (or ambiguous);
                # new Events/Goals/etc. are expected and pass through.
                provisional = f"new::{node.label.value}::{Gazetteer._norm(node.name)}"
                ref_id[node.temp_id] = provisional
                ref_label[node.temp_id] = node.label
                if node.label in RESOLVABLE_LABELS or hit.ambiguous:
                    review_ids.add(provisional)

        def resolve_ref(ref: str) -> tuple[Optional[str], Optional[NodeLabel]]:
            if ref in ref_id:                       # batch-local temp_id
                return ref_id[ref], ref_label[ref]
            hit = self.gaz.resolve(ref)             # bare canonical name
            if hit.canonical_id and not hit.ambiguous:
                return hit.canonical_id, self.gaz.label_of(hit.canonical_id)
            return None, None

        kept, rejected = [], []
        for e in result.edges:
            reasons: list[str] = []
            sid, slabel = resolve_ref(e.source_ref)
            tid, tlabel = resolve_ref(e.target_ref)

            # (a) DANGLING: endpoint resolves to nothing -> reject
            if sid is None:
                reasons.append(f"dangling source ref '{e.source_ref}'")
            if tid is None:
                reasons.append(f"dangling target ref '{e.target_ref}'")

            # (b) TYPE: endpoint labels must satisfy the relation domain
            if slabel and tlabel:
                src_ok, tgt_ok = RELATION_DOMAINS[e.rel_type]
                if slabel not in src_ok:
                    reasons.append(f"{e.rel_type.value} source must be {{{','.join(l.value for l in src_ok)}}}, got {slabel.value}")
                if tlabel not in tgt_ok:
                    reasons.append(f"{e.rel_type.value} target must be {{{','.join(l.value for l in tgt_ok)}}}, got {tlabel.value}")

            if reasons:
                rejected.append(ValidatedEdge(e.rel_type, str(sid), str(tid), e.confidence,
                                              e.evidence, ctx, Verdict.REJECT, reasons))
                continue

            # (c) CONFIDENCE / novelty -> ACCEPT vs QUEUE
            involves_review = sid in review_ids or tid in review_ids
            if e.confidence >= self.accept_threshold and not involves_review:
                verdict, why = Verdict.ACCEPT, []
            else:
                verdict, why = Verdict.QUEUE, []
                if e.confidence < self.accept_threshold:
                    why.append(f"confidence {e.confidence:.2f} < {self.accept_threshold}")
                if involves_review:
                    why.append("touches a new entity that should have resolved")
            kept.append(ValidatedEdge(e.rel_type, sid, tid, e.confidence,
                                      e.evidence, ctx, verdict, why))
        return kept, rejected


# ─────────────────────────────────────────────────────────────────────────────
# SCHEMA-CONSTRAINED PROMPT
# ─────────────────────────────────────────────────────────────────────────────
def build_extraction_prompt(chunk: str, gazetteer_hints: list[str]) -> str:
    labels = ", ".join(l.value for l in NodeLabel)
    rels = ", ".join(r.value for r in RelType)
    hints = "\n".join(f"  - {h}" for h in gazetteer_hints) or "  (none found in this chunk)"
    return f"""\
Extract lore from the passage into the fixed graph vocabulary. Return ONLY the
structured tool call — no prose.

NODE LABELS (use exactly these): {labels}
RELATION TYPES (use exactly these): {rels}

RULES
1. Reify events. A happening is an Event NODE. Connect participants with role
   EDGES: INSTIGATED_BY (who willed it), EXECUTED_BY (who did it), TARGETED,
   OCCURRED_AT. Never write a direct "X betrayed Y" edge.
2. Capture goals as Goal nodes; connect agents with PURSUES, goals to goals with
   SERVES / ALIGNS_WITH / CONFLICTS_WITH, and an event's effect with
   ADVANCES / THREATENS.
3. Prefer linking to KNOWN ENTITIES below (use their exact name as the ref) over
   inventing duplicates:
{hints}
4. Every edge needs a confidence (0-1) and a short verbatim evidence span (<25 words).
5. Do NOT supply source, edition, or canon — those are added downstream.
6. If a relationship isn't expressible in the vocabulary, omit it.

PASSAGE
\"\"\"{chunk}\"\"\"
"""


# ─────────────────────────────────────────────────────────────────────────────
# LLM BOUNDARY (the only network-bound, swappable part)
# ─────────────────────────────────────────────────────────────────────────────
DEFAULT_MODEL = "claude-sonnet-4-6"  # extraction quality benefits from a stronger
                                     # model; point this at local tooling if preferred.


def extract_with_llm(chunk: str, gazetteer_hints: list[str],
                     model: str = DEFAULT_MODEL) -> ExtractionResult:
    """Forced-tool-use extraction. Isolated so the validation layer above stays
    pure and unit-testable. Requires the `anthropic` SDK + ANTHROPIC_API_KEY."""
    import anthropic

    tool = {
        "name": "emit_lore",
        "description": "Emit extracted nodes and edges in the fixed vocabulary.",
        "input_schema": ExtractionResult.model_json_schema(),
    }
    client = anthropic.Anthropic()
    msg = client.messages.create(
        model=model,
        max_tokens=4096,
        tools=[tool],
        tool_choice={"type": "tool", "name": "emit_lore"},
        messages=[{"role": "user", "content": build_extraction_prompt(chunk, gazetteer_hints)}],
    )
    for block in msg.content:
        if getattr(block, "type", None) == "tool_use" and block.name == "emit_lore":
            return ExtractionResult.model_validate(block.input)
    return ExtractionResult()


# ─────────────────────────────────────────────────────────────────────────────
# DEMO — runs without network; exercises validation on the assassination case
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    gaz = Gazetteer()
    gaz.add("cult_dragon", NodeLabel.ORGANIZATION, ["Cult of the Dragon", "the Cult"])
    gaz.add("severin", NodeLabel.PERSON, ["Severin Silrajin", "Severin"])
    gaz.add("goal_free_tiamat", NodeLabel.GOAL, ["Free Tiamat"])

    # Pretend the LLM returned this for a chunk. Note the deliberate problems:
    mock = ExtractionResult(
        nodes=[
            ExtractedNode(temp_id="e1", label=NodeLabel.EVENT, name="Assassination attempt on the child"),
            ExtractedNode(temp_id="g1", label=NodeLabel.GOAL, name="Free Tiamat"),  # resolves to known
            ExtractedNode(temp_id="p1", label=NodeLabel.PERSON, name="Severin"),    # resolves to known
        ],
        edges=[
            # valid, high confidence, all-known -> ACCEPT
            ExtractedEdge(rel_type=RelType.INSTIGATED_BY, source_ref="e1", target_ref="p1", confidence=0.9),
            # valid type, but threatens a known goal -> ACCEPT
            ExtractedEdge(rel_type=RelType.THREATENS, source_ref="e1", target_ref="g1", confidence=0.8),
            # TYPE violation: PURSUES target must be a Goal, not a Person
            ExtractedEdge(rel_type=RelType.PURSUES, source_ref="p1", target_ref="e1", confidence=0.7),
            # DANGLING: target_ref names nothing known and no such temp_id
            ExtractedEdge(rel_type=RelType.ALLIED_WITH, source_ref="p1", target_ref="The Shadow Broker", confidence=0.6),
        ],
    )

    ctx = SourceContext("Homebrew session 42", CanonTier.MY_CANON, "5e", canon_rank=1)
    kept, rejected = Validator(gaz).validate_batch(mock, ctx)

    print("KEPT")
    for e in kept:
        tag = f" [{', '.join(e.reasons)}]" if e.reasons else ""
        print(f"  {e.verdict.value:7} {e.source_id} -{e.rel_type.value}-> {e.target_id}{tag}")
    print("REJECTED")
    for e in rejected:
        print(f"  {e.verdict.value:7} {e.source_ref if False else e.source_id} -{e.rel_type.value}-> {e.target_id}  ({'; '.join(e.reasons)})")
