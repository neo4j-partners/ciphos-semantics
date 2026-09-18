CREATE CONSTRAINT ciphos_test_tag_number IF NOT EXISTS
FOR (tag:Tag) REQUIRE tag.tagNumber IS UNIQUE;

CREATE RANGE INDEX ciphos_test_vulnerability_confidence IF NOT EXISTS
FOR ()-[relationship:HAS_VULNERABILITY]-() ON (relationship.confidence);

MERGE (:CiphosEntity:Tag {tagNumber: 'TAG-LOCAL-1'})
MERGE (:CiphosEntity:Document {documentNumber: 'DOC-LOCAL-1'})
MERGE (:CiphosEntity:Vulnerability {cveId: 'CVE-LOCAL-1'})
MERGE (projection:CiphosProjection {graphSnapshotId: 'local-semantic-test'})
SET projection.status = 'ACTIVE';

MERGE (tag:CiphosEntity:Tag {tagNumber: 'TAG-LOCAL-2'})
MERGE (vulnerability:CiphosEntity:Vulnerability {cveId: 'CVE-LOCAL-2'})
MERGE (document:CiphosEntity:Document {documentNumber: 'DOC-LOCAL-2'})
MERGE (tag)-[vulnerability_link:HAS_VULNERABILITY]->(vulnerability)
SET vulnerability_link.confidence = 0.9
MERGE (tag)-[:REFERENCED_IN]->(document);
