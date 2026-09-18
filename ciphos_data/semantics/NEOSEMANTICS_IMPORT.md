# Importing the CFIHOS 2.0 + OT/Cybersecurity ontology and SHACL shapes with neosemantics

This folder has two files, generated against the graph actually produced by
[`synthetic_dataset.cypher`](../synthetic_dataset.cypher) (ground truth for labels,
relationship types and property keys — not the arrows.app diagram file, which uses
slightly different grouping labels for visualization purposes only):

- `ontology.ttl` — an OWL/RDFS vocabulary: one `owl:Class` per Neo4j node label,
  one `owl:ObjectProperty` per relationship type (with `rdfs:domain`/`rdfs:range`),
  one `owl:DatatypeProperty` per node property key (with `rdfs:range` as an XSD type).
- `shacl-shapes.ttl` — one `sh:NodeShape` per label, with property shapes for every
  stored attribute (datatype, cardinality, and — where the sample data supports it —
  a controlled vocabulary or regex format check) plus a property shape for every
  outgoing relationship (target label + cardinality, for the handful of relationships
  that are structurally 1:1 in this model).

Both files use the namespace `http://neo4j.com/voc/cfihos-ot-cyber#` (prefix `cfihos:`).
Local names match the graph exactly, e.g. class `cfihos:Tag` ↔ label `:Tag`,
object property `cfihos:CLASSIFIED_AS` ↔ relationship type `:CLASSIFIED_AS`,
datatype property `cfihos:tagNumber` ↔ property key `tagNumber`.

## 1. One-time graph config

neosemantics needs to know it should match RDF resources to Neo4j labels /
relationship types / property keys by local name only (there's no separate RDF
copy of this graph — the shapes validate the property graph directly):

```cypher
CALL n10s.graphconfig.init({ handleVocabUris: "IGNORE" });
```

Run this once per database, before the imports below. If you already initialized
graph config differently for other purposes, check that `handleVocabUris` is
`IGNORE` — with a `MAP`/`SHORTEN`/`KEEP` config the namespace prefix would need to
resolve through `n10s.mapping`, which these files don't set up.

## 2. Import the ontology (optional, for documentation / n10s.inference)

```cypher
CALL n10s.onto.import.fetch("file:///path/to/ontology.ttl", "Turtle");
```

Or inline (paste the file contents into `$ttl`):

```cypher
CALL n10s.onto.import.inline($ttl, "Turtle");
```

This creates a separate schema layer in the graph — `Class`, `Relationship` and
`Property` nodes connected by `SCO` (subclass) / `DOMAIN` / `RANGE` edges. It does
**not** touch your existing `:Tag`, `:AssetZone`, etc. nodes; it's metadata you can
browse, or drive `n10s.inference.*` procedures from, alongside the graph you already
have. If you don't need that layer, you can skip this step — SHACL validation
(next) works directly against the property graph without it.

## 3. Import the SHACL shapes

```cypher
CALL n10s.validation.shacl.import.fetch("file:///path/to/shacl-shapes.ttl", "Turtle");
```

Or inline, same pattern as above with `n10s.validation.shacl.import.inline`.

## 4. Run validation

Validate the whole graph:

```cypher
CALL n10s.validation.shacl.validate()
YIELD focusNode, nodeType, propertyShape, offendingValue, resultPath, resultMessage, severity
RETURN focusNode, nodeType, propertyShape, offendingValue, resultPath, resultMessage, severity
ORDER BY severity DESC;
```

Validate a specific set of nodes (e.g. everything touched in a batch load):

```cypher
MATCH (n:Tag) WHERE n.tagNumber STARTS WITH 'K-'
WITH collect(n) AS nodes
CALL n10s.validation.shacl.validateSet(nodes)
YIELD focusNode, nodeType, propertyShape, offendingValue, resultPath, resultMessage, severity
RETURN *;
```

Enforce validation on every write (requires APOC; rolls back the transaction if a
`sh:Violation`-severity constraint is broken):

```cypher
CALL apoc.trigger.add(
  'shacl-validate',
  'CALL n10s.validation.shacl.validateTransaction($createdNodes, $createdRelationships,
     $assignedLabels, $removedLabels, $assignedNodeProperties, $removedNodeProperties)',
  { phase: 'before' }
);
```

### Severity convention used in `shacl-shapes.ttl`

- **`sh:Violation`** (the default — unmarked constraints): required properties,
  correct datatypes, a relationship's target having the expected label, and the
  handful of relationships that are structurally 1:1 in this model (e.g.
  `Tag -[:CLASSIFIED_AS]-> EquipmentClass`, `Tag -[:LOCATED_AT]-> FunctionalLocation`,
  `NetworkSegment -[:WITHIN_ZONE]-> AssetZone`). If you wire up the transaction
  trigger above, only these block a write.
- **`sh:Warning`**: controlled-vocabulary checks (`sh:in`, e.g. `tagStatus` must be
  one of `In Service`/`Out of Service`/`Decommissioned`/`Commissioning`) and date
  format checks (`sh:pattern`). These are inferred from the current sample dataset
  rather than the official CFIHOS RDL pick lists, so they're deliberately
  non-blocking — review-and-extend rather than hard-fail. Loosen or tighten them
  (or promote specific ones to `sh:Violation`) as your real pick lists solidify.

## 5. Known limitations (not a neosemantics bug — SHACL/OWL just don't model this)

**Values stored *on* a relationship aren't covered.** Four relationships in this
schema carry their own properties rather than just connecting two nodes:

| Relationship | Property | Expected values |
|---|---|---|
| `Tag -[:CONNECTED_TO]-> Tag` | `connectionType` | `on-line`, `upstream-of`, `downstream-of`, `feeds`, `discharges-to` |
| `Tag -[:REPLACES]-> Tag` | `revampDate` | ISO date string |
| `AssetZone -[:HAS_CONDUIT]-> Conduit` | `direction` | `inbound`, `outbound` |
| `CyberIncident -[:REPORTED_UNDER]-> ComplianceFramework` | `reportingDeadlineHours` | integer, e.g. `24` |

Neither OWL nor neosemantics' native LPG SHACL validation can target a value
stored on a relationship (only node properties and a relationship's
existence/target class) — it's an LPG-only concept with no direct RDF/SHACL
equivalent. A companion Cypher check for these:

```cypher
MATCH ()-[r:CONNECTED_TO]->()
WHERE NOT r.connectionType IN ['on-line','upstream-of','downstream-of','feeds','discharges-to']
RETURN r, r.connectionType;

MATCH ()-[r:HAS_CONDUIT]->()
WHERE NOT r.direction IN ['inbound','outbound']
RETURN r, r.direction;

MATCH ()-[r:REPORTED_UNDER]->()
WHERE r.reportingDeadlineHours IS NULL OR r.reportingDeadlineHours <= 0
RETURN r, r.reportingDeadlineHours;
```

**True uniqueness isn't a SHACL concern here either.** `shacl-shapes.ttl` checks
that each key property (`tagNumber`, `zoneId`, `cveId`, …) is present with the
right datatype, but "no two nodes share this value" is a whole-graph constraint
SHACL can't express economically. That's already handled by the native Neo4j
constraints at the top of `synthetic_dataset.cypher` (`CREATE CONSTRAINT ... IS
UNIQUE`) — keep using those; they run in the database and don't need SHACL at all.

**Dates are plain strings.** `installationDate`, `publishedDate`, `assessmentDate`,
`detectedDate` and `reportedToAuthorityDate` are written by this dataset as plain
Neo4j strings (`"2014-03-05"`, `"2025-06-19T21:18:58"`), not native `Date`/`DateTime`
values, so the shapes validate them as `xsd:string` + `sh:pattern` rather than
`xsd:date`/`xsd:dateTime`. If you convert those properties to native temporal types
(e.g. via `SET n.installationDate = date(n.installationDate)`), change the
corresponding `sh:datatype` to `xsd:date` / `xsd:dateTime` and drop the `sh:pattern`.

## 6. Regenerating these files

Both files were generated from a small Python script rather than hand-written, so
regenerating them after a schema change (new label, new property, new relationship)
is safer than hand-editing ~2,300 lines of Turtle. Ask for the generator if you need
to add or change entities and want the files kept internally consistent.
