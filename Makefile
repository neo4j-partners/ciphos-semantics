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
DEMO_PORT ?= 8502
## A separate default port for the backgrounded `make mcp` target, since 8000
## may already be in use by another project's own MCP server.
MCP_DEV_PORT ?= 8010
MCP_PID_FILE := .mcp-search.pid
MCP_LOG_FILE := .mcp-search.log

.DEFAULT_GOAL := help
.PHONY: help validate-contract validate validate-all graph graph-clear \
        graph-counts graph-verify lakehouse-tables lakehouse-plan demo lint test \
        semantic-contract semantic-context semantic-ingest semantic-mcp semantic-validate \
        semantic-query semantic-search-mcp mcp mcp-stop \
        semantic-local-down semantic-local-test semantic-local-up

help:
	@echo "CIPHOS lakehouse and graph projection"
	@echo ""
	@echo "  make validate-contract  Check the frozen CIPHOS v1 inventory and count baseline."
	@echo "  make validate      Validate the reduced graph projection locally."
	@echo "  make validate-all  Run contract, lint, unit tests, and projection checks."
	@echo "  make graph         Build and validate the CIPHOS graph projection."
	@echo "  make graph-clear   Clear existing CIPHOS data, then rebuild the projection."
	@echo "  make graph-counts  Show imported node and relationship counts."
	@echo "  make graph-verify  Compare graph counts, labels, and types with the CSV export."
	@echo "  make lakehouse-plan  Inspect all Bronze and Silver work without external writes."
	@echo "  make lakehouse-tables  Upload all CSVs and build Bronze/Silver Unity Catalog tables."
	@echo "  make demo          Start the Streamlit explorer on DEMO_PORT (default 8502)."
	@echo "  make semantic-contract  Check local records against pinned NeoCarta LPG models."
	@echo "  make semantic-ingest  Replace the source-scoped CIPHOS LPG map, then index curated Silver metadata and embeddings."
	@echo "  make semantic-context  Print the persisted structural context as JSON."
	@echo "  make semantic-validate  Compare persisted context with a fresh extraction."
	@echo "  make semantic-mcp  Serve the read-only LPG context on loopback HTTP."
	@echo "  make semantic-search-mcp  Serve NeoCarta search plus CIPHOS graph context."
	@echo "  make mcp           Start the semantic search MCP in the background on MCP_DEV_PORT (default 8010)."
	@echo "  make mcp-stop      Stop the MCP server started by make mcp."
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
	@echo "graph-clear deletes only :CiphosEntity nodes before rebuilding."

validate-contract:
	@echo "==> Validating frozen CIPHOS v1 contract"
	$(UV) run ciphos-contract

validate:
	@echo "==> Validating the CIPHOS current-state projection"
	$(UV) run $(IMPORTER) --validate-only --data-dir ciphos_data/csv

validate-all: validate-contract lint test validate

graph:
	@echo "==> Building the CIPHOS graph projection"
	$(UV) run $(IMPORTER) $(GRAPH_SOURCE_FLAGS)

graph-clear:
	@echo "==> Clearing and rebuilding the CIPHOS graph projection"
	$(UV) run $(IMPORTER) --clear $(GRAPH_SOURCE_FLAGS)

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
	@echo "==> Starting the CIPHOS lakehouse, graph, and traceability explorer at http://localhost:$(DEMO_PORT)"
	$(UV) run ciphos-demo --server.port $(DEMO_PORT)

semantic-contract:
	@echo "==> Checking the pinned NeoCarta 0.8.0 LPG contract"
	$(UV) run --isolated --no-project --with "neocarta==0.8.0" python -m unittest \
		tests/test_neocarta_lpg_contract.py

semantic-ingest:
	@echo "==> Replacing the source-scoped CIPHOS LPG metadata map"
	$(UV) run $(SEMANTIC_INGEST)
	@echo "==> Indexing CIPHOS Silver metadata and embeddings"
	$(UV) run ciphos-semantic-index

semantic-context:
	@echo "==> Reading persisted CIPHOS LPG structural context"
	$(UV) run $(SEMANTIC_CONTEXT)

semantic-validate:
	@echo "==> Comparing persisted CIPHOS LPG metadata with a fresh extraction"
	$(UV) run $(SEMANTIC_VALIDATE)

semantic-mcp:
	@echo "==> Serving CIPHOS LPG context at http://127.0.0.1:$(MCP_PORT)/mcp"
	$(UV) run $(SEMANTIC_MCP) --transport streamable-http --port $(MCP_PORT)

semantic-search-mcp:
	@echo "==> Serving CIPHOS semantic search at http://127.0.0.1:$(MCP_PORT)/mcp"
	$(UV) run ciphos-semantic-search-mcp --port $(MCP_PORT)

mcp:
	@if [ -f $(MCP_PID_FILE) ] && kill -0 $$(cat $(MCP_PID_FILE)) 2>/dev/null; then \
		echo "CIPHOS semantic search MCP is already running (pid $$(cat $(MCP_PID_FILE))) at http://127.0.0.1:$(MCP_DEV_PORT)/mcp"; \
	else \
		echo "==> Starting CIPHOS semantic search MCP at http://127.0.0.1:$(MCP_DEV_PORT)/mcp"; \
		$(UV) run ciphos-semantic-search-mcp --port $(MCP_DEV_PORT) > $(MCP_LOG_FILE) 2>&1 & echo $$! > $(MCP_PID_FILE); \
		echo "Logs: $(MCP_LOG_FILE)"; \
	fi

mcp-stop:
	@if [ -f $(MCP_PID_FILE) ]; then \
		PID=$$(cat $(MCP_PID_FILE)); \
		if kill -0 $$PID 2>/dev/null; then \
			kill $$PID && echo "Stopped CIPHOS semantic search MCP (pid $$PID)"; \
		else \
			echo "No running process for pid $$PID"; \
		fi; \
		rm -f $(MCP_PID_FILE); \
	else \
		echo "No MCP pid file found ($(MCP_PID_FILE)); nothing to stop"; \
	fi

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
