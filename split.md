# Proposal: CIPHOS lakehouse and Neo4j data architecture

## Repository implementation status

The v1 architecture contract is implemented in
[`contracts/ciphos-v1.json`](contracts/ciphos-v1.json), with a local baseline
validator at `src/ciphos_semantics/validate_contract.py`. The repository now has
contract-driven Bronze and first Silver SQL planning, a manifest-driven
candidate graph importer, and a Delta-plus-Neo4j traceability view. The local
acceptance suite verifies the 197,735-node / 826,724-relationship source
baseline and the 77,686-node / 373,908-relationship current-state projection.

The phase acceptance gates remain pending until a configured Databricks
warehouse and an isolated candidate Neo4j database complete the external
Bronze-to-Silver, graph candidate, hybrid, Gold-publication, and cutover runs.
No external system was changed while implementing this repository work.

## Key goal and objectives

### Project goal

Build a high-quality demonstration of how Databricks and Neo4j work together in
a production-oriented data architecture. The demonstration should make the role
of each platform obvious, show why both are useful, and avoid maintaining two
independent systems of record.

### Project objectives

- Use the lakehouse as the complete, governed, and replayable system of record
  for source data, detailed facts, and history.
- Use Neo4j as a rebuildable serving projection for connected, current-state
  questions such as attack paths, blast radius, dependency analysis, and OT/IT
  convergence.
- Use stable business identifiers and snapshot metadata so results can move
  safely between the two platforms.
- Return graph-derived results to governed Gold Delta tables for SQL, BI, and
  Genie.
- Demonstrate lakehouse-native, graph-native, and hybrid workloads instead of
  forcing every question into one engine.

### Objective of this proposal

Define the data ownership boundary, the first graph projection, the hybrid demo
experience, and a phased implementation plan. The split is based on data grain,
history, lifecycle, and access patterns. Reducing the graph size is a useful
consequence, but it is not the primary design goal.

## Decision summary

The lakehouse will contain a complete Bronze copy of every source node and
relationship file, typed and validated Silver models, and Gold analytical and
graph-derived results. Neo4j will contain only the connected current-state
projection required for graph questions.

Detailed tag-property values and their value-level provenance will remain in
Delta. The graph will retain the property vocabulary and classification model,
including `Property`, `UnitOfMeasure`, `HAS_APPLICABLE_PROPERTY`, and
`DEFAULT_UNIT`, because those structures explain which properties are valid for
an equipment class.

Neo4j is not a second system of record. Its projection must be reproducible from
a named and versioned Silver snapshot.

## Architecture principles

1. **One authoritative data plane:** Delta tables own source fidelity, canonical
   facts, history, and data-quality results.
2. **A purpose-built graph projection:** Neo4j contains relationships that
   support traversal, path finding, impact analysis, or graph algorithms.
3. **History in Delta, current connectivity in Neo4j:** Historical observations,
   assessments, and changes remain in the lakehouse. The graph receives the
   current or otherwise explicitly selected state.
4. **Shared identifiers, not hidden coupling:** Both platforms use stable keys
   such as `tag_number`, `ot_asset_id`, `document_number`, and `cve_id`.
5. **Rebuild instead of reconcile:** A graph release is built from a known
   Silver snapshot and published only after validation.
6. **Results return with lineage:** Gold graph outputs record the graph snapshot,
   algorithm version, calculation time, and source identifiers.
7. **Choose the engine by workload:** SQL aggregation stays in the lakehouse;
   multi-hop connected reasoning runs in Neo4j; combined questions use both.

## Target architecture

```text
Source systems and CSV exports
  -> Bronze Delta: complete, immutable source nodes and relationships
  -> Silver Delta: typed entities, facts, relationships, history, quality checks
       -> Neo4j: versioned current-state connected projection
       -> SQL and lakehouse-native analysis
  -> Neo4j paths, scores, communities, and impact results
  -> Gold Delta: row-oriented graph results joined to governed business facts
  -> Genie, dashboards, applications, and path visualizations
```

### Ownership and synchronization contract

| Concern | System responsible | Required contract |
| --- | --- | --- |
| Raw source fidelity | Bronze Delta | Preserve source values, file name, source row, ingestion time, batch ID, and checksum. |
| Canonical entities and facts | Silver Delta | Enforce stable keys, types, referential checks, and documented history rules. |
| Connected serving model | Neo4j | Build only from an approved Silver snapshot and projection manifest. |
| Graph calculations | Neo4j | Record algorithm, parameters, graph snapshot, and execution time. |
| Reporting and conversational analytics | Gold Delta | Store tabular results at a documented grain with source and graph lineage. |

No workflow should update the same business fact independently in both Delta
and Neo4j. A new graph version should replace or supersede the previous
projection after validation rather than relying on manual reconciliation.

## Recommended data placement

| Data area | Lakehouse responsibility | Neo4j projection |
| --- | --- | --- |
| Raw source data | Store every node and relationship export in Bronze. | Do not load raw files directly. |
| Asset register | Store canonical entities, attributes, and history. | Project current plants, facilities, systems, functional locations, tags, and hierarchy. |
| Classification vocabulary | Store equipment classes, properties, units, and definitions. | Keep equipment classes, properties, units, subclassing, applicable properties, and default units. |
| Tag-property values | Store typed values, units, revisions, and value-level provenance. | Do not create `TagPropertyValue` nodes or their four relationships. |
| Documents | Store complete metadata, revision history, and content references. | Project document identity and direct graph-relevant links such as `REFERENCED_IN`. |
| OT topology | Store full snapshots and change history. | Project current OT assets, segments, zones, conduits, and connectivity. |
| Vulnerabilities | Store observations and scan history. | Project active vulnerabilities and current exposure relationships. |
| Risks and incidents | Store complete assessment and incident history. | Project active, open, or otherwise selected graph-relevant records. |
| Maintenance and spares | Store detailed facts and reporting models by default. | Project only when a dependency or supply-impact graph use case requires them. |
| Graph results | Store versioned Gold outputs. | Calculate paths, ranks, communities, reachability, and impact. |

## First graph projection

The first implementation will remove detailed tag-property-value instances from
Neo4j while retaining their semantic vocabulary.

| Source file | Data rows | Lakehouse use | Neo4j use |
| --- | ---: | --- | --- |
| `nodes/TagPropertyValue.csv` | 120,049 | Bronze source plus typed Silver fact. | Exclude. |
| `rels/HAS_PROPERTY_VALUE.csv` | 120,049 | Bronze source and relationship validation. | Exclude because `tagNumber` is on the fact. |
| `rels/VALUE_OF.csv` | 120,049 | Bronze source and relationship validation. | Exclude because `propertyId` is on the fact. |
| `rels/MEASURED_IN.csv` | 92,669 | Bronze source and relationship validation. | Exclude because `unitOfMeasureId` is on the fact. |
| `rels/SOURCED_FROM.csv` | 120,049 | Bronze source and Silver provenance bridge. | Exclude from the first projection. |

This projection removes 120,049 nodes and 452,816 relationships from Neo4j.
The resulting graph contains approximately 77,686 nodes and 373,908
relationships. These counts are validation targets, not the reason for the
split.

### Why tag-property values belong in Delta

Tag-property values are detailed facts that users filter, type, compare,
aggregate, validate, and trace through document revisions. The source currently
mixes numeric and pick-list values in one string column, so the Silver model
must preserve the raw value and add typed representations.

The graph still keeps these useful semantic paths:

- Tag to equipment class.
- Equipment class to applicable property.
- Property to default unit.
- Tag to directly referenced document.

Questions about actual values and value-level source documents use Delta.
Questions about classification, topology, exposure, and impact use Neo4j.

## Lakehouse model

### Bronze

Create a raw Delta table for every node and relationship source. Bronze tables
preserve source column names and values and add ingestion metadata. Relationship
files must not be omitted simply because only Neo4j currently consumes them.
Keeping all relationships in Bronze makes the graph reproducible and auditable.

Each ingestion run should record the source file, source row, checksum, schema
version, ingestion time, batch ID, row count, status, and errors. Reprocessing
the same batch must be idempotent. Malformed rows should be quarantined with a
reason rather than silently discarded.

### Silver

Create canonical, typed tables for entities, relationships, and facts. The
tag-property-value fact should include at least:

- `tpv_id`
- `tag_number`
- `property_id`
- `raw_value`
- `value_type`
- `numeric_value`
- `text_value`
- `unit_of_measure_id`
- `source_batch_id`
- `parse_status`
- `source_revision` or `effective_at` when the source provides them
- `is_current` when source history is introduced

Keep `tag_property_value_sources` as a provenance bridge with one row per value
and source-document association. The current data is one-to-one, but the bridge
preserves the possibility that a value can be supported by more than one
document. Provide an enriched Silver view that joins values to property, unit,
and document metadata for common SQL and Genie questions.

The current source does not include enough temporal information to calculate a
true "latest value." An ingestion timestamp is not a business-effective date.
Until effective dates or revisions are added, summaries must be described as
current-snapshot summaries.

### Gold

Create row-oriented outputs instead of storing impacted assets only as arrays.
Recommended tables are:

- **`gold_tag_property_quality`:** Property coverage, missing units, invalid
  types, and missing provenance by tag, class, facility, and source snapshot.
- **`gold_asset_cyber_exposure`:** One row per source asset, impacted asset,
  and calculated path or exposure result.
- **`gold_graph_path_hops`:** One row per path and hop so SQL and Genie can
  explain a graph result.
- **`gold_graph_runs`:** Graph snapshot, algorithm name and version,
  parameters, start and completion times, output counts, and status.

Gold result rows should include stable business identifiers,
`source_snapshot_id`, `graph_snapshot_id`, `algorithm_version`, `run_id`,
and `computed_at`.

## Neo4j projection contract

Maintain an explicit, versioned manifest that identifies the Silver node and
relationship datasets included in the graph. The graph loader must:

- Validate the selected projection independently from complete Bronze and
  Silver source validation.
- Require every projected relationship endpoint to exist in the projection.
- Create uniqueness constraints and workload-driven indexes for stable
  identifiers.
- Load into a staging database or versioned graph context before publication.
- Attach or record the Silver batch, manifest version, application revision, and
  graph snapshot.
- Verify node counts, relationship counts, labels, relationship types, and
  representative paths before declaring the graph ready.

The loader must not silently ignore missing endpoints. Excluded relationships
are valid only when they are explicitly absent from the projection manifest.
The first release may use full snapshot rebuilds. Incremental projection can be
added after the architecture and contracts are proven.

## Demonstration experience

The application should identify which engine answers each part of a question.

### Lakehouse-native workloads

- Property completeness, missing units, and invalid values.
- Asset-register counts and criticality summaries.
- Document revision and provenance reporting.
- Maintenance and spare-parts coverage when the question is primarily an
  aggregation.

### Graph-native workloads

- Zone-to-zone attack paths through conduits.
- OT/IT convergence gaps between engineering tags and network-visible assets.
- Vulnerability blast radius and reachable critical equipment.
- Connected risk, threat, control, incident, and organizational responsibility
  paths.

### Primary hybrid demonstration

1. Delta identifies tags with high design pressure, missing units, anomalous
   property values, or another governed business condition.
2. The application passes stable tag identifiers to Neo4j.
3. Neo4j expands from those tags through OT representations, vulnerabilities,
   zones, conduits, controls, and downstream assets.
4. The graph calculation writes path and exposure results to Gold Delta tables.
5. SQL, Genie, or a dashboard enriches those results with property values,
   facilities, documents, and data-quality information.
6. A drill-through view displays the original Neo4j path and its supporting
   lakehouse facts.

The same pattern also works in reverse. Neo4j can first identify reachable or
impacted tags, after which Delta adds engineering values, history, quality, and
source-document provenance.

The existing full asset-traceability experience must become a hybrid query:
Delta supplies actual property values, units, and value-level source documents;
Neo4j supplies hierarchy, classification, OT context, and connected exposure.

## Implementation plan

All phases are initially **Pending**. A phase is complete only when its outcome,
checklist, and acceptance gate are satisfied.

### Phase 0: Freeze the architecture and baseline

**Status:** Pending

**Outcome:** Every workstream uses the same ownership, identity, schema,
snapshot, and acceptance contracts.

**Checklist:**

- [ ] Inventory every node and relationship source, key, endpoint, and
  destination.
- [ ] Record current source counts, graph counts, labels, relationship types,
  and representative query results.
- [ ] Define stable business keys and source, Silver, graph, and run identifiers.
- [ ] Approve the first versioned projection manifest.
- [ ] Confirm the retained property ontology and the five excluded source files.
- [ ] Assign each demo use case to lakehouse, graph, or hybrid execution.
- [ ] Save golden traceability, cyber-exposure, and impact examples for
  regression testing.

**Acceptance gate:** Every source has an owner and destination; projected
relationships have projected endpoints; shared identifiers and snapshot
semantics are documented; golden examples are saved.

### Phase 1: Build complete Bronze ingestion

**Status:** Pending

**Outcome:** Every node and relationship source is stored in Delta with enough
metadata to reproduce and audit a load.

**Checklist:**

- [ ] Extend discovery and ingestion from node files to both nodes and
  relationships.
- [ ] Preserve raw column names and values.
- [ ] Add source row, checksum, schema version, ingestion time, and batch
  metadata.
- [ ] Make repeated ingestion of the same batch idempotent.
- [ ] Detect schema drift before publication.
- [ ] Quarantine malformed rows instead of silently dropping them.
- [ ] Record file and batch results in an ingestion control table.

**Acceptance gate:** Every discovered CSV is registered; Bronze row counts match
the source exactly; replay produces no duplicates; quarantined rows retain a
reason and source location.

### Phase 2: Build Silver models and quality checks

**Status:** Pending

**Outcome:** Typed, canonical data supports SQL analysis and provides the only
approved source for graph construction.

**Checklist:**

- [ ] Create typed entity, relationship, and fact models.
- [ ] Split tag-property values into raw, numeric, and text representations.
- [ ] Build the value-to-document provenance bridge and enriched property view.
- [ ] Validate uniqueness, required fields, endpoint existence, and type
  compatibility.
- [ ] Publish data-quality results by batch and rule.
- [ ] Mark a Silver batch publishable only after required rules pass.
- [ ] Publish an immutable Silver snapshot for graph construction.

**Acceptance gate:** All 120,049 property-value facts and source links are
preserved; accepted values resolve to tags and properties; populated units
resolve; parsing exceptions are visible; no unsupported "latest value" claim is
made.

### Phase 3: Build the versioned Neo4j projection

**Status:** Pending

**Outcome:** Neo4j is reproducibly built from a published Silver snapshot rather
than directly from source CSV files.

**Checklist:**

- [ ] Implement the versioned node and relationship projection manifest.
- [ ] Keep asset, OT, cyber, selected risk and incident, document-reference, and
  property-ontology paths.
- [ ] Exclude `TagPropertyValue` and its four instance relationships.
- [ ] Add identifier constraints and workload-driven indexes.
- [ ] Validate every projected relationship endpoint.
- [ ] Record source batch, manifest version, graph snapshot, counts, rejected
  rows, duration, and application revision.
- [ ] Load and validate a candidate projection before activating it.
- [ ] Update graph queries that previously depended on property-value nodes.

**Acceptance gate:** The graph contains no property-value instance nodes or
excluded relationship types; counts match the manifest; all endpoints resolve;
retained graph-native queries return expected paths; a failed candidate can be
discarded without affecting the active graph.

### Phase 4: Implement the hybrid application

**Status:** Pending

**Outcome:** The demo visibly uses each platform for the workload it handles
best.

**Checklist:**

- [ ] Replace graph-only property traceability with a composed Delta and Neo4j
  workflow.
- [ ] Retrieve typed values, units, quality status, and value-level provenance
  from Delta.
- [ ] Retrieve hierarchy, classification, OT context, and exposure paths from
  Neo4j.
- [ ] Join results through stable identifiers.
- [ ] Display the source batch and graph snapshot used by the answer.
- [ ] Implement the property-condition-to-cyber-impact demonstration.
- [ ] Handle empty results, missing identifiers, stale snapshots, and partial
  service failures clearly.
- [ ] Keep data-access logic separate from UI rendering.

**Acceptance gate:** Hybrid traceability works without property-value nodes in
Neo4j; golden examples pass; the UI distinguishes lakehouse facts from graph
paths; snapshot mismatches and service failures are explicit.

### Phase 5: Publish graph-derived Gold outputs

**Status:** Pending

**Outcome:** SQL, BI, and Genie can consume graph insights without querying
Neo4j at report time.

**Checklist:**

- [ ] Select the primary Gold product, initially asset cyber exposure or
  reachable critical assets.
- [ ] Write one row per source, impacted entity, and path or score.
- [ ] Publish graph run metadata and path-hop details.
- [ ] Reconcile output rows to the Neo4j calculation.
- [ ] Make repeated publication for the same run idempotent.
- [ ] Join Gold results to Silver asset and property facts.
- [ ] Point a dashboard or Genie example at the Gold output.

**Acceptance gate:** Gold keys are unique at their documented grain; every
entity resolves to Silver; counts reconcile with Neo4j; a graph-derived question
can be answered using SQL alone.

### Phase 6: Automate validation and observability

**Status:** Pending

**Outcome:** Component and cross-platform behavior is testable and every run
produces auditable evidence.

**Checklist:**

- [ ] Add tests for schema normalization, typing, projection selection, and
  relationship validation.
- [ ] Add source-to-Bronze, Bronze-to-Silver, graph, hybrid, and Gold contract
  tests.
- [ ] Test malformed values, missing endpoints, schema drift, stale snapshots,
  and unavailable services.
- [ ] Record ingestion, quality, graph projection, and Gold run results in
  control tables.
- [ ] Produce a machine-readable acceptance report for each end-to-end run.
- [ ] Measure graph build time, representative query latency, and Gold
  publication time.

**Acceptance gate:** Required tests pass; counts reconcile across all layers;
golden hybrid examples pass; Graph and Gold outputs reference compatible
snapshots; no critical quality exception is silently waived.

### Phase 7: Dual run, cut over, and package the demo

**Status:** Pending

**Outcome:** The smaller projection replaces the full graph through a reversible
release, and a new operator can reproduce the demonstration.

**Checklist:**

- [ ] Keep the current graph available while the candidate projection runs in
  parallel.
- [ ] Compare retained labels, relationships, paths, and business results.
- [ ] Run the complete acceptance suite against the candidate.
- [ ] Exercise cutover and rollback before removing old graph data.
- [ ] Retain a restorable graph snapshot for an agreed rollback window.
- [ ] Document recovery, rerun, troubleshooting, and operator procedures.
- [ ] Update the README, architecture diagram, and demo script.
- [ ] Rehearse one lakehouse-native, one graph-native, and one hybrid story.
- [ ] Verify setup and execution from a clean environment.

**Acceptance gate:** Retained use cases pass; hybrid traceability replaces the
removed behavior; cutover and rollback are proven; active components reference
compatible snapshots; the demo is reproducible without undocumented repair.

## Parallel-agent delivery model

Use a contract-first model with one integration lead and three implementation
agents. Parallel coding starts only after Phase 0 contracts are approved and
committed. Each agent works from the same contract commit in a separate branch
and Git worktree. Agents may read the entire repository, but each agent has an
exclusive file set. No two active agents edit the same file.

### Roles and ownership

| Role | Scope | Exclusive files and artifacts |
| --- | --- | --- |
| Integration lead | Freeze contracts, create worktrees, review and merge branches, resolve integration issues, run shared-environment validation, and update project-wide documentation. | `split.md`, `README.md`, `Makefile`, `pyproject.toml`, `.env.sample`, shared configuration, release checklist, and shared contract documents. |
| Lakehouse agent | Build Bronze ingestion, typed Silver models, provenance, quality checks, and reconciliation tests. | `src/ciphos_semantics/build_lakehouse_tables.py`, lakehouse-only modules, and lakehouse-specific tests. |
| Graph agent | Build the Silver-to-Neo4j projection, constraints, graph validation, graph algorithms, and graph tests. | `src/ciphos_semantics/import_ciphos_graph.py`, graph-only modules, and graph-specific tests. |
| Hybrid demo and Gold agent | Build Delta-plus-Neo4j orchestration, Gold publication, lineage display, path drill-through, and demo tests. | `src/ciphos_semantics/demo/`, `src/ciphos_semantics/hybrid_data.py`, `src/ciphos_semantics/gold_contract.py`, and demo-specific tests. |

With a fifth workstream, assign independent acceptance testing, diagrams, and
operator documentation to a validation agent. With four agents, the integration
lead owns that work.

### Contracts to freeze before parallel work

- **Data-placement manifest:** Assign every source node and relationship to
  Bronze, Silver, Neo4j, Gold, or more than one layer with a documented purpose.
- **Identity contract:** Define stable entity keys and source batch, processing
  run, and graph snapshot identifiers consistently across systems.
- **Silver schema contract:** Define property typing, provenance, null rules,
  snapshot semantics, and rejection handling.
- **Projection contract:** Define node and relationship allowlists,
  current-state selection, retained ontology, and endpoint-integrity behavior.
- **Gold contract:** Define the grain, identifiers, scores, path representation,
  algorithm version, and lineage fields for graph outputs.
- **Use-case contract:** State which portion of every flagship question runs in
  Delta, which runs in Neo4j, and how the results join.
- **Reconciliation contract:** Record expected counts and allowed exceptions for
  the source, Bronze, Silver, graph, and Gold.

Implementation agents treat these contracts as read-only. A contract change
pauses affected workstreams, is made by the integration lead, and begins a new
synchronized work round from the revised contract commit.

### Parallel delivery waves

1. **Contract and discovery:** The lead freezes Phase 0 contracts. The lakehouse
   agent profiles source schemas, the graph agent inventories path dependencies,
   and the application agent captures golden responses.
2. **Independent implementation:** The lakehouse agent builds Bronze and Silver.
   The graph agent builds the manifest-driven projector against contract
   fixtures. The application agent builds adapters and Gold interfaces against
   mock responses. The lead builds the acceptance harness.
3. **Serialized integration:** The lead merges lakehouse work first, validates
   Silver, merges graph work next, validates the projection, then merges the
   hybrid and Gold work. Shared commands and configuration are updated only by
   the lead.
4. **Gold, migration, and release:** The graph agent owns calculation semantics,
   the application agent owns publication and consumption, the lakehouse agent
   owns Gold quality checks, and the lead owns dual-run comparison, cutover,
   rollback, and final rehearsal.

### Coordination and conflict rules

- Assign one owner to every new file before implementation starts.
- Keep shared files under integration-lead ownership throughout a parallel wave.
- If an agent needs a shared dependency or contract changed, it records the
  request in its handoff instead of editing the shared file.
- Use small commits that contain one observable outcome and its tests.
- Require every handoff to list changed files, validation commands and results,
  assumptions, contract conformance, and unresolved risks.
- Reject workstream branches that modify files outside their assigned ownership.
- Fix contract mismatches in the contract before choosing one implementation.
- Do not let multiple agents deploy to or mutate the same Databricks schema or
  Neo4j database concurrently.
- Use isolated non-production schemas and databases when available. Otherwise,
  the integration lead is the sole owner of all external writes.

## Assumptions

- The current CSV export is a demonstration input, not the long-term system of
  record.
- Stable business identifiers remain available across source batches.
- Databricks and Neo4j environments can store or expose matching snapshot
  metadata.
- The first release represents a current snapshot because the source lacks
  complete business-effective timestamps and revision history.
- The graph is read-oriented for the demo; authoritative corrections flow
  through the lakehouse pipeline.
- Existing full-graph behavior remains available during dual-run validation.

## Risks and mitigations

| Risk | Mitigation |
| --- | --- |
| Duplicate facts drift between platforms. | Make Silver authoritative and rebuild Neo4j from a recorded snapshot. |
| Delta and Neo4j answers use different snapshots. | Require compatibility checks and display lineage in the application. |
| Schema inference changes across source batches. | Version schemas, detect drift, and quarantine unexpected records before publication. |
| A relationship endpoint is absent from the projection. | Validate the manifest and all endpoints before graph publication. |
| Generic string values create incorrect comparisons. | Preserve raw values and add typed Silver columns with visible parsing exceptions. |
| Removing property-value nodes breaks traceability. | Replace graph-only traceability with a tested hybrid workflow before cutover. |
| Gold results are difficult to query or explain. | Store one result or hop per row with run, path, algorithm, and snapshot identifiers. |
| The demo uses Neo4j for simple aggregation. | Route summaries and quality reporting to SQL and reserve graph execution for connected questions. |
| Parallel agents create conflicting changes. | Freeze contracts, use separate worktrees, assign exclusive file ownership, and serialize integration. |
| Candidate graph replacement is destructive. | Use dual run, candidate validation, a rollback window, and a restorable prior snapshot. |

## Completion criteria

The proposal is fully implemented when:

- Every source node and relationship is reproducibly stored in Bronze Delta.
- Silver contains typed canonical facts, relationship-integrity checks, quality
  results, and versioned snapshots.
- Neo4j can be cleared and rebuilt deterministically from a named Silver
  snapshot and projection manifest.
- Detailed tag-property values are absent from Neo4j while classification and
  property semantics remain available.
- Graph results return to lineage-rich, row-oriented Gold tables.
- The application clearly demonstrates one lakehouse-native, one graph-native,
  and one end-to-end hybrid workflow.
- Automated validation proves count integrity, endpoint integrity, snapshot
  consistency, representative paths, idempotency, and graph rebuildability.
- Cutover and rollback have been exercised without deleting authoritative data.
- Documentation explains ownership, operation, recovery, and the reason each
  workload runs where it does.
