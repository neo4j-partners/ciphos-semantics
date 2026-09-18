// Disposable CIPHOS-shaped source for the local semantic-map workflow.
// The seed is small on purpose but it deliberately covers every extraction case
// the frozen contract cares about: a multi-label node set, a label set that is
// the CIPHOS marker alone, a label with no properties at all, a label no node
// carries, a relationship property, and one relationship type whose endpoints
// are genuinely ambiguous.  Re-running it is safe; every write is a MERGE.

CREATE CONSTRAINT ciphos_test_tag_number IF NOT EXISTS
FOR (tag:Tag) REQUIRE tag.tagNumber IS UNIQUE;

CREATE RANGE INDEX ciphos_test_document_number IF NOT EXISTS
FOR (document:Document) ON (document.documentNumber);

CREATE RANGE INDEX ciphos_test_vulnerability_confidence IF NOT EXISTS
FOR ()-[relationship:HAS_VULNERABILITY]-() ON (relationship.confidence);

// A label that exists in the schema but that no node carries. db.labels() never
// reports it, so this proves the map does not invent node types.
CREATE INDEX ciphos_test_unused_label IF NOT EXISTS
FOR (zone:AssetZone) ON (zone.zoneName);

MERGE (projection:CiphosProjection {graphSnapshotId: 'local-semantic-test'})
SET projection.status = 'ACTIVE';

// The CIPHOS marker label on its own. `Node.label` must stay `CiphosEntity`
// here rather than collapsing to an empty primary label.
MERGE (:CiphosEntity {entityKey: 'ENTITY-LOCAL-1'});

// A label set carrying no properties whatsoever.
MERGE (:CiphosEntity:AuditMarker);

MERGE (tag:CiphosEntity:Tag {tagNumber: 'TAG-LOCAL-1'})
MERGE (document:CiphosEntity:Document {documentNumber: 'DOC-LOCAL-1'})
MERGE (vulnerability:CiphosEntity:Vulnerability {cveId: 'CVE-LOCAL-1'})
MERGE (tag)-[tag_vulnerability:HAS_VULNERABILITY]->(vulnerability)
SET tag_vulnerability.confidence = 0.9
MERGE (tag)-[:REFERENCED_IN]->(document);

// A second, archived label set for Tag. Endpoint extraction is statistics-based
// and reports the bare label `Tag`, which now matches two reported label sets,
// so HAS_SOURCE_NODE fans out to both.
MERGE (archived_tag:CiphosEntity:Tag:Archived {tagNumber: 'TAG-LOCAL-2'})
MERGE (other_vulnerability:CiphosEntity:Vulnerability {cveId: 'CVE-LOCAL-2'})
MERGE (archived_tag)-[archived_vulnerability:HAS_VULNERABILITY]->(other_vulnerability)
SET archived_vulnerability.confidence = 0.4;

// HAS_VULNERABILITY from a Document as well, so one relationship type carries
// more than one possible source label set from distinct domain labels.
MERGE (advisory:CiphosEntity:Document {documentNumber: 'DOC-LOCAL-2'})
MERGE (advisory_vulnerability:CiphosEntity:Vulnerability {cveId: 'CVE-LOCAL-3'})
MERGE (advisory)-[advisory_link:HAS_VULNERABILITY]->(advisory_vulnerability)
SET advisory_link.confidence = 0.7;
