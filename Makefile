# CIPHOS lakehouse loader, Neo4j graph projection, and hybrid demo.
UV ?= uv
IMPORTER := ciphos-graph
LAKEHOUSE_BUILDER := ciphos-lakehouse

.DEFAULT_GOAL := help
.PHONY: help validate-contract validate validate-all graph graph-activate graph-clear \
        graph-counts graph-verify lakehouse-tables lakehouse-plan demo lint test

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
	$(UV) run $(IMPORTER) --candidate

graph-activate:
	@echo "==> Building, validating, and activating a candidate CIPHOS projection"
	$(UV) run $(IMPORTER) --candidate --activate

graph-clear:
	@echo "==> Clearing and reloading CIPHOS-owned candidate graph data"
	$(UV) run $(IMPORTER) --candidate --clear

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

lint:
	@echo "==> Linting src and tests"
	$(UV) run ruff check src tests

test:
	@echo "==> Running CIPHOS contract tests"
	$(UV) run python -m unittest discover -s tests
