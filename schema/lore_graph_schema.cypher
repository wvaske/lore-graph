// =============================================================================
// DM COMPANION — LORE GRAPH SCHEMA (starting draft, Neo4j 5 / Cypher)
// Focus: people, organizations, goals, canonical events, time, causality.
// Mechanics (spells/monsters) live in a separate layer and join on entities.
// =============================================================================

// -----------------------------------------------------------------------------
// SHARED CONVENTIONS
// -----------------------------------------------------------------------------
// :Agent  -> applied to anything that can hold a goal (Person, Organization, Power).
//            This gives PURSUES a clean domain. A node carries multiple labels,
//            e.g.  (:Power:Agent {name:'Zariel'})  (:Organization:Agent {...}).
// time    -> in-world year as an integer (DR / Dalereckoning). Coarse on purpose;
//            add a sort key + display string later if you need finer granularity.
// canon   -> every Event and state-fact carries a `canon` property:
//            'PUBLISHED' | 'MY_CANON' | 'CAMPAIGN_ACTUAL' | 'FORESHADOWED'
// status  -> Event lifecycle relative to campaign time:
//            'RESOLVED' | 'IN_PROGRESS' | 'NOT_YET'
// All facts that can change over time carry valid_from / valid_to (DR years).
// Provenance (`source`) is required: book+page, or "ruling, session 42".
// -----------------------------------------------------------------------------

// ---- Uniqueness constraints (id on every primary node type) -----------------
CREATE CONSTRAINT agent_id   IF NOT EXISTS FOR (n:Agent)    REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT loc_id     IF NOT EXISTS FOR (n:Location) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT plane_id   IF NOT EXISTS FOR (n:Plane)    REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT event_id   IF NOT EXISTS FOR (n:Event)    REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT goal_id    IF NOT EXISTS FOR (n:Goal)     REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT proph_id   IF NOT EXISTS FOR (n:Prophecy) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT conf_id    IF NOT EXISTS FOR (n:Conflict) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT cap_id     IF NOT EXISTS FOR (n:Capability) REQUIRE n.id IS UNIQUE;

// =============================================================================
// NODE TYPES
// =============================================================================
//  (:Person:Agent)        named NPCs/PCs        {alive, alignment, ...}
//  (:Organization:Agent)  cults, factions, legions
//  (:Power:Agent)         deities, archdevils    {portfolio}
//  (:Location)            cities, regions        (containment via PART_OF)
//  (:Plane)               Material, the Nine Hells layers
//  (:Goal)                what an Agent wants     {scope, secrecy}
//  (:Event)               reified happening       {canon, status, dr_year, ...}
//  (:Prophecy)            a foretold outcome
//  (:Conflict)            standing struggle (the Blood War) w/ slow front-state
//  (:Capability)          a means-tag (e.g. 'assassination', 'planar travel')

// =============================================================================
// RELATIONSHIPS
// =============================================================================
// GOALS — the spine of both "what is X trying to do" and the suspect-generator
//   (:Agent)-[:PURSUES {priority, secrecy, since}]->(:Goal)
//   (:Goal)-[:SERVES]->(:Goal)            // instrumental -> grand goal hierarchy
//   (:Goal)-[:ALIGNS_WITH]->(:Goal)       // goal-to-goal, agent-independent
//   (:Goal)-[:CONFLICTS_WITH]->(:Goal)
//   (:Goal)-[:TARGETS]->(:Agent|:Location|:Item|:Plane)  // the object of the goal
//
// EVENTS — directional impact on goals is what makes abduction mechanical
//   (:Event)-[:ADVANCES]->(:Goal)
//   (:Event)-[:THREATENS]->(:Goal)
//   (:Event)-[:INSTIGATED_BY]->(:Agent)   // who willed it
//   (:Event)-[:EXECUTED_BY]->(:Agent)     // who carried it out
//   (:Event)-[:TARGETED]->(:Agent|:Location)
//   (:Event)-[:OCCURRED_AT]->(:Location|:Plane)
//   (:Event)-[:CAUSED|:ENABLED|:PREVENTED]->(:Event)   // causal chains
//
// MEANS / STRUCTURE
//   (:Agent)-[:COMMANDS {valid_from, valid_to}]->(:Agent)   // chain of authority
//   (:Agent)-[:INFLUENCES]->(:Agent)                         // softer than COMMANDS
//   (:Agent)-[:CAPABLE_OF]->(:Capability)
//   (:Agent)-[:MEMBER_OF {valid_from, valid_to}]->(:Organization)
//
// STATE-FACTS (time-bounded; query by interval overlap)
//   (:Agent)-[:RULES {valid_from, valid_to, canon}]->(:Location|:Plane)
//   (:Agent)-[:ALLIED_WITH {valid_from, valid_to}]->(:Agent)
//   (:Location|:Plane)-[:PART_OF]->(:Location|:Plane)        // containment
//
// PROPHECY
//   (:Prophecy)-[:FORETELLS]->(:Event|:Goal)
//   (:Agent)-[:SUBJECT_OF]->(:Prophecy)

// =============================================================================
// MINIMAL SEED — illustrative. VERIFY names/dates against your chosen canon;
// the third-party suspect below is intentionally homebrew (canon:'MY_CANON').
// =============================================================================
MERGE (tiamat:Power:Agent {id:'tiamat'})        SET tiamat.name='Tiamat';
MERGE (avernus:Plane {id:'avernus'})            SET avernus.name='Avernus';
MERGE (nineHells:Plane {id:'nine_hells'})       SET nineHells.name='The Nine Hells';
MERGE (avernus)-[:PART_OF]->(nineHells);

MERGE (cult:Organization:Agent {id:'cult_dragon'}) SET cult.name='Cult of the Dragon';
MERGE (severin:Person:Agent {id:'severin'})        SET severin.name='Severin Silrajin', severin.source='Rise of Tiamat';
MERGE (severin)-[:MEMBER_OF]->(cult);
MERGE (severin)-[:COMMANDS]->(cult);

// Goal hierarchy: the grand goal + an instrumental sub-goal
MERGE (gFree:Goal {id:'goal_free_tiamat'})
  SET gFree.name='Free Tiamat into the Material Plane', gFree.scope='grand';
MERGE (gMasks:Goal {id:'goal_gather_masks'})
  SET gMasks.name='Gather the Dragon Masks', gMasks.scope='instrumental';
MERGE (gMasks)-[:SERVES]->(gFree);
MERGE (cult)-[:PURSUES {priority:1, secrecy:'overt'}]->(gFree);
MERGE (gFree)-[:TARGETS]->(tiamat);
MERGE (tiamat)-[:IMPRISONED_IN]->(avernus);  // the RoT->DiA seam (verify specifics)

// The prophecy + the prophesied event that THREATENS the Cult's goal
MERGE (child:Person:Agent {id:'npc_child'}) SET child.name='Prophesied Child', child.canon='MY_CANON';
MERGE (proph:Prophecy {id:'proph_disruptor'})
  SET proph.text='The child will disrupt the Cult of the Dragon', proph.canon='MY_CANON';
MERGE (child)-[:SUBJECT_OF]->(proph);
MERGE (disrupt:Event {id:'ev_disruption', name:'Child disrupts the Cult', canon:'FORESHADOWED', status:'NOT_YET'});
MERGE (proph)-[:FORETELLS]->(disrupt);
MERGE (disrupt)-[:THREATENS]->(gFree);   // <-- the motive hook

// Means: someone capable of the deed, reachable by command
MERGE (assassins:Organization:Agent {id:'org_assassins'}) SET assassins.name='Assassins (generic)';
MERGE (cap:Capability {id:'cap_assassination', name:'assassination'});
MERGE (assassins)-[:CAPABLE_OF]->(cap);
MERGE (cult)-[:INFLUENCES]->(assassins);

// A NON-OBVIOUS, homebrew third party whose goal aligns with the Cult's
MERGE (broker:Person:Agent {id:'npc_broker'})
  SET broker.name='A Hell-bound Power-Broker', broker.canon='MY_CANON';
MERGE (gChaos:Goal {id:'goal_destabilize'})
  SET gChaos.name='Destabilize the Sword Coast for leverage', gChaos.canon='MY_CANON';
MERGE (broker)-[:PURSUES {priority:1, secrecy:'hidden'}]->(gChaos);
MERGE (gChaos)-[:ALIGNS_WITH]->(gFree);   // aligns indirectly -> surprising suspect
MERGE (broker)-[:COMMANDS]->(assassins);

// =============================================================================
// QUERY A — "What is X trying to accomplish?"  (goals, ranked, with hierarchy)
// =============================================================================
// :param agentId => 'cult_dragon'
MATCH (a:Agent {id:$agentId})-[p:PURSUES]->(g:Goal)
OPTIONAL MATCH path = (g)-[:SERVES*1..3]->(grand:Goal)
RETURN a.name AS agent, g.name AS goal, p.priority AS priority,
       p.secrecy AS secrecy, [n IN nodes(path) | n.name] AS servesChain
ORDER BY priority;

// =============================================================================
// QUERY B — THE SUSPECT-GENERATOR (abductive: effect -> plausible instigators)
// Given a target whose harm would advance some goal, find agents with
// MOTIVE (pursue an advanced/aligned goal) + MEANS (command path to a capable
// executor). Rank surprising-but-grounded suspects ABOVE the obvious target.
// =============================================================================
// :param targetId => 'npc_child'

// 1. What goal does harming the target advance? (direct: the event that
//    threatens a goal == its prevention advances that goal)
MATCH (:Person {id:$targetId})-[:SUBJECT_OF]->(:Prophecy)-[:FORETELLS]->(ev:Event)-[:THREATENS]->(threatened:Goal)

// 2. MOTIVE: agents pursuing that goal, OR a goal aligned with it
MATCH (motiveGoal:Goal)
WHERE motiveGoal = threatened
   OR (motiveGoal)-[:ALIGNS_WITH]-(threatened)
MATCH (suspect:Agent)-[pur:PURSUES]->(motiveGoal)

// 3. MEANS: a command/influence path from suspect to something CAPABLE of it
OPTIONAL MATCH meansPath = (suspect)-[:COMMANDS|INFLUENCES*1..4]->(:Agent)-[:CAPABLE_OF]->(:Capability {name:'assassination'})

// 4. Score. Direct pursuit of the threatened goal = obvious (penalize).
//    Aligned-but-indirect goal + hidden agenda + real means = juicy (reward).
WITH suspect, pur, motiveGoal, threatened, meansPath,
     CASE WHEN motiveGoal = threatened THEN 0 ELSE 2 END         AS surpriseScore,
     CASE WHEN pur.secrecy = 'hidden' THEN 1 ELSE 0 END          AS hiddenScore,
     CASE WHEN meansPath IS NOT NULL THEN 1 ELSE 0 END           AS meansScore
RETURN suspect.name                    AS suspect,
       motiveGoal.name                 AS motive,
       (meansPath IS NOT NULL)         AS hasMeans,
       suspect.canon                   AS canon,
       (surpriseScore + hiddenScore + meansScore) AS plausibilityRank
ORDER BY plausibilityRank DESC;   // non-obvious, well-connected suspects first

// =============================================================================
// QUERY C — "What's relevant right now?" (spatiotemporal scope; from prior design)
// =============================================================================
// :param region   => 'sword_coast'    :param year => 1490
MATCH (here:Location {id:$region})<-[:PART_OF*0..4]-(within)
MATCH (ev:Event)-[:OCCURRED_AT]->(within)
WHERE ev.dr_year <= $year
  AND coalesce(ev.ends_year, ev.dr_year) >= $year - 5   // recent / active window
  AND ev.canon IN ['PUBLISHED','MY_CANON','CAMPAIGN_ACTUAL']
OPTIONAL MATCH (ev)-[:INSTIGATED_BY]->(who:Agent)
RETURN ev.name AS event, within.name AS where, ev.dr_year AS year,
       collect(who.name) AS instigators, ev.status AS status
ORDER BY ev.dr_year DESC;
