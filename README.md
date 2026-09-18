# CIPHOS lakehouse and Neo4j projection

This demonstration keeps CIPHOS source fidelity, typed facts, history, and
governed reporting in Databricks Delta. Neo4j is a rebuildable, current-state
serving projection for connected questions. It is not a second system of
record.

The first projection deliberately excludes the 120,049 `TagPropertyValue`
instances and their `HAS_PROPERTY_VALUE`, `VALUE_OF`, `MEASURED_IN`, and
`SOURCED_FROM` relationships. Actual property values and value-level document
provenance are queried from Delta; Neo4j retains asset hierarchy, property
vocabulary, OT topology, cyber context, and direct document references.

## Validate the contracts

Install the environment and inspect the frozen source and projection baseline:

```sh
uv sync
cp .env.sample .env  # add connection details when running external services
make validate-all    # contract, lint, unit tests, and the projection check
make lakehouse-plan  # print every Bronze and Silver statement without writing
```

The local fixture baseline is 197,735 nodes and 826,724 relationships. The
current-state graph manifest validates 77,686 nodes and 373,908 relationships.
The machine-readable ownership, identity, snapshot, and Gold-grain contract is
in [`contracts/ciphos-v1.json`](contracts/ciphos-v1.json).

## Repository layout

```text
src/ciphos_semantics/
  contract.py                 frozen contract loader, the single source of truth
  graph_projection_manifest.py  bundled manifest derived from the contract
  build_lakehouse_tables.py   Bronze and Silver statement planner and loader
  import_ciphos_graph.py      manifest-driven Neo4j candidate projection
  validate_contract.py        source inventory and baseline check
  hybrid_data.py              read-only Delta and Neo4j adapters, no Streamlit
  gold_contract.py            Gold row grain and idempotency helpers
  demo/                       the hybrid traceability Streamlit application
contracts/ciphos-v1.json      the frozen contract
tests/                        unit tests; no external service is contacted
```

Node and relationship allowlists, quality rule names, and count baselines are
written down once, in the contract. The manifest, the importer exclusions, and
the Silver quality rules are all derived from it, and `make test` fails if any
of them drift.

## Data ownership and workflow

```text
CSV exports
  -> Bronze Delta: every node and relationship file, raw values plus ingestion metadata
  -> Silver Delta: typed facts, provenance, quality, immutable source snapshot
       -> Neo4j candidate projection: connected current-state model
       -> lakehouse SQL and data-quality workloads
  -> Neo4j paths and exposure calculations
  -> Gold Delta: row-oriented paths, exposure, run, and lineage outputs
```

`ciphos-lakehouse` discovers all 27 node and 47 relationship CSVs. It writes
raw source columns as strings in `bronze_node_*` and `bronze_relationship_*`,
with checksum, schema, source-row, batch, and ingestion metadata. The upload
stamps each file's real 1-based CSV line number, so `source_row_number` points
at an actual line rather than at an ordering the query engine invented.
Control and quarantine tables make a published batch replayable.

Every Delta column is lowercase `snake_case`, the Databricks and Unity Catalog
convention. The CSV exports use camelCase, so each load starts with a single
`conformed` CTE that renames the header once, at the Bronze read boundary. That
CTE is the only place a query sees the file's own spelling; every predicate,
projection, and insert after it has one spelling to get right. The original
header is kept as a column comment and folded into the schema hash, so a
renamed source column still trips drift detection.

Silver publishes typed `TagPropertyValue` facts and their value-to-document
provenance into two append-only snapshot tables. A published snapshot is never
rewritten: the current views, the enriched application view, and the
data-quality results are all pinned to one `silver_snapshot_id`. The enriched
view aggregates source documents, so it stays one row per value.

The graph importer accepts a local materialization of an approved Silver
snapshot, selected by the bundled v1 projection manifest. It validates every
relationship endpoint before connecting to Neo4j, requires source and graph
snapshot identifiers, records a `CiphosProjection` release node carrying a
content digest of the files it actually read, and validates counts, labels,
relationship types, and exclusion rules.

Three rules keep a build from damaging what is being served. A candidate must
target `CIPHOS_CANDIDATE_DATABASE`, which has to differ from the serving
`NEO4J_DATABASE`. A graph snapshot ID can be claimed once, so a reused ID is
an error rather than a silent overwrite of earlier lineage. Activation that
matches no validated snapshot fails instead of quietly doing nothing. Relationship
identity is the endpoint pair, so a changed property updates the existing edge
rather than adding a parallel one. Do not use `--clear` against an active graph
database.

Projecting the raw export instead of a published Silver materialization
requires `--allow-raw-source`, and the projection node records that it was
built from `raw-export`.

The Streamlit demo’s **Hybrid asset traceability** use case visibly composes
both platforms: Delta returns property facts, units, parse state, and source
documents; Neo4j returns hierarchy, classification, OT assets, zones, and
vulnerabilities. It displays both snapshot identifiers and makes service
failures or incompatible source snapshots explicit.

## External-service runs

Set the Databricks warehouse and Neo4j settings in `.env`, then run:

```sh
make lakehouse-tables

# Materialize the published Silver snapshot to CIPHOS_SILVER_SNAPSHOT_DIR,
# set the CIPHOS_* snapshot identifiers, and use an isolated candidate database.
make graph
make graph-activate

make demo
```

`make graph` validates a candidate but does not mark it active. `make
graph-activate` performs a separately configured candidate build and records
it as active only after validation. `make graph-clear` deletes only
`:CiphosEntity` nodes in the configured candidate database before rebuilding.

Run `make help` for all commands. External Databricks and Neo4j writes are
intentionally not performed by the local validation suite.
