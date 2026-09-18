# CIPHOS lakehouse, graph, and demo

## Overview

This project moves CIPHOS CSV data into Databricks and Neo4j, then demos it.

- **Databricks holds everything**: Every CSV row lands in Databricks. This keeps the full history of properties and documents.
- **Neo4j holds a current-state graph**: A smaller graph in Neo4j answers connected questions, like which assets link to which zones.
- **The Streamlit demo reads both**: It reads property values and documents from Databricks. It reads asset connections, OT assets, zones, and vulnerabilities from Neo4j.

## Quick start

Run this flow once to load data into Databricks, build the Neo4j graph, and build the NeoCarta semantic map.

```sh
uv sync
cp .env.sample .env
```

Open `.env` and fill in the required values. See [Setting up your environment](#setting-up-your-environment) for the full list.

```sh
make lakehouse-tables
make graph
make semantic-ingest
```

- **`make lakehouse-tables`**: Loads the CIPHOS CSV files into Databricks. It builds raw Bronze tables, then typed Silver tables for queries.
- **`make graph`**: Builds the Neo4j graph the demo reads, straight into your configured `OPS_NEO4J_DATABASE`.
- **`make semantic-ingest`**: Builds the NeoCarta structural map of the graph, then indexes the curated Silver tables for semantic search. This one command always does both steps. There is no separate index command to run.

A few things to know before you run these commands:

- **The bundled sample data is a raw export**: `make graph` allows this by default. Set `CIPHOS_SILVER_SNAPSHOT_DIR` in `.env` to require an approved Silver snapshot instead.
- **You can check first without writing anything**: `make validate-all` checks the data contract, code style, and tests. `make lakehouse-plan` prints the Databricks load plan without running it.

## Local development

Test the semantic map end to end against disposable local containers, with no real Neo4j or Databricks involved.

With Docker running:

```sh
uv sync
uv run ciphos-local
```

This one command starts the local containers, seeds test data, and runs the full acceptance flow (ingest, validate, retrieve). It sets `NEO4J_LOCAL=true` for itself, so your `.env` stays untouched.

To run a single extra command against the same local stack, set the flag yourself:

```sh
NEO4J_LOCAL=true uv run ciphos-semantic-context
```

When you are done, remove the containers and their data:

```sh
uv run ciphos-local down
```

- **`make semantic-local-up`**, **`make semantic-local-test`**, and **`make semantic-local-down`** are shortcuts for the commands above.
- **`CIPHOS_TEST_NEO4J_PASSWORD`** sets the password for these disposable containers only.
- **One known gap**: the containers run Neo4j Community, so the local flow cannot test property-existence constraints. Those are Enterprise-only. Unit tests cover that case instead.

## Running the demo

The demo has two parts. Start the server first, then run the CLI in a second terminal.

```sh
make semantic-search-mcp
```

Leave this running. It serves NeoCarta search and CIPHOS graph context at `http://127.0.0.1:8010/mcp`.
Choose a different available port with `make semantic-search-mcp MCP_SEARCH_PORT=8015`.

```sh
uv run ciphos-semantic-query
```

This runs a showcase of exact, conceptual, and hybrid lookups, then generates a grounded SQL query.

To ask one question directly, skip the showcase:

```sh
uv run ciphos-semantic-query \
  "Which tags have high pressure readings and which source documents support them?"
```

## Setting up your environment

Set these values in `.env` once. Start from `.env.sample`.

**Databricks connection**

- **`DATABRICKS_PROFILE`**: Name of the Databricks CLI profile to use.
- **`DATABRICKS_WAREHOUSE_ID`**: SQL warehouse that runs the lakehouse load. Required for `make lakehouse-tables`.
- **`CIPHOS_CATALOG`**: Unity Catalog catalog name for CIPHOS tables.
- **`CIPHOS_SCHEMA`**: Unity Catalog schema name for CIPHOS tables.
- **`CIPHOS_VOLUME`**: Unity Catalog volume that holds the uploaded CSV files.

**CIPHOS operational graph (Neo4j)**

- **`OPS_NEO4J_URI`**: Connection URI for the CIPHOS graph. Use `neo4j+s://` for Aura or `bolt://` for a local server.
- **`OPS_NEO4J_USERNAME`**: Username for the CIPHOS graph.
- **`OPS_NEO4J_PASSWORD`**: Password for the CIPHOS graph.
- **`OPS_NEO4J_DATABASE`**: The database `make graph` writes to and the demo reads from.

**Graph build identifiers**

These are required for `make graph` when you use an approved Silver snapshot instead of the bundled sample data.

- **`CIPHOS_SILVER_SNAPSHOT_DIR`**: Local folder holding the approved Silver snapshot.
- **`CIPHOS_SOURCE_BATCH_ID`**: ID of the source data batch.
- **`CIPHOS_SOURCE_SNAPSHOT_ID`**: ID of the approved Silver snapshot.
- **`CIPHOS_GRAPH_SNAPSHOT_ID`**: New ID you assign to this graph build.
- **`CIPHOS_APPLICATION_REVISION`**: Version or commit ID for this build.

**NeoCarta semantic store (Neo4j)**

This is a separate Neo4j database. It stores graph structure only, never operational values. NeoCarta reads these bare `NEO4J_*` names directly, so keep them pointed at a different instance or database than the operational graph above.

- **`NEO4J_URI`**: Connection URI for the semantic store.
- **`NEO4J_USERNAME`**: Username for the semantic store.
- **`NEO4J_PASSWORD`**: Password for the semantic store.
- **`NEO4J_DATABASE`**: Database name in the semantic store.
- **`CIPHOS_SEMANTIC_SOURCE_SCOPE`** (optional): Scope ID to pick one CIPHOS map when the semantic store holds more than one.

**Semantic search**

- **`CIPHOS_SEMANTIC_EMBEDDING_MODEL`**: Set to `databricks/system.ai.gte-large-en`. NeoCarta calls the Databricks Model Serving API, so it resolves this to your workspace's `databricks-gte-large-en` endpoint automatically.
- **`CIPHOS_SEMANTIC_LLM_ENDPOINT`**: Name of a Databricks Foundation Model serving endpoint.
- **`CIPHOS_SEMANTIC_TABLES`** (optional): Comma-separated list that overrides the default curated Silver views. Do not add Bronze tables or append-only `*_snapshots` tables here. They are loader internals or history, not the supported analytical model.

**Other settings**

- **`CIPHOS_DATA_DIR`**: Folder the importer reads node and relationship CSVs from. Defaults to `ciphos_data/csv`.
- **`IMPORT_BATCH_SIZE`**: Row batch size for graph import.
- **`CIPHOS_BATCH_ID`** (optional): Fixed source batch ID. Leave unset to derive it from the file checksums.
- **`CIPHOS_STATEMENT_TIMEOUT_SECONDS`** (optional): Seconds to wait for one Databricks SQL statement before cancelling it.
- **`CIPHOS_SILVER_SCHEMA`** and **`CIPHOS_SILVER_PROPERTY_VIEW`** (optional): Override which Delta view the Streamlit demo reads for property values.

## Streamlit demo

```sh
make demo
```

The explorer automatically selects the first available local port from
**8503–8599**, leaving Streamlit's standard 8501 available for another app.
Choose a fixed port when needed:

```sh
make demo DEMO_PORT=8510
```

This starts a four-page Streamlit explorer:

- **Lakehouse** browses contract-allowlisted Bronze and Silver tables with real sample rows.
- **Operational graph** renders a bounded Neo4j subgraph from a selected CIPHOS entity.
- **Traceability** joins a tag's Databricks facts and provenance with its Neo4j hierarchy, OT, and cyber context.
- **Architecture & glossary** explains the data flow and CIPHOS vocabulary.

Every query is read-only. The graph page caps a rendering at 150 nodes and the
lakehouse page caps a sample at 10 rows.

## What it does

**Load CIPHOS data**

- **Bronze step**: The loader finds the CIPHOS CSV files and stores them as raw Bronze Delta tables.
- **Silver step**: The loader then builds typed Silver tables from Bronze, ready for queries and data checks.

**Build a Neo4j graph**

- **Checks during the build**: The graph build reads an approved Silver snapshot, then checks its counts, labels, and relationship types.
- **What each side stores**: Neo4j stores the current asset structure and connections. Databricks stores the full property history and documents.

**Show asset traceability**

- The Streamlit demo joins Databricks facts with Neo4j connections. It shows an asset's properties, documents, hierarchy, OT context, zones, and vulnerabilities in one view.

**Create a structural map for NeoCarta**

- **What it stores**: labels, relationship types, properties, constraints, and indexes from the active Neo4j graph.
- **What it never stores**: operational values from the graph.
- **Why the settings are separate**: `OPS_NEO4J_*` configures the CIPHOS graph. `NEO4J_*` configures the semantic store. Separate settings keep the structural map isolated from the live graph.

**Search the curated Silver model**

- **What gets indexed**: table and column metadata from four curated Silver views: `silver_tag_property_value_enriched` for tag-property traceability, `silver_tag_property_value_sources` for row-level provenance, `silver_snapshots` for publication freshness, and `silver_data_quality_results` for snapshot contract checks.
- **What never gets indexed**: Bronze exports, raw measurements, documents, OT assets, and graph property values. Only Unity Catalog table and column metadata is embedded.

## Main commands

| Command | What it does |
|---|---|
| `make validate-contract` | Checks the frozen CIPHOS data contract. |
| `make validate` | Checks the local graph projection. |
| `make validate-all` | Runs the contract check, lint, tests, and projection check together. |
| `make lakehouse-plan` | Prints the Databricks load plan without writing anything. |
| `make lakehouse-tables` | Loads CSV data into Databricks and builds Bronze and Silver tables. |
| `make graph` | Loads CIPHOS data into the configured Neo4j graph. |
| `make graph-clear` | Clears existing CIPHOS data, then rebuilds the graph. |
| `make graph-counts` | Shows node and relationship counts in the graph. |
| `make graph-verify` | Compares the graph with the source CSV data. |
| `make semantic-ingest` | Builds the NeoCarta structural map, then indexes it for semantic search. |
| `make semantic-context` | Prints the saved structural map as JSON. |
| `make semantic-validate` | Compares the saved structural map with a fresh extraction. |
| `make semantic-mcp` | Starts the read-only structural-map service at `http://127.0.0.1:8000/mcp`. |
| `make semantic-search-mcp` | Starts the semantic search service at `http://127.0.0.1:8010/mcp`. |
| `make semantic-query` | Runs the semantic-search showcase and a grounded SQL query. |
| `make demo` | Starts the Streamlit traceability demo. |
| `make semantic-local-test` | Runs the full semantic-map acceptance flow against disposable local Neo4j containers. |
| `make semantic-local-down` | Removes those local containers and their volumes. |
| `make lint` | Runs ruff over the code and tests. |
| `make test` | Runs the local unit tests. |
| `make help` | Lists every command. |

## Terms

| Term | Definition |
|---|---|
| Bronze table | Raw CSV data plus load details. |
| Silver table | Cleaned and typed data used for queries. |
| Gold table | Final rows used for reports, paths, exposure, and lineage. |
| Snapshot | A fixed version of the source data. |
| Projection | The source data copied into Neo4j. The demo reads this graph directly. |
| Semantic store | A separate Neo4j database that holds graph structure only, not values. |
