# CIPHOS data architecture

CIPHOS keeps the complete, queryable data history in Databricks and exposes a
validated current-state asset graph in Neo4j. The Streamlit explorer combines
both systems for traceability. A separate NeoCarta store holds only structural
metadata used for semantic retrieval.

## What lives where: lakehouse vs. graph

Databricks holds the complete data history. Neo4j holds a validated
current-state subset used for traceability and connected-asset analysis.

| Data | Databricks (lakehouse) | Neo4j (graph) |
| --- | --- | --- |
| Raw CSV rows and ingestion provenance | Bronze | Not present |
| Typed facts, tag-property values, quality results | Silver | Not present |
| Source documents and document provenance | Silver | Not present |
| Current-state asset hierarchy (facility, plant, system, functional location, tag) | Not present | Operational graph |
| Equipment classes and manufacturer models | Not present | Operational graph |
| OT assets, network segments, asset zones, conduits | Not present | Operational graph |
| Vulnerabilities, threats, cyber incidents, security controls, risk assessments, compliance frameworks | Not present | Operational graph |
| Organizations | Not present | Operational graph |
| Graph schema (labels, relationship types, properties, constraints, indexes) and curated table/column metadata | Not present | Semantic store (NeoCarta, separate database) |

```text
     DATABRICKS LAKEHOUSE (complete data history)                     NEO4J (current-state graph)

                                                   projection
+------------------+      +--------------------+                +------------------------+
|      Bronze      |      |       Silver       |                |   Operational graph    |
|   raw rows and   |      |    typed facts,    |                |   assets, tags, OT,    |
|    provenance    |      |    tag-property    |                |         zones,         |
|                  |      |      values,       |                |    vulnerabilities,    |
|                  | ---->|     documents,     | -------------->|  risk, organizations   |
|                  |      |  quality results   |                |  (current state only)  |
+------------------+      +--------------------+                +------------------------+
                                     |                                       |
                     curated table/column                               schema only
                                  metadata                                   |
                                     |                                       v
       +---------------------------------------------------------------------------------+
       |                   NeoCarta semantic store (separate database)                   |
       |                     labels, relationship types, properties,                     |
       |                   constraints, indexes. No operational values.                  |
       +---------------------------------------------------------------------------------+
```

## Dataset and domain

This is a **synthetic industrial-facility information dataset**, not a live
plant historian or production system. It models the engineering, operations,
maintenance, OT, cybersecurity, risk, and document information needed to
operate a capital facility. The supplied export is one current-source snapshot,
so it supports traceability and connected-asset analysis but does not establish
business-effective history or a latest-value claim.

Within this repository, **CIPHOS** is the name used for the lakehouse, graph,
and demonstration project. The bundled ontology identifies the underlying
information model as **CFIHOS 2.0 with OT/cybersecurity extensions**. CFIHOS
stands for [Capital Facilities Information Handover Specification](https://www.jip36-cfihos.org/):
a standard for structured information handover across the lifecycle of
industrial facilities. The near-identical names should not be read as two
separate datasets or standards in this project.

### What the CIPHOS data contains

The CSV export represents a connected facility-information model. Its principal
entity groups include:

| Area | Examples in the dataset | Why it matters |
| --- | --- | --- |
| Physical asset hierarchy | facilities, plants, systems, functional locations, maintainable items, tags, equipment classes, and manufacturer models | Locates equipment and captures how facility assets fit together. |
| Engineering and maintenance | properties, units of measure, corrosion loops, disciplines, spare parts, and documents | Describes equipment characteristics and links them to supporting engineering evidence. |
| Operational technology | OT assets, network segments, asset zones, and conduits | Associates physical equipment with the systems and network zones that monitor or control it. |
| Cybersecurity and risk | vulnerabilities, threats, cyber incidents, security controls, risk assessments, and compliance frameworks | Supports questions about exposure, affected assets, mitigations, and obligations. |
| Organizations and records | organizations, document types, and documents | Records accountable parties and document context. |

Relationships turn these files into a facility graph. For example, a tag can
belong to a system and functional location, be classified as an equipment type,
have an OT representation, be connected to other tags, and be associated with
documents, zones, vulnerabilities, and controls. The contract defines 27 source
node types and 50 relationship types. The operational graph retains the
current-state asset and context relationships; the detailed property-value and
provenance records remain in Databricks.

### What tag data means

A **tag** is the stable identifier assigned to a physical or functional item in
an industrial facility. It is the common handle used to connect engineering,
operations, maintenance, documentation, and OT/cyber context. In this sample,
examples include `TT-1` (a temperature transmitter), `P-2` (a centrifugal pump),
`XV-3` (an isolation valve), and `E-4` (a shell-and-tube exchanger).

The `Tag.csv` record supplies the tag's core descriptive attributes: `tagNumber`,
description, status, equipment class, manufacturer, criticality, installation
date, and CFIHOS identifier. A tag-property-value record then states one
attribute of that tag, such as a pressure rating, temperature, material, or
other defined property, optionally with a unit. For example, one tag can have
several property-value records, and each can be traced to its source document.

Tag-property values are **asset metadata and engineering facts**, not a
high-frequency time-series telemetry feed. They are deliberately modeled at a
separate grain in Databricks so the full value history and document provenance
can be queried without making the operational Neo4j graph unnecessarily large.

```text
                    CIPHOS CSV export
                           |
                           v
                  +-------------------+
                  | Databricks Bronze |
                  | raw rows + loader |
                  | provenance        |
                  +-------------------+
                           |
                           v
                  +-------------------+
                  | Databricks Silver |
                  | typed facts,      |
                  | documents, and   |
                  | quality results  |
                  +-------------------+
                    |             |
          approved snapshot      | curated table/column metadata
                    |             v
                    v     +------------------------+
          +-------------------+  | NeoCarta semantic     |
          | Neo4j operational |--| store: graph schema   |
          | graph: current    |  | only, no operational  |
          | assets and links  |  | values                 |
          +-------------------+  +------------------------+
                    |                         |
                    +------------+------------+
                                 v
                    +--------------------------+
                    | Streamlit / read-only    |
                    | MCP clients               |
                    | facts + provenance +      |
                    | graph context             |
                    +--------------------------+
```

## Data flow

1. The lakehouse loader ingests every CSV row into Bronze Delta tables with
   source-file and row-level provenance.
2. It creates typed Silver tables and views, including tag-property facts,
   source-document provenance, snapshot information, and data-quality results.
3. A validated, published Silver snapshot is projected to the operational
   Neo4j database. This graph represents current asset structure and
   connections; tag-property-value records stay in Databricks.
4. NeoCarta extracts only the operational graph's labels, relationship types,
   properties, constraints, and indexes into a separately configured semantic
   store. Curated Silver table and column metadata can also be indexed for
   semantic search.
5. The demo and MCP services issue read-only queries, joining Databricks facts
   and provenance with Neo4j asset, OT, zone, and vulnerability context.

## Glossary

| Term | Meaning |
| --- | --- |
| Bronze | Raw Delta tables created from the CSV export, with ingestion and source provenance. |
| Silver | Cleaned, typed tables and views intended for supported analytical queries. |
| Gold | Derived analytical outputs, such as exposure paths and scores, with complete lineage. |
| CFIHOS | Capital Facilities Information Handover Specification, the industry information-handover model on which the supplied synthetic dataset is based. |
| CIPHOS | This repository's name for the CFIHOS-oriented lakehouse, graph, and demo project. |
| Source batch | Deterministic SHA-256 identifier for the ordered source-file checksums in an ingestion run. |
| Silver snapshot | A published, fixed source batch from which a graph projection may be built. |
| Graph snapshot | Immutable graph-build identifier that records the Silver snapshot, manifest version, and application revision. |
| Projection | The validated current-state subset of Silver data written to the operational Neo4j graph. |
| Operational graph | The Neo4j database used by the explorer for asset structure, OT assets, zones, and vulnerabilities. |
| Semantic store | A separate Neo4j database containing NeoCarta metadata, never CIPHOS operational values. |
| NeoCarta map | Structural description of a labeled property graph: labels, relationships, properties, constraints, indexes, and endpoints. |
| Provenance | Information that identifies where a fact came from, including its source file, row, checksum, and supporting document. |
| Tag-property value | A recorded value of a defined property for a tag. It is retained in Silver rather than projected into the operational graph. |
| Tag | Stable identifier for a physical or functional facility item, used to join engineering, operational, document, and cyber context. |
| Business key | Stable domain identifier for an entity, such as `tagNumber`, `documentNumber`, `otAssetId`, or `cveId`. |
| Run ID | Caller-supplied idempotency key for a graph calculation and its Gold publication. |
| Current-state | The source snapshot's represented state. It does not establish effective-dated history or a latest-value claim. |
| Source scope | Credential-free identifier that distinguishes one operational Neo4j URI-and-database pair in the semantic store. |
| Data quality result | Outcome of a contract check, such as required identifiers, numeric parsing, or expected graph endpoints. |
