# CIPHOS lakehouse loader, Neo4j graph projection, and hybrid demo.
UV ?= uv
IMPORTER := ciphos-graph
LAKEHOUSE_BUILDER := ciphos-lakehouse
## The bundled CSV fixture is a raw export.  Keep this opt-in at the Make
## boundary so the importer records raw-export lineage when no Silver snapshot
## is configured.  A configured CIPHOS_SILVER_SNAPSHOT_DIR still wins and is
## recorded as Silver.  Set GRAPH_SOURCE_FLAGS= to require Silver input.
GRAPH_SOURCE_FLAGS ?= --allow-raw-source
SEMANTIC_CONTEXT := ciphos-semantic-context
SEMANTIC_INGEST := ciphos-semantic-ingest
SEMANTIC_MCP := ciphos-semantic-mcp
SEMANTIC_VALIDATE := ciphos-semantic-validate
MCP_PORT ?= 8000

.DEFAULT_GOAL := help
.PHONY: help validate-contract validate validate-all graph graph-activate graph-clear \
        graph-counts graph-verify lakehouse-tables lakehouse-plan demo lint test \
        semantic-contract semantic-context semantic-ingest semantic-mcp semantic-validate \
        semantic-index semantic-query semantic-search-mcp \
        semantic-local-down semantic-local-test semantic-local-up

help:
	@echo "CIPHOS lakehouse and graph projection"
	@echo ""
	@echo "  make validate-contract  Check the frozen CIPHOS v1 inventory and count baseline."
	@echo "  make validate      Validate the reduced graph projection locally."
	@echo "  make validate-all  Run contract, lint, unit tests, and projection checks."
	@echo "  make graph         Build and validate a candidate projection in an isolated Neo4j database."
	@echo "  make graph-activate  Build, validate, and activate a candidate projection."
	@echo "  make graph-clear   Clear and reload a candidate CIPHOS projection only."
	@echo "  make graph-counts  Show imported node and relationship counts."
	@echo "  make graph-verify  Compare graph counts, labels, and types with the CSV export."
	@echo "  make lakehouse-plan  Inspect all Bronze and Silver work without external writes."
	@echo "  make lakehouse-tables  Upload all CSVs and build Bronze/Silver Unity Catalog tables."
	@echo "  make demo          Start the hybrid traceability Streamlit demo."
	@echo "  make semantic-contract  Check local records against pinned NeoCarta LPG models."
	@echo "  make semantic-ingest  Replace and verify the source-scoped CIPHOS LPG map."
	@echo "  make semantic-context  Print the persisted structural context as JSON."
	@echo "  make semantic-validate  Compare persisted context with a fresh extraction."
	@echo "  make semantic-mcp  Serve the read-only LPG context on loopback HTTP."
	@echo "  make semantic-index  Index curated Silver table/column metadata and embeddings."
	@echo "  make semantic-search-mcp  Serve NeoCarta search plus CIPHOS graph context."
	@echo "  make semantic-query  Run the CIPHOS semantic-search showcase and grounded SQL query."
	@echo "  make semantic-local-up  Start, seed, and accept disposable local Neo4j containers."
	@echo "  make semantic-local-test  Alias for the complete local Neo4j acceptance flow."
	@echo "  make semantic-local-down  Remove disposable local semantic-test containers and volumes."
	@echo "  make lint          Run ruff over the package and tests."
	@echo "  make test          Run local unit tests."
	@echo "  make help          Show this message."
	@echo ""
	@echo "First run: review .env.sample, then run make validate-contract and make lakehouse-plan."
	@echo "lakehouse-tables requires DATABRICKS_WAREHOUSE_ID; graph builds require immutable snapshot IDs."
	@echo "Graph candidates must use an isolated Neo4j database. graph-clear deletes only :CiphosEntity nodes there."

validate-contract:
	@echo "==> Validating frozen CIPHOS v1 contract"
	$(UV) run ciphos-contract

validate:
	@echo "==> Validating the CIPHOS current-state projection"
	$(UV) run $(IMPORTER) --validate-only --data-dir ciphos_data/csv

validate-all: validate-contract lint test validate

graph:
	@echo "==> Building a candidate CIPHOS projection in the configured isolated database"
	$(UV) run $(IMPORTER) --candidate $(GRAPH_SOURCE_FLAGS)

graph-activate:
	@echo "==> Building, validating, and activating a candidate CIPHOS projection"
	$(UV) run $(IMPORTER) --candidate --activate $(GRAPH_SOURCE_FLAGS)

graph-clear:
	@echo "==> Clearing and reloading CIPHOS-owned candidate graph data"
	$(UV) run $(IMPORTER) --candidate --clear $(GRAPH_SOURCE_FLAGS)

graph-counts:
	@echo "==> Reading CIPHOS graph counts"
	$(UV) run $(IMPORTER) --counts

graph-verify:
	@echo "==> Verifying CIPHOS graph against CSV export"
	$(UV) run $(IMPORTER) --verify

lakehouse-tables:
	@echo "==> Building CIPHOS Bronze and Silver Unity Catalog tables"
	$(UV) run $(LAKEHOUSE_BUILDER)

lakehouse-plan:
	@echo "==> Planning CIPHOS Bronze and Silver Unity Catalog tables"
	$(UV) run $(LAKEHOUSE_BUILDER) --dry-run

demo:
	@echo "==> Starting the CIPHOS hybrid traceability demo"
	$(UV) run ciphos-demo

semantic-contract:
	@echo "==> Checking the pinned NeoCarta 0.8.0 LPG contract"
	$(UV) run --isolated --no-project --with "neocarta==0.8.0" python -m unittest \
		tests/test_neocarta_lpg_contract.py

semantic-ingest:
	@echo "==> Replacing the source-scoped CIPHOS LPG metadata map"
	$(UV) run $(SEMANTIC_INGEST)

semantic-context:
	@echo "==> Reading persisted CIPHOS LPG structural context"
	$(UV) run $(SEMANTIC_CONTEXT)

semantic-validate:
	@echo "==> Comparing persisted CIPHOS LPG metadata with a fresh extraction"
	$(UV) run $(SEMANTIC_VALIDATE)

semantic-mcp:
	@echo "==> Serving CIPHOS LPG context at http://127.0.0.1:$(MCP_PORT)/mcp"
	$(UV) run $(SEMANTIC_MCP) --transport streamable-http --port $(MCP_PORT)

semantic-index:
	@echo "==> Indexing CIPHOS Silver metadata and embeddings"
	$(UV) run ciphos-semantic-index

semantic-search-mcp:
	@echo "==> Serving CIPHOS semantic search at http://127.0.0.1:$(MCP_PORT)/mcp"
	$(UV) run ciphos-semantic-search-mcp --port $(MCP_PORT)

semantic-query:
	@echo "==> Running the CIPHOS semantic query showcase"
	$(UV) run ciphos-semantic-query

semantic-local-up:
	$(UV) run ciphos-local up

semantic-local-test:
	$(UV) run ciphos-local up

semantic-local-down:
	$(UV) run ciphos-local down

lint:
	@echo "==> Linting src and tests"
	$(UV) run ruff check src tests

test:
	@echo "==> Running CIPHOS contract tests"
	$(UV) run python -m unittest discover -s tests
