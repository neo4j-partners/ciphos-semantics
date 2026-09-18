# CIPHOS lakehouse, graph, and demo

## Overview

This project loads CIPHOS CSV data into Databricks and Neo4j. It keeps the
full source data in Databricks. It builds a smaller, current-state graph in
Neo4j for connected questions.

The Streamlit demo reads both systems. It uses Databricks for property values
and documents. It uses Neo4j for asset connections, OT assets, zones, and
vulnerabilities.

## Quick start

Use these commands to install the project and check the local demo data. These
commands do not write to Databricks or Neo4j.

```sh
uv sync
cp .env.sample .env
make validate-all
make lakehouse-plan
```

`make validate-all` checks the data contract, code style, tests, and graph
plan. `make lakehouse-plan` prints the Databricks work without running it.

## Run the full demo

Set the Databricks and Neo4j values in `.env`. Start with `.env.sample`.

Run these commands in order:

```sh
make lakehouse-tables
make graph-activate
make demo
```

`make lakehouse-tables` loads the CSV files and builds the Databricks tables.
It uses four concurrent CSV-upload workers and four concurrent independent
Bronze-table workers by default. To tune this for the configured SQL warehouse,
set `CIPHOS_UPLOAD_WORKERS` and `CIPHOS_BRONZE_WORKERS`, or pass
`--upload-workers` and `--bronze-workers` to `ciphos-lakehouse`. Shared Delta
control and quarantine writes, plus Silver publication, remain ordered.
`make graph-activate` builds and activates a graph in the candidate Neo4j
database. `make demo` starts the Streamlit app.

Before you run `make graph-activate`, set these values in `.env`:

- **`CIPHOS_SILVER_SNAPSHOT_DIR`**: local folder with an approved Silver snapshot.
- **`CIPHOS_SOURCE_BATCH_ID`**: ID for the source data batch.
- **`CIPHOS_SOURCE_SNAPSHOT_ID`**: ID for the approved Silver snapshot.
- **`CIPHOS_GRAPH_SNAPSHOT_ID`**: new ID for this graph build.
- **`CIPHOS_APPLICATION_REVISION`**: version or commit ID for this build.
- **`CIPHOS_CANDIDATE_DATABASE`**: separate Neo4j database for the graph build.

The candidate database must differ from `OPS_NEO4J_DATABASE`. This protects the
graph used by the demo.

For the bundled local CSV export, the graph Make targets explicitly permit the
raw source and record `sourceMaterialization=raw-export` on the projection.
When `CIPHOS_SILVER_SNAPSHOT_DIR` is configured, that directory is used and
recorded as Silver instead. To require a Silver materialization even for the
Make targets, run `make graph-activate GRAPH_SOURCE_FLAGS=`.

## What it does

### Load CIPHOS data

The loader finds the CIPHOS node and relationship CSV files. It stores the raw
files in Bronze Delta tables. It then creates typed Silver tables for queries
and data checks.

### Build a Neo4j graph

The graph build uses an approved Silver snapshot. It checks the snapshot,
counts, labels, and relationship types before activation. Neo4j stores the
current asset structure and connections. Databricks keeps the full property
values and document history.

### Show asset traceability

The demo joins facts from Databricks with connected data from Neo4j. It can
show an asset's properties, documents, hierarchy, OT context, zones, and
vulnerabilities in one view.

### Create a structural map

The semantic commands create a separate NeoCarta-compatible map of the active
Neo4j graph structure. The map stores labels, relationship types, properties,
constraints, and indexes. It does not store operational values.

```sh
make semantic-contract
make semantic-ingest
make semantic-validate
make semantic-context
make semantic-mcp
```

Use separate `OPS_NEO4J_*` settings for the CIPHOS graph and `NEO4J_*` settings
for the semantic store. This keeps the structural map separate from the live
graph.

## Local development

[`docker-compose.semantic-test.yml`](docker-compose.semantic-test.yml) starts
an isolated CIPHOS-shaped source on port `17688`, an empty semantic store on
port `17689`, and an idempotent seed job. The normal Neo4j values in `.env` are
left in place. `NEO4J_LOCAL=true` switches only the running process to those
two local endpoints, so switching back is simply removing the flag or setting
it to `false`.

With Docker running, this one command runs the whole local acceptance flow. It
starts Compose, waits for the source to be seeded, ingests its structural map
into the local semantic store, validates the map against a fresh extraction,
ingests and validates a second time to prove the replacement is idempotent,
checks that endpoint extraction produced source and target links, proves a
scoped replacement leaves another source scope untouched, proves a rejected
write leaves no partial scope behind, retrieves the map through the read-only
MCP tool, and prints the resulting context:

```sh
uv sync
uv run ciphos-local
```

The seed deliberately covers every case the frozen contract cares about: a
multi-label node set, a label set that is the CIPHOS marker alone, a label set
with no properties, a label no node carries, a unique constraint, node and
relationship indexes, and one relationship type whose endpoints are genuinely
ambiguous.

One property flag cannot be proven locally. The containers run Neo4j
Community, where property-existence and node-key constraints are
Enterprise-only, so no local seed can make `existence` report `true`. The flag
is read from `SHOW CONSTRAINTS` through the same path as `unique`, which the
local flow does exercise, and its own behaviour is covered by the unit tests.

Use the same disposable environment for an individual command by prefixing it
with the flag. Your remote settings remain unchanged.

```sh
NEO4J_LOCAL=true uv run ciphos-semantic-context
NEO4J_LOCAL=true uv run ciphos-semantic-mcp --transport streamable-http
```

Remove the local containers and their Docker volumes when finished:

```sh
uv run ciphos-local down
```

`CIPHOS_TEST_NEO4J_PASSWORD` applies only to these disposable containers. The
existing `make semantic-local-up`, `make semantic-local-test`, and `make
semantic-local-down` targets remain available as short aliases.

## Main commands

- **`make validate-contract`**: checks the frozen CIPHOS data contract.
- **`make validate`**: checks the local graph projection.
- **`make validate-all`**: runs all local checks.
- **`make lakehouse-plan`**: prints the Databricks load plan without writes.
- **`make lakehouse-tables`**: loads data into Databricks and builds Bronze and Silver tables.
- **`make graph`**: builds and validates a candidate Neo4j graph.
- **`make graph-activate`**: builds, validates, and activates a candidate graph.
- **`make graph-counts`**: shows graph counts.
- **`make graph-verify`**: compares the graph with the CSV data.
- **`make demo`**: starts the Streamlit demo.
- **`make semantic-ingest`**: saves a fresh Neo4j structural map.
- **`make semantic-context`**: prints the saved structural map as JSON.
- **`make semantic-mcp`**: starts the read-only structural-map service at `http://127.0.0.1:8000/mcp`.
- **`make semantic-local-test`**: runs the complete semantic-map acceptance flow against disposable local Neo4j containers.
- **`make semantic-local-down`**: removes those containers and their volumes.

Run `make help` to see every command.

## Terms

- **Bronze table**: raw CSV data with load details.
- **Silver table**: cleaned and typed data used for queries.
- **Gold table**: final rows for reports, paths, exposure, and lineage.
- **Snapshot**: a fixed version of the source data.
- **Candidate graph**: a separate Neo4j graph that is checked before use.
- **Serving graph**: the active Neo4j graph used by the demo.
- **Projection**: the selected source data copied into Neo4j.
- **Semantic store**: a separate Neo4j database that holds graph structure only.
