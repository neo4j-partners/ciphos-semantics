
// ============================================================================
// CONSTRAINTS
// ============================================================================
CREATE CONSTRAINT organization_organizationId_unique IF NOT EXISTS FOR (n:Organization) REQUIRE n.organizationId IS UNIQUE;
CREATE CONSTRAINT plant_plantId_unique IF NOT EXISTS FOR (n:Plant) REQUIRE n.plantId IS UNIQUE;
CREATE CONSTRAINT facility_facilityId_unique IF NOT EXISTS FOR (n:Facility) REQUIRE n.facilityId IS UNIQUE;
CREATE CONSTRAINT system_systemId_unique IF NOT EXISTS FOR (n:System) REQUIRE n.systemId IS UNIQUE;
CREATE CONSTRAINT functionallocation_functionalLocationId_unique IF NOT EXISTS FOR (n:FunctionalLocation) REQUIRE n.functionalLocationId IS UNIQUE;
CREATE CONSTRAINT equipmentclass_classId_unique IF NOT EXISTS FOR (n:EquipmentClass) REQUIRE n.classId IS UNIQUE;
CREATE CONSTRAINT property_propertyId_unique IF NOT EXISTS FOR (n:Property) REQUIRE n.propertyId IS UNIQUE;
CREATE CONSTRAINT unitofmeasure_uomId_unique IF NOT EXISTS FOR (n:UnitOfMeasure) REQUIRE n.uomId IS UNIQUE;
CREATE CONSTRAINT discipline_disciplineId_unique IF NOT EXISTS FOR (n:Discipline) REQUIRE n.disciplineId IS UNIQUE;
CREATE CONSTRAINT documenttype_typeId_unique IF NOT EXISTS FOR (n:DocumentType) REQUIRE n.typeId IS UNIQUE;
CREATE CONSTRAINT document_documentNumber_unique IF NOT EXISTS FOR (n:Document) REQUIRE n.documentNumber IS UNIQUE;
CREATE CONSTRAINT manufacturermodel_modelId_unique IF NOT EXISTS FOR (n:ManufacturerModel) REQUIRE n.modelId IS UNIQUE;
CREATE CONSTRAINT corrosionloop_loopId_unique IF NOT EXISTS FOR (n:CorrosionLoop) REQUIRE n.loopId IS UNIQUE;
CREATE CONSTRAINT tag_tagNumber_unique IF NOT EXISTS FOR (n:Tag) REQUIRE n.tagNumber IS UNIQUE;
CREATE CONSTRAINT tagpropertyvalue_tpvId_unique IF NOT EXISTS FOR (n:TagPropertyValue) REQUIRE n.tpvId IS UNIQUE;
CREATE CONSTRAINT sparepart_partNumber_unique IF NOT EXISTS FOR (n:SparePart) REQUIRE n.partNumber IS UNIQUE;
CREATE CONSTRAINT maintainableitem_itemId_unique IF NOT EXISTS FOR (n:MaintainableItem) REQUIRE n.itemId IS UNIQUE;
CREATE CONSTRAINT assetzone_zoneId_unique IF NOT EXISTS FOR (n:AssetZone) REQUIRE n.zoneId IS UNIQUE;
CREATE CONSTRAINT conduit_conduitId_unique IF NOT EXISTS FOR (n:Conduit) REQUIRE n.conduitId IS UNIQUE;
CREATE CONSTRAINT networksegment_segmentId_unique IF NOT EXISTS FOR (n:NetworkSegment) REQUIRE n.segmentId IS UNIQUE;
CREATE CONSTRAINT otasset_otAssetId_unique IF NOT EXISTS FOR (n:OTAsset) REQUIRE n.otAssetId IS UNIQUE;
CREATE CONSTRAINT vulnerability_cveId_unique IF NOT EXISTS FOR (n:Vulnerability) REQUIRE n.cveId IS UNIQUE;
CREATE CONSTRAINT threat_threatId_unique IF NOT EXISTS FOR (n:Threat) REQUIRE n.threatId IS UNIQUE;
CREATE CONSTRAINT securitycontrol_controlId_unique IF NOT EXISTS FOR (n:SecurityControl) REQUIRE n.controlId IS UNIQUE;
CREATE CONSTRAINT complianceframework_frameworkId_unique IF NOT EXISTS FOR (n:ComplianceFramework) REQUIRE n.frameworkId IS UNIQUE;
CREATE CONSTRAINT riskassessment_assessmentId_unique IF NOT EXISTS FOR (n:RiskAssessment) REQUIRE n.assessmentId IS UNIQUE;
CREATE CONSTRAINT cyberincident_incidentId_unique IF NOT EXISTS FOR (n:CyberIncident) REQUIRE n.incidentId IS UNIQUE;

// ============================================================================
// NODES: Organization  (csv/nodes/Organization.csv)
// ============================================================================
LOAD CSV WITH HEADERS FROM $csvBase + 'nodes/Organization.csv' AS row
CALL {
  WITH row
  MERGE (n:Organization {organizationId: row.organizationId})
  SET n.organizationName = CASE WHEN row.organizationName = '' THEN null ELSE row.organizationName END,
      n.organizationRole = CASE WHEN row.organizationRole = '' THEN null ELSE row.organizationRole END
} IN TRANSACTIONS OF 5000 ROWS;

// ============================================================================
// NODES: Plant  (csv/nodes/Plant.csv)
// ============================================================================
LOAD CSV WITH HEADERS FROM $csvBase + 'nodes/Plant.csv' AS row
CALL {
  WITH row
  MERGE (n:Plant {plantId: row.plantId})
  SET n.name = CASE WHEN row.name = '' THEN null ELSE row.name END,
      n.country = CASE WHEN row.country = '' THEN null ELSE row.country END,
      n.cfihosId = CASE WHEN row.cfihosId = '' THEN null ELSE row.cfihosId END
} IN TRANSACTIONS OF 5000 ROWS;

// ============================================================================
// NODES: Facility  (csv/nodes/Facility.csv)
// ============================================================================
LOAD CSV WITH HEADERS FROM $csvBase + 'nodes/Facility.csv' AS row
CALL {
  WITH row
  MERGE (n:Facility {facilityId: row.facilityId})
  SET n.name = CASE WHEN row.name = '' THEN null ELSE row.name END,
      n.facilityType = CASE WHEN row.facilityType = '' THEN null ELSE row.facilityType END,
      n.cfihosId = CASE WHEN row.cfihosId = '' THEN null ELSE row.cfihosId END
} IN TRANSACTIONS OF 5000 ROWS;

// ============================================================================
// NODES: System  (csv/nodes/System.csv)
// ============================================================================
LOAD CSV WITH HEADERS FROM $csvBase + 'nodes/System.csv' AS row
CALL {
  WITH row
  MERGE (n:System {systemId: row.systemId})
  SET n.name = CASE WHEN row.name = '' THEN null ELSE row.name END,
      n.systemType = CASE WHEN row.systemType = '' THEN null ELSE row.systemType END,
      n.cfihosId = CASE WHEN row.cfihosId = '' THEN null ELSE row.cfihosId END
} IN TRANSACTIONS OF 5000 ROWS;

// ============================================================================
// NODES: FunctionalLocation  (csv/nodes/FunctionalLocation.csv)
// ============================================================================
LOAD CSV WITH HEADERS FROM $csvBase + 'nodes/FunctionalLocation.csv' AS row
CALL {
  WITH row
  MERGE (n:FunctionalLocation {functionalLocationId: row.functionalLocationId})
  SET n.name = CASE WHEN row.name = '' THEN null ELSE row.name END,
      n.hierarchyLevel = CASE WHEN row.hierarchyLevel IS NULL OR row.hierarchyLevel = '' THEN null ELSE toInteger(row.hierarchyLevel) END,
      n.cfihosId = CASE WHEN row.cfihosId = '' THEN null ELSE row.cfihosId END
} IN TRANSACTIONS OF 5000 ROWS;

// ============================================================================
// NODES: EquipmentClass  (csv/nodes/EquipmentClass.csv)
// ============================================================================
LOAD CSV WITH HEADERS FROM $csvBase + 'nodes/EquipmentClass.csv' AS row
CALL {
  WITH row
  MERGE (n:EquipmentClass {classId: row.classId})
  SET n.className = CASE WHEN row.className = '' THEN null ELSE row.className END,
      n.cfihosId = CASE WHEN row.cfihosId = '' THEN null ELSE row.cfihosId END
} IN TRANSACTIONS OF 5000 ROWS;

// ============================================================================
// NODES: UnitOfMeasure  (csv/nodes/UnitOfMeasure.csv)
// ============================================================================
LOAD CSV WITH HEADERS FROM $csvBase + 'nodes/UnitOfMeasure.csv' AS row
CALL {
  WITH row
  MERGE (n:UnitOfMeasure {uomId: row.uomId})
  SET n.uomSymbol = CASE WHEN row.uomSymbol = '' THEN null ELSE row.uomSymbol END,
      n.uomName = CASE WHEN row.uomName = '' THEN null ELSE row.uomName END
} IN TRANSACTIONS OF 5000 ROWS;

// ============================================================================
// NODES: Property  (csv/nodes/Property.csv)
// ============================================================================
LOAD CSV WITH HEADERS FROM $csvBase + 'nodes/Property.csv' AS row
CALL {
  WITH row
  MERGE (n:Property {propertyId: row.propertyId})
  SET n.propertyName = CASE WHEN row.propertyName = '' THEN null ELSE row.propertyName END,
      n.dataType = CASE WHEN row.dataType = '' THEN null ELSE row.dataType END,
      n.unitOfMeasureId = CASE WHEN row.unitOfMeasureId = '' THEN null ELSE row.unitOfMeasureId END,
      n.cfihosId = CASE WHEN row.cfihosId = '' THEN null ELSE row.cfihosId END
} IN TRANSACTIONS OF 5000 ROWS;

// ============================================================================
// NODES: Discipline  (csv/nodes/Discipline.csv)
// ============================================================================
LOAD CSV WITH HEADERS FROM $csvBase + 'nodes/Discipline.csv' AS row
CALL {
  WITH row
  MERGE (n:Discipline {disciplineId: row.disciplineId})
  SET n.disciplineName = CASE WHEN row.disciplineName = '' THEN null ELSE row.disciplineName END
} IN TRANSACTIONS OF 5000 ROWS;

// ============================================================================
// NODES: DocumentType  (csv/nodes/DocumentType.csv)
// ============================================================================
LOAD CSV WITH HEADERS FROM $csvBase + 'nodes/DocumentType.csv' AS row
CALL {
  WITH row
  MERGE (n:DocumentType {typeId: row.typeId})
  SET n.typeName = CASE WHEN row.typeName = '' THEN null ELSE row.typeName END,
      n.disciplineId = CASE WHEN row.disciplineId = '' THEN null ELSE row.disciplineId END,
      n.cfihosId = CASE WHEN row.cfihosId = '' THEN null ELSE row.cfihosId END
} IN TRANSACTIONS OF 5000 ROWS;

// ============================================================================
// NODES: Document  (csv/nodes/Document.csv)
// ============================================================================
LOAD CSV WITH HEADERS FROM $csvBase + 'nodes/Document.csv' AS row
CALL {
  WITH row
  MERGE (n:Document {documentNumber: row.documentNumber})
  SET n.documentTitle = CASE WHEN row.documentTitle = '' THEN null ELSE row.documentTitle END,
      n.documentTypeId = CASE WHEN row.documentTypeId = '' THEN null ELSE row.documentTypeId END,
      n.revision = CASE WHEN row.revision = '' THEN null ELSE row.revision END,
      n.status = CASE WHEN row.status = '' THEN null ELSE row.status END,
      n.cfihosId = CASE WHEN row.cfihosId = '' THEN null ELSE row.cfihosId END
} IN TRANSACTIONS OF 5000 ROWS;

// ============================================================================
// NODES: ManufacturerModel  (csv/nodes/ManufacturerModel.csv)
// ============================================================================
LOAD CSV WITH HEADERS FROM $csvBase + 'nodes/ManufacturerModel.csv' AS row
CALL {
  WITH row
  MERGE (n:ManufacturerModel {modelId: row.modelId})
  SET n.manufacturerName = CASE WHEN row.manufacturerName = '' THEN null ELSE row.manufacturerName END,
      n.modelNumber = CASE WHEN row.modelNumber = '' THEN null ELSE row.modelNumber END,
      n.cfihosId = CASE WHEN row.cfihosId = '' THEN null ELSE row.cfihosId END
} IN TRANSACTIONS OF 5000 ROWS;

// ============================================================================
// NODES: CorrosionLoop  (csv/nodes/CorrosionLoop.csv)
// ============================================================================
LOAD CSV WITH HEADERS FROM $csvBase + 'nodes/CorrosionLoop.csv' AS row
CALL {
  WITH row
  MERGE (n:CorrosionLoop {loopId: row.loopId})
  SET n.description = CASE WHEN row.description = '' THEN null ELSE row.description END,
      n.cfihosId = CASE WHEN row.cfihosId = '' THEN null ELSE row.cfihosId END
} IN TRANSACTIONS OF 5000 ROWS;

// ============================================================================
// NODES: Tag  (csv/nodes/Tag.csv)
// ============================================================================
LOAD CSV WITH HEADERS FROM $csvBase + 'nodes/Tag.csv' AS row
CALL {
  WITH row
  MERGE (n:Tag {tagNumber: row.tagNumber})
  SET n.tagDescription = CASE WHEN row.tagDescription = '' THEN null ELSE row.tagDescription END,
      n.tagStatus = CASE WHEN row.tagStatus = '' THEN null ELSE row.tagStatus END,
      n.equipmentClassId = CASE WHEN row.equipmentClassId = '' THEN null ELSE row.equipmentClassId END,
      n.manufacturer = CASE WHEN row.manufacturer = '' THEN null ELSE row.manufacturer END,
      n.criticalityClass = CASE WHEN row.criticalityClass = '' THEN null ELSE row.criticalityClass END,
      n.installationDate = CASE WHEN row.installationDate = '' THEN null ELSE row.installationDate END,
      n.cfihosId = CASE WHEN row.cfihosId = '' THEN null ELSE row.cfihosId END
} IN TRANSACTIONS OF 5000 ROWS;

// ============================================================================
// NODES: TagPropertyValue  (csv/nodes/TagPropertyValue.csv)
// ============================================================================
LOAD CSV WITH HEADERS FROM $csvBase + 'nodes/TagPropertyValue.csv' AS row
CALL {
  WITH row
  MERGE (n:TagPropertyValue {tpvId: row.tpvId})
  SET n.tagNumber = CASE WHEN row.tagNumber = '' THEN null ELSE row.tagNumber END,
      n.propertyId = CASE WHEN row.propertyId = '' THEN null ELSE row.propertyId END,
      n.value = CASE WHEN row.value = '' THEN null ELSE row.value END,
      n.unitOfMeasureId = CASE WHEN row.unitOfMeasureId = '' THEN null ELSE row.unitOfMeasureId END,
      n.cfihosId = CASE WHEN row.cfihosId = '' THEN null ELSE row.cfihosId END
} IN TRANSACTIONS OF 5000 ROWS;

// ============================================================================
// NODES: SparePart  (csv/nodes/SparePart.csv)
// ============================================================================
LOAD CSV WITH HEADERS FROM $csvBase + 'nodes/SparePart.csv' AS row
CALL {
  WITH row
  MERGE (n:SparePart {partNumber: row.partNumber})
  SET n.partDescription = CASE WHEN row.partDescription = '' THEN null ELSE row.partDescription END,
      n.recommendedQuantity = CASE WHEN row.recommendedQuantity IS NULL OR row.recommendedQuantity = '' THEN null ELSE toInteger(row.recommendedQuantity) END,
      n.criticality = CASE WHEN row.criticality = '' THEN null ELSE row.criticality END,
      n.cfihosId = CASE WHEN row.cfihosId = '' THEN null ELSE row.cfihosId END
} IN TRANSACTIONS OF 5000 ROWS;

// ============================================================================
// NODES: MaintainableItem  (csv/nodes/MaintainableItem.csv)
// ============================================================================
LOAD CSV WITH HEADERS FROM $csvBase + 'nodes/MaintainableItem.csv' AS row
CALL {
  WITH row
  MERGE (n:MaintainableItem {itemId: row.itemId})
  SET n.name = CASE WHEN row.name = '' THEN null ELSE row.name END,
      n.failureModeClass = CASE WHEN row.failureModeClass = '' THEN null ELSE row.failureModeClass END,
      n.cfihosId = CASE WHEN row.cfihosId = '' THEN null ELSE row.cfihosId END
} IN TRANSACTIONS OF 5000 ROWS;

// ============================================================================
// NODES: AssetZone  (csv/nodes/AssetZone.csv)
// ============================================================================
LOAD CSV WITH HEADERS FROM $csvBase + 'nodes/AssetZone.csv' AS row
CALL {
  WITH row
  MERGE (n:AssetZone {zoneId: row.zoneId})
  SET n.zoneName = CASE WHEN row.zoneName = '' THEN null ELSE row.zoneName END,
      n.iec62443Level = CASE WHEN row.iec62443Level = '' THEN null ELSE row.iec62443Level END,
      n.criticality = CASE WHEN row.criticality = '' THEN null ELSE row.criticality END,
      n.purdueLevel = CASE WHEN row.purdueLevel IS NULL OR row.purdueLevel = '' THEN null ELSE toInteger(row.purdueLevel) END
} IN TRANSACTIONS OF 5000 ROWS;

// ============================================================================
// NODES: Conduit  (csv/nodes/Conduit.csv)
// ============================================================================
LOAD CSV WITH HEADERS FROM $csvBase + 'nodes/Conduit.csv' AS row
CALL {
  WITH row
  MERGE (n:Conduit {conduitId: row.conduitId})
  SET n.name = CASE WHEN row.name = '' THEN null ELSE row.name END,
      n.protocol = CASE WHEN row.protocol = '' THEN null ELSE row.protocol END,
      n.encryption = CASE WHEN row.encryption IS NULL OR row.encryption = '' THEN null ELSE toBoolean(row.encryption) END
} IN TRANSACTIONS OF 5000 ROWS;

// ============================================================================
// NODES: NetworkSegment  (csv/nodes/NetworkSegment.csv)
// ============================================================================
LOAD CSV WITH HEADERS FROM $csvBase + 'nodes/NetworkSegment.csv' AS row
CALL {
  WITH row
  MERGE (n:NetworkSegment {segmentId: row.segmentId})
  SET n.vlanId = CASE WHEN row.vlanId = '' THEN null ELSE row.vlanId END,
      n.subnet = CASE WHEN row.subnet = '' THEN null ELSE row.subnet END,
      n.purdueLevel = CASE WHEN row.purdueLevel IS NULL OR row.purdueLevel = '' THEN null ELSE toInteger(row.purdueLevel) END
} IN TRANSACTIONS OF 5000 ROWS;

// ============================================================================
// NODES: OTAsset  (csv/nodes/OTAsset.csv)
// ============================================================================
LOAD CSV WITH HEADERS FROM $csvBase + 'nodes/OTAsset.csv' AS row
CALL {
  WITH row
  MERGE (n:OTAsset {otAssetId: row.otAssetId})
  SET n.tagNumber = CASE WHEN row.tagNumber = '' THEN null ELSE row.tagNumber END,
      n.deviceType = CASE WHEN row.deviceType = '' THEN null ELSE row.deviceType END,
      n.firmwareVersion = CASE WHEN row.firmwareVersion = '' THEN null ELSE row.firmwareVersion END,
      n.ipAddress = CASE WHEN row.ipAddress = '' THEN null ELSE row.ipAddress END,
      n.macAddress = CASE WHEN row.macAddress = '' THEN null ELSE row.macAddress END,
      n.vendor = CASE WHEN row.vendor = '' THEN null ELSE row.vendor END,
      n.purdueLevel = CASE WHEN row.purdueLevel IS NULL OR row.purdueLevel = '' THEN null ELSE toInteger(row.purdueLevel) END,
      n.isInternetFacing = CASE WHEN row.isInternetFacing IS NULL OR row.isInternetFacing = '' THEN null ELSE toBoolean(row.isInternetFacing) END
} IN TRANSACTIONS OF 5000 ROWS;

// ============================================================================
// NODES: Vulnerability  (csv/nodes/Vulnerability.csv)
// ============================================================================
LOAD CSV WITH HEADERS FROM $csvBase + 'nodes/Vulnerability.csv' AS row
CALL {
  WITH row
  MERGE (n:Vulnerability {cveId: row.cveId})
  SET n.description = CASE WHEN row.description = '' THEN null ELSE row.description END,
      n.cvssScore = CASE WHEN row.cvssScore IS NULL OR row.cvssScore = '' THEN null ELSE toFloat(row.cvssScore) END,
      n.severity = CASE WHEN row.severity = '' THEN null ELSE row.severity END,
      n.affectedFirmwareVersion = CASE WHEN row.affectedFirmwareVersion = '' THEN null ELSE row.affectedFirmwareVersion END,
      n.publishedDate = CASE WHEN row.publishedDate = '' THEN null ELSE row.publishedDate END
} IN TRANSACTIONS OF 5000 ROWS;

// ============================================================================
// NODES: Threat  (csv/nodes/Threat.csv)
// ============================================================================
LOAD CSV WITH HEADERS FROM $csvBase + 'nodes/Threat.csv' AS row
CALL {
  WITH row
  MERGE (n:Threat {threatId: row.threatId})
  SET n.name = CASE WHEN row.name = '' THEN null ELSE row.name END,
      n.threatActorType = CASE WHEN row.threatActorType = '' THEN null ELSE row.threatActorType END,
      n.mitreAttIckTechniqueId = CASE WHEN row.mitreAttIckTechniqueId = '' THEN null ELSE row.mitreAttIckTechniqueId END
} IN TRANSACTIONS OF 5000 ROWS;

// ============================================================================
// NODES: SecurityControl  (csv/nodes/SecurityControl.csv)
// ============================================================================
LOAD CSV WITH HEADERS FROM $csvBase + 'nodes/SecurityControl.csv' AS row
CALL {
  WITH row
  MERGE (n:SecurityControl {controlId: row.controlId})
  SET n.name = CASE WHEN row.name = '' THEN null ELSE row.name END,
      n.controlType = CASE WHEN row.controlType = '' THEN null ELSE row.controlType END,
      n.iec62443Requirement = CASE WHEN row.iec62443Requirement = '' THEN null ELSE row.iec62443Requirement END,
      n.implementationStatus = CASE WHEN row.implementationStatus = '' THEN null ELSE row.implementationStatus END
} IN TRANSACTIONS OF 5000 ROWS;

// ============================================================================
// NODES: ComplianceFramework  (csv/nodes/ComplianceFramework.csv)
// ============================================================================
LOAD CSV WITH HEADERS FROM $csvBase + 'nodes/ComplianceFramework.csv' AS row
CALL {
  WITH row
  MERGE (n:ComplianceFramework {frameworkId: row.frameworkId})
  SET n.frameworkName = CASE WHEN row.frameworkName = '' THEN null ELSE row.frameworkName END,
      n.version = CASE WHEN row.version = '' THEN null ELSE row.version END,
      n.applicableSector = CASE WHEN row.applicableSector = '' THEN null ELSE row.applicableSector END
} IN TRANSACTIONS OF 5000 ROWS;

// ============================================================================
// NODES: RiskAssessment  (csv/nodes/RiskAssessment.csv)
// ============================================================================
LOAD CSV WITH HEADERS FROM $csvBase + 'nodes/RiskAssessment.csv' AS row
CALL {
  WITH row
  MERGE (n:RiskAssessment {assessmentId: row.assessmentId})
  SET n.assessmentDate = CASE WHEN row.assessmentDate = '' THEN null ELSE row.assessmentDate END,
      n.likelihood = CASE WHEN row.likelihood = '' THEN null ELSE row.likelihood END,
      n.impact = CASE WHEN row.impact = '' THEN null ELSE row.impact END,
      n.riskScore = CASE WHEN row.riskScore IS NULL OR row.riskScore = '' THEN null ELSE toFloat(row.riskScore) END,
      n.residualRisk = CASE WHEN row.residualRisk = '' THEN null ELSE row.residualRisk END
} IN TRANSACTIONS OF 5000 ROWS;

// ============================================================================
// NODES: CyberIncident  (csv/nodes/CyberIncident.csv)
// ============================================================================
LOAD CSV WITH HEADERS FROM $csvBase + 'nodes/CyberIncident.csv' AS row
CALL {
  WITH row
  MERGE (n:CyberIncident {incidentId: row.incidentId})
  SET n.detectedDate = CASE WHEN row.detectedDate = '' THEN null ELSE row.detectedDate END,
      n.incidentType = CASE WHEN row.incidentType = '' THEN null ELSE row.incidentType END,
      n.severity = CASE WHEN row.severity = '' THEN null ELSE row.severity END,
      n.nis2Reportable = CASE WHEN row.nis2Reportable IS NULL OR row.nis2Reportable = '' THEN null ELSE toBoolean(row.nis2Reportable) END,
      n.reportedToAuthorityDate = CASE WHEN row.reportedToAuthorityDate = '' THEN null ELSE row.reportedToAuthorityDate END
} IN TRANSACTIONS OF 5000 ROWS;

// ============================================================================
// RELS: Plant -[:HAS_FACILITY]-> Facility  (csv/rels/HAS_FACILITY.csv)
// ============================================================================
LOAD CSV WITH HEADERS FROM $csvBase + 'rels/HAS_FACILITY.csv' AS row
CALL {
  WITH row
  MATCH (a:Plant {plantId: row.from})
  MATCH (b:Facility {facilityId: row.to})
  MERGE (a)-[:HAS_FACILITY]->(b)
} IN TRANSACTIONS OF 5000 ROWS;

// ============================================================================
// RELS: Facility -[:HAS_SYSTEM]-> System  (csv/rels/HAS_SYSTEM.csv)
// ============================================================================
LOAD CSV WITH HEADERS FROM $csvBase + 'rels/HAS_SYSTEM.csv' AS row
CALL {
  WITH row
  MATCH (a:Facility {facilityId: row.from})
  MATCH (b:System {systemId: row.to})
  MERGE (a)-[:HAS_SYSTEM]->(b)
} IN TRANSACTIONS OF 5000 ROWS;

// ============================================================================
// RELS: Facility -[:HAS_FUNCTIONAL_LOCATION]-> FunctionalLocation  (csv/rels/HAS_FUNCTIONAL_LOCATION.csv)
// ============================================================================
LOAD CSV WITH HEADERS FROM $csvBase + 'rels/HAS_FUNCTIONAL_LOCATION.csv' AS row
CALL {
  WITH row
  MATCH (a:Facility {facilityId: row.from})
  MATCH (b:FunctionalLocation {functionalLocationId: row.to})
  MERGE (a)-[:HAS_FUNCTIONAL_LOCATION]->(b)
} IN TRANSACTIONS OF 5000 ROWS;

// ============================================================================
// RELS: FunctionalLocation -[:PARENT_OF]-> FunctionalLocation  (csv/rels/PARENT_OF.csv)
// ============================================================================
LOAD CSV WITH HEADERS FROM $csvBase + 'rels/PARENT_OF.csv' AS row
CALL {
  WITH row
  MATCH (a:FunctionalLocation {functionalLocationId: row.from})
  MATCH (b:FunctionalLocation {functionalLocationId: row.to})
  MERGE (a)-[:PARENT_OF]->(b)
} IN TRANSACTIONS OF 5000 ROWS;

// ============================================================================
// RELS: EquipmentClass -[:SUBCLASS_OF]-> EquipmentClass  (csv/rels/SUBCLASS_OF.csv)
// ============================================================================
LOAD CSV WITH HEADERS FROM $csvBase + 'rels/SUBCLASS_OF.csv' AS row
CALL {
  WITH row
  MATCH (a:EquipmentClass {classId: row.from})
  MATCH (b:EquipmentClass {classId: row.to})
  MERGE (a)-[:SUBCLASS_OF]->(b)
} IN TRANSACTIONS OF 5000 ROWS;

// ============================================================================
// RELS: Tag -[:CLASSIFIED_AS]-> EquipmentClass  (csv/rels/CLASSIFIED_AS.csv)
// ============================================================================
LOAD CSV WITH HEADERS FROM $csvBase + 'rels/CLASSIFIED_AS.csv' AS row
CALL {
  WITH row
  MATCH (a:Tag {tagNumber: row.from})
  MATCH (b:EquipmentClass {classId: row.to})
  MERGE (a)-[:CLASSIFIED_AS]->(b)
} IN TRANSACTIONS OF 5000 ROWS;

// ============================================================================
// RELS: Tag -[:LOCATED_AT]-> FunctionalLocation  (csv/rels/LOCATED_AT.csv)
// ============================================================================
LOAD CSV WITH HEADERS FROM $csvBase + 'rels/LOCATED_AT.csv' AS row
CALL {
  WITH row
  MATCH (a:Tag {tagNumber: row.from})
  MATCH (b:FunctionalLocation {functionalLocationId: row.to})
  MERGE (a)-[:LOCATED_AT]->(b)
} IN TRANSACTIONS OF 5000 ROWS;

// ============================================================================
// RELS: System -[:CONTAINS_TAG]-> Tag  (csv/rels/CONTAINS_TAG.csv)
// ============================================================================
LOAD CSV WITH HEADERS FROM $csvBase + 'rels/CONTAINS_TAG.csv' AS row
CALL {
  WITH row
  MATCH (a:System {systemId: row.from})
  MATCH (b:Tag {tagNumber: row.to})
  MERGE (a)-[:CONTAINS_TAG]->(b)
} IN TRANSACTIONS OF 5000 ROWS;

// ============================================================================
// RELS: EquipmentClass -[:HAS_APPLICABLE_PROPERTY]-> Property  (csv/rels/HAS_APPLICABLE_PROPERTY.csv)
// ============================================================================
LOAD CSV WITH HEADERS FROM $csvBase + 'rels/HAS_APPLICABLE_PROPERTY.csv' AS row
CALL {
  WITH row
  MATCH (a:EquipmentClass {classId: row.from})
  MATCH (b:Property {propertyId: row.to})
  MERGE (a)-[:HAS_APPLICABLE_PROPERTY]->(b)
} IN TRANSACTIONS OF 5000 ROWS;

// ============================================================================
// RELS: Tag -[:HAS_PROPERTY_VALUE]-> TagPropertyValue  (csv/rels/HAS_PROPERTY_VALUE.csv)
// ============================================================================
LOAD CSV WITH HEADERS FROM $csvBase + 'rels/HAS_PROPERTY_VALUE.csv' AS row
CALL {
  WITH row
  MATCH (a:Tag {tagNumber: row.from})
  MATCH (b:TagPropertyValue {tpvId: row.to})
  MERGE (a)-[:HAS_PROPERTY_VALUE]->(b)
} IN TRANSACTIONS OF 5000 ROWS;

// ============================================================================
// RELS: TagPropertyValue -[:VALUE_OF]-> Property  (csv/rels/VALUE_OF.csv)
// ============================================================================
LOAD CSV WITH HEADERS FROM $csvBase + 'rels/VALUE_OF.csv' AS row
CALL {
  WITH row
  MATCH (a:TagPropertyValue {tpvId: row.from})
  MATCH (b:Property {propertyId: row.to})
  MERGE (a)-[:VALUE_OF]->(b)
} IN TRANSACTIONS OF 5000 ROWS;

// ============================================================================
// RELS: TagPropertyValue -[:MEASURED_IN]-> UnitOfMeasure  (csv/rels/MEASURED_IN.csv)
// ============================================================================
LOAD CSV WITH HEADERS FROM $csvBase + 'rels/MEASURED_IN.csv' AS row
CALL {
  WITH row
  MATCH (a:TagPropertyValue {tpvId: row.from})
  MATCH (b:UnitOfMeasure {uomId: row.to})
  MERGE (a)-[:MEASURED_IN]->(b)
} IN TRANSACTIONS OF 5000 ROWS;

// ============================================================================
// RELS: Property -[:DEFAULT_UNIT]-> UnitOfMeasure  (csv/rels/DEFAULT_UNIT.csv)
// ============================================================================
LOAD CSV WITH HEADERS FROM $csvBase + 'rels/DEFAULT_UNIT.csv' AS row
CALL {
  WITH row
  MATCH (a:Property {propertyId: row.from})
  MATCH (b:UnitOfMeasure {uomId: row.to})
  MERGE (a)-[:DEFAULT_UNIT]->(b)
} IN TRANSACTIONS OF 5000 ROWS;

// ============================================================================
// RELS: Tag -[:HAS_MODEL]-> ManufacturerModel  (csv/rels/HAS_MODEL.csv)
// ============================================================================
LOAD CSV WITH HEADERS FROM $csvBase + 'rels/HAS_MODEL.csv' AS row
CALL {
  WITH row
  MATCH (a:Tag {tagNumber: row.from})
  MATCH (b:ManufacturerModel {modelId: row.to})
  MERGE (a)-[:HAS_MODEL]->(b)
} IN TRANSACTIONS OF 5000 ROWS;

// ============================================================================
// RELS: Tag -[:RECOMMENDS_SPARE]-> SparePart  (csv/rels/RECOMMENDS_SPARE.csv)
// ============================================================================
LOAD CSV WITH HEADERS FROM $csvBase + 'rels/RECOMMENDS_SPARE.csv' AS row
CALL {
  WITH row
  MATCH (a:Tag {tagNumber: row.from})
  MATCH (b:SparePart {partNumber: row.to})
  MERGE (a)-[:RECOMMENDS_SPARE]->(b)
} IN TRANSACTIONS OF 5000 ROWS;

// ============================================================================
// RELS: Tag -[:HAS_MAINTAINABLE_ITEM]-> MaintainableItem  (csv/rels/HAS_MAINTAINABLE_ITEM.csv)
// ============================================================================
LOAD CSV WITH HEADERS FROM $csvBase + 'rels/HAS_MAINTAINABLE_ITEM.csv' AS row
CALL {
  WITH row
  MATCH (a:Tag {tagNumber: row.from})
  MATCH (b:MaintainableItem {itemId: row.to})
  MERGE (a)-[:HAS_MAINTAINABLE_ITEM]->(b)
} IN TRANSACTIONS OF 5000 ROWS;

// ============================================================================
// RELS: Tag -[:PART_OF_LOOP]-> CorrosionLoop  (csv/rels/PART_OF_LOOP.csv)
// ============================================================================
LOAD CSV WITH HEADERS FROM $csvBase + 'rels/PART_OF_LOOP.csv' AS row
CALL {
  WITH row
  MATCH (a:Tag {tagNumber: row.from})
  MATCH (b:CorrosionLoop {loopId: row.to})
  MERGE (a)-[:PART_OF_LOOP]->(b)
} IN TRANSACTIONS OF 5000 ROWS;

// ============================================================================
// RELS: Tag -[:CONNECTED_TO]-> Tag  (csv/rels/CONNECTED_TO.csv)
// ============================================================================
LOAD CSV WITH HEADERS FROM $csvBase + 'rels/CONNECTED_TO.csv' AS row
CALL {
  WITH row
  MATCH (a:Tag {tagNumber: row.from})
  MATCH (b:Tag {tagNumber: row.to})
  MERGE (a)-[r:CONNECTED_TO]->(b)
  SET r.connectionType = CASE WHEN row.connectionType = '' THEN null ELSE row.connectionType END
} IN TRANSACTIONS OF 5000 ROWS;

// ============================================================================
// RELS: Tag -[:REPLACES]-> Tag  (csv/rels/REPLACES.csv)
// ============================================================================
LOAD CSV WITH HEADERS FROM $csvBase + 'rels/REPLACES.csv' AS row
CALL {
  WITH row
  MATCH (a:Tag {tagNumber: row.from})
  MATCH (b:Tag {tagNumber: row.to})
  MERGE (a)-[r:REPLACES]->(b)
  SET r.revampDate = CASE WHEN row.revampDate = '' THEN null ELSE row.revampDate END
} IN TRANSACTIONS OF 5000 ROWS;

// ============================================================================
// RELS: Tag -[:REFERENCED_IN]-> Document  (csv/rels/REFERENCED_IN.csv)
// ============================================================================
LOAD CSV WITH HEADERS FROM $csvBase + 'rels/REFERENCED_IN.csv' AS row
CALL {
  WITH row
  MATCH (a:Tag {tagNumber: row.from})
  MATCH (b:Document {documentNumber: row.to})
  MERGE (a)-[:REFERENCED_IN]->(b)
} IN TRANSACTIONS OF 5000 ROWS;

// ============================================================================
// RELS: Document -[:HAS_DOCUMENT_TYPE]-> DocumentType  (csv/rels/HAS_DOCUMENT_TYPE.csv)
// ============================================================================
LOAD CSV WITH HEADERS FROM $csvBase + 'rels/HAS_DOCUMENT_TYPE.csv' AS row
CALL {
  WITH row
  MATCH (a:Document {documentNumber: row.from})
  MATCH (b:DocumentType {typeId: row.to})
  MERGE (a)-[:HAS_DOCUMENT_TYPE]->(b)
} IN TRANSACTIONS OF 5000 ROWS;

// ============================================================================
// RELS: DocumentType -[:BELONGS_TO_DISCIPLINE]-> Discipline  (csv/rels/BELONGS_TO_DISCIPLINE.csv)
// ============================================================================
LOAD CSV WITH HEADERS FROM $csvBase + 'rels/BELONGS_TO_DISCIPLINE.csv' AS row
CALL {
  WITH row
  MATCH (a:DocumentType {typeId: row.from})
  MATCH (b:Discipline {disciplineId: row.to})
  MERGE (a)-[:BELONGS_TO_DISCIPLINE]->(b)
} IN TRANSACTIONS OF 5000 ROWS;

// ============================================================================
// RELS: Document -[:AUTHORED_BY]-> Organization  (csv/rels/AUTHORED_BY.csv)
// ============================================================================
LOAD CSV WITH HEADERS FROM $csvBase + 'rels/AUTHORED_BY.csv' AS row
CALL {
  WITH row
  MATCH (a:Document {documentNumber: row.from})
  MATCH (b:Organization {organizationId: row.to})
  MERGE (a)-[:AUTHORED_BY]->(b)
} IN TRANSACTIONS OF 5000 ROWS;

// ============================================================================
// RELS: TagPropertyValue -[:SOURCED_FROM]-> Document  (csv/rels/SOURCED_FROM.csv)
// ============================================================================
LOAD CSV WITH HEADERS FROM $csvBase + 'rels/SOURCED_FROM.csv' AS row
CALL {
  WITH row
  MATCH (a:TagPropertyValue {tpvId: row.from})
  MATCH (b:Document {documentNumber: row.to})
  MERGE (a)-[:SOURCED_FROM]->(b)
} IN TRANSACTIONS OF 5000 ROWS;

// ============================================================================
// RELS: Plant -[:OPERATED_BY]-> Organization  (csv/rels/OPERATED_BY.csv)
// ============================================================================
LOAD CSV WITH HEADERS FROM $csvBase + 'rels/OPERATED_BY.csv' AS row
CALL {
  WITH row
  MATCH (a:Plant {plantId: row.from})
  MATCH (b:Organization {organizationId: row.to})
  MERGE (a)-[:OPERATED_BY]->(b)
} IN TRANSACTIONS OF 5000 ROWS;

// ============================================================================
// RELS: Tag -[:HAS_OT_REPRESENTATION]-> OTAsset  (csv/rels/HAS_OT_REPRESENTATION.csv)
// ============================================================================
LOAD CSV WITH HEADERS FROM $csvBase + 'rels/HAS_OT_REPRESENTATION.csv' AS row
CALL {
  WITH row
  MATCH (a:Tag {tagNumber: row.from})
  MATCH (b:OTAsset {otAssetId: row.to})
  MERGE (a)-[:HAS_OT_REPRESENTATION]->(b)
} IN TRANSACTIONS OF 5000 ROWS;

// ============================================================================
// RELS: OTAsset -[:MEMBER_OF_ZONE]-> AssetZone  (csv/rels/MEMBER_OF_ZONE.csv)
// ============================================================================
LOAD CSV WITH HEADERS FROM $csvBase + 'rels/MEMBER_OF_ZONE.csv' AS row
CALL {
  WITH row
  MATCH (a:OTAsset {otAssetId: row.from})
  MATCH (b:AssetZone {zoneId: row.to})
  MERGE (a)-[:MEMBER_OF_ZONE]->(b)
} IN TRANSACTIONS OF 5000 ROWS;

// ============================================================================
// RELS: OTAsset -[:CONNECTED_VIA]-> NetworkSegment  (csv/rels/CONNECTED_VIA.csv)
// ============================================================================
LOAD CSV WITH HEADERS FROM $csvBase + 'rels/CONNECTED_VIA.csv' AS row
CALL {
  WITH row
  MATCH (a:OTAsset {otAssetId: row.from})
  MATCH (b:NetworkSegment {segmentId: row.to})
  MERGE (a)-[:CONNECTED_VIA]->(b)
} IN TRANSACTIONS OF 5000 ROWS;

// ============================================================================
// RELS: AssetZone -[:HAS_CONDUIT]-> Conduit  (csv/rels/HAS_CONDUIT.csv)
// ============================================================================
LOAD CSV WITH HEADERS FROM $csvBase + 'rels/HAS_CONDUIT.csv' AS row
CALL {
  WITH row
  MATCH (a:AssetZone {zoneId: row.from})
  MATCH (b:Conduit {conduitId: row.to})
  MERGE (a)-[r:HAS_CONDUIT]->(b)
  SET r.direction = CASE WHEN row.direction = '' THEN null ELSE row.direction END
} IN TRANSACTIONS OF 5000 ROWS;

// ============================================================================
// RELS: Conduit -[:CONNECTS_TO_ZONE]-> AssetZone  (csv/rels/CONNECTS_TO_ZONE.csv)
// ============================================================================
LOAD CSV WITH HEADERS FROM $csvBase + 'rels/CONNECTS_TO_ZONE.csv' AS row
CALL {
  WITH row
  MATCH (a:Conduit {conduitId: row.from})
  MATCH (b:AssetZone {zoneId: row.to})
  MERGE (a)-[:CONNECTS_TO_ZONE]->(b)
} IN TRANSACTIONS OF 5000 ROWS;

// ============================================================================
// RELS: NetworkSegment -[:WITHIN_ZONE]-> AssetZone  (csv/rels/WITHIN_ZONE.csv)
// ============================================================================
LOAD CSV WITH HEADERS FROM $csvBase + 'rels/WITHIN_ZONE.csv' AS row
CALL {
  WITH row
  MATCH (a:NetworkSegment {segmentId: row.from})
  MATCH (b:AssetZone {zoneId: row.to})
  MERGE (a)-[:WITHIN_ZONE]->(b)
} IN TRANSACTIONS OF 5000 ROWS;

// ============================================================================
// RELS: OTAsset -[:HAS_VULNERABILITY]-> Vulnerability  (csv/rels/HAS_VULNERABILITY.csv)
// ============================================================================
LOAD CSV WITH HEADERS FROM $csvBase + 'rels/HAS_VULNERABILITY.csv' AS row
CALL {
  WITH row
  MATCH (a:OTAsset {otAssetId: row.from})
  MATCH (b:Vulnerability {cveId: row.to})
  MERGE (a)-[:HAS_VULNERABILITY]->(b)
} IN TRANSACTIONS OF 5000 ROWS;

// ============================================================================
// RELS: Vulnerability -[:EXPLOITED_BY]-> Threat  (csv/rels/EXPLOITED_BY.csv)
// ============================================================================
LOAD CSV WITH HEADERS FROM $csvBase + 'rels/EXPLOITED_BY.csv' AS row
CALL {
  WITH row
  MATCH (a:Vulnerability {cveId: row.from})
  MATCH (b:Threat {threatId: row.to})
  MERGE (a)-[:EXPLOITED_BY]->(b)
} IN TRANSACTIONS OF 5000 ROWS;

// ============================================================================
// RELS: Threat -[:TARGETS_ZONE]-> AssetZone  (csv/rels/TARGETS_ZONE.csv)
// ============================================================================
LOAD CSV WITH HEADERS FROM $csvBase + 'rels/TARGETS_ZONE.csv' AS row
CALL {
  WITH row
  MATCH (a:Threat {threatId: row.from})
  MATCH (b:AssetZone {zoneId: row.to})
  MERGE (a)-[:TARGETS_ZONE]->(b)
} IN TRANSACTIONS OF 5000 ROWS;

// ============================================================================
// RELS: SecurityControl -[:MITIGATES]-> Vulnerability  (csv/rels/MITIGATES.csv)
// ============================================================================
LOAD CSV WITH HEADERS FROM $csvBase + 'rels/MITIGATES.csv' AS row
CALL {
  WITH row
  MATCH (a:SecurityControl {controlId: row.from})
  MATCH (b:Vulnerability {cveId: row.to})
  MERGE (a)-[:MITIGATES]->(b)
} IN TRANSACTIONS OF 5000 ROWS;

// ============================================================================
// RELS: SecurityControl -[:APPLIED_TO_ZONE]-> AssetZone  (csv/rels/APPLIED_TO_ZONE.csv)
// ============================================================================
LOAD CSV WITH HEADERS FROM $csvBase + 'rels/APPLIED_TO_ZONE.csv' AS row
CALL {
  WITH row
  MATCH (a:SecurityControl {controlId: row.from})
  MATCH (b:AssetZone {zoneId: row.to})
  MERGE (a)-[:APPLIED_TO_ZONE]->(b)
} IN TRANSACTIONS OF 5000 ROWS;

// ============================================================================
// RELS: SecurityControl -[:APPLIED_TO_ASSET]-> OTAsset  (csv/rels/APPLIED_TO_ASSET.csv)
// ============================================================================
LOAD CSV WITH HEADERS FROM $csvBase + 'rels/APPLIED_TO_ASSET.csv' AS row
CALL {
  WITH row
  MATCH (a:SecurityControl {controlId: row.from})
  MATCH (b:OTAsset {otAssetId: row.to})
  MERGE (a)-[:APPLIED_TO_ASSET]->(b)
} IN TRANSACTIONS OF 5000 ROWS;

// ============================================================================
// RELS: RiskAssessment -[:ASSESSES]-> AssetZone  (csv/rels/ASSESSES.csv)
// ============================================================================
LOAD CSV WITH HEADERS FROM $csvBase + 'rels/ASSESSES.csv' AS row
CALL {
  WITH row
  MATCH (a:RiskAssessment {assessmentId: row.from})
  MATCH (b:AssetZone {zoneId: row.to})
  MERGE (a)-[:ASSESSES]->(b)
} IN TRANSACTIONS OF 5000 ROWS;

// ============================================================================
// RELS: RiskAssessment -[:CONSIDERS]-> Vulnerability  (csv/rels/CONSIDERS.csv)
// ============================================================================
LOAD CSV WITH HEADERS FROM $csvBase + 'rels/CONSIDERS.csv' AS row
CALL {
  WITH row
  MATCH (a:RiskAssessment {assessmentId: row.from})
  MATCH (b:Vulnerability {cveId: row.to})
  MERGE (a)-[:CONSIDERS]->(b)
} IN TRANSACTIONS OF 5000 ROWS;

// ============================================================================
// RELS: RiskAssessment -[:EVALUATES]-> Threat  (csv/rels/EVALUATES.csv)
// ============================================================================
LOAD CSV WITH HEADERS FROM $csvBase + 'rels/EVALUATES.csv' AS row
CALL {
  WITH row
  MATCH (a:RiskAssessment {assessmentId: row.from})
  MATCH (b:Threat {threatId: row.to})
  MERGE (a)-[:EVALUATES]->(b)
} IN TRANSACTIONS OF 5000 ROWS;

// ============================================================================
// RELS: CyberIncident -[:AFFECTS_ASSET]-> OTAsset  (csv/rels/AFFECTS_ASSET.csv)
// ============================================================================
LOAD CSV WITH HEADERS FROM $csvBase + 'rels/AFFECTS_ASSET.csv' AS row
CALL {
  WITH row
  MATCH (a:CyberIncident {incidentId: row.from})
  MATCH (b:OTAsset {otAssetId: row.to})
  MERGE (a)-[:AFFECTS_ASSET]->(b)
} IN TRANSACTIONS OF 5000 ROWS;

// ============================================================================
// RELS: CyberIncident -[:EXPLOITS]-> Vulnerability  (csv/rels/EXPLOITS.csv)
// ============================================================================
LOAD CSV WITH HEADERS FROM $csvBase + 'rels/EXPLOITS.csv' AS row
CALL {
  WITH row
  MATCH (a:CyberIncident {incidentId: row.from})
  MATCH (b:Vulnerability {cveId: row.to})
  MERGE (a)-[:EXPLOITS]->(b)
} IN TRANSACTIONS OF 5000 ROWS;

// ============================================================================
// RELS: CyberIncident -[:CAUSED_BY]-> Threat  (csv/rels/CAUSED_BY.csv)
// ============================================================================
LOAD CSV WITH HEADERS FROM $csvBase + 'rels/CAUSED_BY.csv' AS row
CALL {
  WITH row
  MATCH (a:CyberIncident {incidentId: row.from})
  MATCH (b:Threat {threatId: row.to})
  MERGE (a)-[:CAUSED_BY]->(b)
} IN TRANSACTIONS OF 5000 ROWS;

// ============================================================================
// RELS: CyberIncident -[:REPORTED_UNDER]-> ComplianceFramework  (csv/rels/REPORTED_UNDER.csv)
// ============================================================================
LOAD CSV WITH HEADERS FROM $csvBase + 'rels/REPORTED_UNDER.csv' AS row
CALL {
  WITH row
  MATCH (a:CyberIncident {incidentId: row.from})
  MATCH (b:ComplianceFramework {frameworkId: row.to})
  MERGE (a)-[r:REPORTED_UNDER]->(b)
  SET r.reportingDeadlineHours = CASE WHEN row.reportingDeadlineHours IS NULL OR row.reportingDeadlineHours = '' THEN null ELSE toInteger(row.reportingDeadlineHours) END
} IN TRANSACTIONS OF 5000 ROWS;

// ============================================================================
// RELS: SecurityControl -[:SATISFIES_REQUIREMENT]-> ComplianceFramework  (csv/rels/SATISFIES_REQUIREMENT.csv)
// ============================================================================
LOAD CSV WITH HEADERS FROM $csvBase + 'rels/SATISFIES_REQUIREMENT.csv' AS row
CALL {
  WITH row
  MATCH (a:SecurityControl {controlId: row.from})
  MATCH (b:ComplianceFramework {frameworkId: row.to})
  MERGE (a)-[:SATISFIES_REQUIREMENT]->(b)
} IN TRANSACTIONS OF 5000 ROWS;

// ============================================================================
// RELS: AssetZone -[:GOVERNED_BY]-> ComplianceFramework  (csv/rels/GOVERNED_BY.csv)
// ============================================================================
LOAD CSV WITH HEADERS FROM $csvBase + 'rels/GOVERNED_BY.csv' AS row
CALL {
  WITH row
  MATCH (a:AssetZone {zoneId: row.from})
  MATCH (b:ComplianceFramework {frameworkId: row.to})
  MERGE (a)-[:GOVERNED_BY]->(b)
} IN TRANSACTIONS OF 5000 ROWS;

// ============================================================================
// RELS: Organization -[:RESPONSIBLE_FOR_REPORTING]-> CyberIncident  (csv/rels/RESPONSIBLE_FOR_REPORTING.csv)
// ============================================================================
LOAD CSV WITH HEADERS FROM $csvBase + 'rels/RESPONSIBLE_FOR_REPORTING.csv' AS row
CALL {
  WITH row
  MATCH (a:Organization {organizationId: row.from})
  MATCH (b:CyberIncident {incidentId: row.to})
  MERGE (a)-[:RESPONSIBLE_FOR_REPORTING]->(b)
} IN TRANSACTIONS OF 5000 ROWS;

// ============================================================================
// POST-LOAD VERIFICATION (optional - run separately to sanity-check the load)
// ============================================================================
// Node counts per label:
// MATCH (n) RETURN labels(n)[0] AS label, count(n) AS count ORDER BY count DESC;
//
// Relationship counts per type:
// MATCH ()-[r]->() RETURN type(r) AS relType, count(r) AS count ORDER BY count DESC;
//
// Total nodes and relationships:
// MATCH (n) WITH count(n) AS nodeCount MATCH ()-[r]->() RETURN nodeCount, count(r) AS relCount;
