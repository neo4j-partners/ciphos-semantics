# Proposal: NeoCarta semantic map for CIPHOS

## Goal

Create a repeatable, source-derived NeoCarta LPG map for the active CIPHOS Neo4j
projection. The map must be safe to rebuild, easy to validate, and useful to a
read-only retrieval client without copying operational values.

## Required local references

Future agents must inspect these local directories before designing or changing
the implementation. Treat them as reference implementations, not as files to
copy wholesale.

- Finance Genie prototype root:
  `/Users/ryanknight/projects/databricks/graph-on-databricks/finance-genie/semantic-investigation-copilot`
- NeoCarta source root:
  `/Users/ryanknight/projects/neo4j-labs/neocarta`
- CIPHOS implementation root:
  `/Users/ryanknight/projects/databricks/ciphos-semantics`

Start with these Finance Genie files:

- `src/neo4j_schema_map.py` for schema procedure allowlisting, canonical IDs,
  scoped replacement, context retrieval, and the custom MCP tool.
- `src/validate_neo4j_schema.py` for fresh-extraction comparison.
- `src/config.py` for source/store separation and target safety checks.
- `src/mcp_server.py` for adding the LPG context tool to NeoCarta's MCP server.
- `tests/test_neo4j_schema_map.py` and `tests/test_config.py` for the relevant
  unit-test patterns.
- `README.md`, `.env.example`, `Makefile`, and `pyproject.toml` for operating and
  packaging conventions.

Start with these NeoCarta files:

- `neocarta/data_model/schema/lpg/models.py` for the LPG record contract.
- `neocarta/data_model/schema/lpg/README.md` for the LPG model and its current
  limitations.
- `neocarta/ingest/lpg/constraints.py` for LPG identity constraints.
- `neocarta/ingest/metadata.py` for the NeoCarta graph-version metadata node.
- `neocarta/_mcp/` to confirm what the standard server does and does not cover.

The NeoCarta LPG data model is explicitly marked as an in-progress feature and
does not yet provide a complete connector or standard MCP application. Three
specifics shape the plan:

- Importing `neocarta.data_model.schema.lpg` raises a `UserWarning` saying the
  components are in progress. The ingest path handles that warning deliberately
  rather than letting it surface as noise on every run.
- `neocarta/ingest/lpg/` contains constraints and nothing else. There is no LPG
  writer, so persistence is CIPHOS code.
- NeoCarta's MCP server is relational. Its always-on catalog tools do not use
  embeddings, but their query shapes still cover tables and columns only. The
  server also constructs an embedding provider at startup for its search tools.
  None of the standard tools touch LPG records.

CIPHOS therefore ships its own read-only MCP server and does not extend
NeoCarta's. Extending it would pull an embedding provider requirement into a
release that excludes embeddings, and it would run NeoCarta's table-oriented
tools against a graph holding none.

The Finance Genie prototype fills the remaining gap with custom extraction,
persistence, validation, and retrieval. CIPHOS should adopt that proven flow,
with one addition: the prototype does not import NeoCarta at all, so validating
records against the LPG models is net-new work rather than a copied pattern.

NeoCarta stays out of the project dependencies. Installing `neocarta==0.8.0`
resolves 55 additional packages, including the AWS and Google Cloud SDKs and
LiteLLM, and it caps `pandas` below 3 while CIPHOS runs 3.0.6. Forcing
`pandas>=3` makes the resolver fall back to `neocarta==0.1.0`, which predates
the LPG module. None of that weight buys anything here, because CIPHOS needs
five Pydantic models and one constraints module.

Validation against the pinned models therefore runs as a contract test in an
ephemeral environment:

```
uv run --isolated --no-project --with "neocarta==0.8.0" python -m unittest \
  tests/test_neocarta_lpg_contract.py
```

The version in that command is the pin. It belongs in the `Makefile` so a
NeoCarta upgrade is one edit, and the test is the thing that catches upstream
drift in an in-progress data model. The local NeoCarta checkout stays a design
reference, not a runtime path dependency.

## Summary terms

- **NeoCarta LPG map**: A separate metadata graph that describes the structure
  of one labeled property graph source.
- **Operational source**: The active CIPHOS Neo4j serving projection selected by
  `OPS_NEO4J_URI` and `OPS_NEO4J_DATABASE`. A candidate database must not be
  mapped as the active source by accident.
- **Semantic store**: A dedicated Neo4j database selected by the bare `NEO4J_*`
  settings and containing NeoCarta metadata only.
- **Source scope**: A stable, credential-free identifier for one source URI and
  database pair. It separates the CIPHOS map from all other maps.
- **Schema metadata**: Labels, label sets, relationship types, property names,
  reported property types, nullability evidence, and available relationship
  endpoints. It contains no node or relationship values.
- **Ontology and SHACL shapes**: The existing CIPHOS vocabulary and validation
  rules in `ciphos_data/semantics`. They remain separate from the LPG map.

## Assumptions

- `OPS_NEO4J_DATABASE` identifies the serving CIPHOS projection built from an
  approved Silver snapshot. The schema-map extractor does not inspect
  operational projection records to prove activation.
- The semantic store is disposable demo infrastructure. Rebuilding it is always
  acceptable, so no release needs to restore a previous map.
- The first release maps one configured CIPHOS serving database at a time.
- The first release is structural metadata retrieval. It does not promise
  semantic search, embeddings, inferred descriptions, or generated Cypher.
- Existing CIPHOS tests use `unittest`; new tests should follow that convention
  unless the project deliberately adopts `pytest` as a separate decision.

## Configuration contract

The bare `NEO4J_*` names select the semantic store. The operational serving
graph uses an `OPS_NEO4J_*` namespace:

| Namespace | Selects | Read by |
| --- | --- | --- |
| `OPS_NEO4J_URI`, `OPS_NEO4J_USERNAME`, `OPS_NEO4J_PASSWORD`, `OPS_NEO4J_DATABASE` | The operational CIPHOS serving graph | CIPHOS code only |
| `NEO4J_URI`, `NEO4J_USERNAME`, `NEO4J_PASSWORD`, `NEO4J_DATABASE` | The NeoCarta semantic store | CIPHOS code and NeoCarta itself |

This assignment is deliberate and is the reason the operational names moved.
NeoCarta's library and its MCP server read `NEO4J_URI`, `NEO4J_USERNAME`,
`NEO4J_PASSWORD`, and `NEO4J_DATABASE` from the environment directly. Binding
the bare names to the metadata store means no NeoCarta code path can reach
operational credentials, and no environment-remapping shim is needed to keep
the invariants in the next section. Do not introduce a competing
`NEOCARTA_NEO4J_*` namespace.

A renamed variable fails quietly, so the migration needs its own guard. When an
`OPS_NEO4J_*` variable is unset while its bare counterpart is set, every entry
point must refuse to start and name the rename. A pre-rename `.env` would
otherwise be read as a semantic-store configuration, which is the one confusion
this layout exists to prevent.

The implementation must compare normalized source and target URI-plus-database
identities before any write. It must also reject a target containing
`CiphosEntity` or `CiphosProjection` nodes.

When `CIPHOS_CANDIDATE_DATABASE` is configured on the operational Neo4j URI,
the target must differ from that database too. This explicit identity check
protects an empty candidate database that does not yet contain operational
labels.

Secrets must never appear in the source scope, persisted map, logs, validation
output, or MCP response.

### Comparing identities, not names

The identity check compares the URI-and-database pair. It must not reject a
target merely because the database name matches.

This is not a detail. The current deployment puts the store on its own Aura
instance, and on Aura every instance has exactly one database, always named
`neo4j`. The operational graph and the store are therefore both `neo4j`, on
different instances, with different credentials. That is the correct and normal
arrangement. A guard that compared database names alone would refuse it, so a
name-only check is a bug rather than extra caution.

What makes two identities distinct is the normalized URI plus the database. A
test must cover the same database name on different URIs, and prove it is
accepted.

### Verified before start

The operator confirmed both items on 2026-09-17, so neither blocks Phase 0:

- [x] The operational graph and the semantic store are separate Aura instances,
  with separate credentials and distinct URI-and-database pairs.
- [x] The source identity can call the schema procedures the extractor needs.

Endpoint availability stays a per-run fact rather than a verified precondition.
`db.schema.visualization` is statistics-based, so the map records whether
extraction returned endpoints instead of assuming it will.

## Scope

The first release includes:

- A metadata-only extractor for the active CIPHOS Neo4j projection.
- NeoCarta LPG `Database`, `Schema`, `Node`, `Relationship`, and `Property`
  records validated against the referenced NeoCarta models.
- Containment, owned-property, and available relationship-endpoint links.
- Source-scoped, single-transaction replacement in a dedicated semantic store.
- A focused read-only retrieval tool returning the persisted CIPHOS map.
- Unit tests plus an opt-in external-service validation path.
- Rebuild instructions for the disposable semantic store.

The first release excludes:

- Operational node, relationship, and property values.
- Property-value facts that remain in Delta, including `TagPropertyValue` data.
- Inferred business definitions, embeddings, semantic search, cross-source
  mappings, and generated Cypher.
- Changes to the CIPHOS ontology, SHACL shapes, projection manifest, source
  graph, or active-projection lifecycle.
- Multi-source reconciliation and incremental semantic-store updates.
- A general-purpose Neo4j connector contributed back to NeoCarta.

## Adopted mapping model

| NeoCarta record | CIPHOS meaning | Required links |
| --- | --- | --- |
| `Database` | The configured active CIPHOS Neo4j database | `HAS_SCHEMA` to `Schema` |
| `Schema` | The default Neo4j schema namespace | `HAS_NODE` and `HAS_RELATIONSHIP` |
| `Node` | One source label set, such as `Tag`, or `CiphosEntity` plus `Tag` | `HAS_PROPERTY` to each node property |
| `Relationship` | One source relationship type, such as `HAS_VULNERABILITY` | `HAS_PROPERTY`, plus `HAS_SOURCE_NODE` and `HAS_TARGET_NODE` when available |
| `Property` | One source-reported property owned by one node label set or relationship type | Belongs to exactly one owner |

Each record receives a deterministic, source-scoped ID. The source scope is a
hash of a normalized, credential-free source URI and database name. The
canonicalization rules, delimiter, hash algorithm, and truncation length are
part of the frozen Phase 0 contract so the IDs do not drift between releases.

Multi-label nodes must retain the complete sorted label set. NeoCarta splits a
label set into one primary `label` and a list of `additional_labels`, so the
split rule is part of the frozen contract.

`Node.label` is the first label of the sorted set after `CiphosEntity` is
removed. `CiphosEntity` goes into `additional_labels`. The obvious rule of
taking the first label of the full sorted set does not work here. Every
projected CIPHOS node carries `CiphosEntity`, which sorts ahead of 26 of the 27
contract labels, so 26 label sets would report `CiphosEntity` as their primary
label and only `AssetZone` would keep a domain name. Demoting the marker label
keeps `Node.label` meaningful for every label set.

The rule needs two guards. A label set consisting only of `CiphosEntity` keeps
it as the primary label rather than producing an empty one. Because record IDs
are derived from the label set rather than from the primary label, changing this
rule must not change any ID.

Tests must cover single-label, multi-label, `CiphosEntity`-only, and unlabeled
procedure results.

Property types are preserved exactly as reported by Neo4j. Nullability is not a
passthrough. Neo4j reports `mandatory`, NeoCarta stores `nullable`, and the
contract is `nullable = not mandatory`. Phase 0 freezes that inversion so the
two names are never confused.

`unique`, `indexed`, and `existence` cannot be left unknown by omission. The
NeoCarta `Property` model declares all three as non-optional booleans defaulting
to `False`, so omitting them makes validation materialize `False`. A test against
the published `neocarta==0.8.0` confirms it: a `Property` built without the three
flags dumps `unique: False, indexed: False, existence: False`. That is the false
claim this rule exists to prevent, and it is what the Finance Genie prototype
does today by hardcoding all three.

**Decision, frozen.** The extractor reads the real state from the source with
`SHOW CONSTRAINTS` and `SHOW INDEXES` and populates all three honestly. The
alternative of writing the flags with provenance beside them was rejected: it
leaves every reader needing a second field to know whether a `False` means
anything, and it stores a value the map does not actually know. Two extra
allowlisted queries is the cheaper price, and they turn three placeholder
booleans into real information.

The allowlist therefore holds seven queries, not five. `SHOW CONSTRAINTS` and
`SHOW INDEXES` are metadata commands. They return constraint and index
descriptors, never node or relationship values, so they stay inside the
metadata-only boundary.

Two consequences carry into the implementation. The flags are derived per owner
and property name, so a constraint on a label set that no longer reports
properties must not invent a `Property` record. If either command is rejected by
permissions, ingest fails rather than falling back to `False`, because a silent
fallback is the exact defect this decision removes.

`db.schema.visualization` endpoints are optional and statistics-based. The map
records whether endpoint extraction succeeded and does not invent missing
source or target links. Tests must cover multiple possible source and target
label sets for one relationship type.

`source_scope` is a CIPHOS field, not a NeoCarta one. No LPG model declares it,
and Pydantic drops unknown fields silently rather than failing, so a record that
round-trips through a NeoCarta model loses its scope. Validation therefore runs
on the NeoCarta-declared fields only, and the writer attaches `source_scope` to
the persisted node. A test must prove that a validated record still carries its
scope at write time.

## Security and correctness invariants

- The extraction layer executes an exact allowlist of seven metadata queries
  through read routing. Five are schema procedures and two are the `SHOW`
  commands for constraints and indexes. Arbitrary query strings and operational
  `MATCH` reads are not accepted by its public interface.
- Source and target drivers, connection models, and environment variables remain
  distinct throughout the call graph. The retrieval process reads `NEO4J_*` only
  and never resolves an `OPS_NEO4J_*` name.
- Every semantic-store write runs only after URI/database identity checks and
  the operational-label target check pass.
- Replacement deletes only nodes carrying the exact current `source_scope`, then
  recreates that scope in one transaction.
- LPG ID constraints and the NeoCarta graph-version metadata node are installed
  or updated using the selected NeoCarta revision's supported helpers.
- Retrieval uses only the semantic-store driver with read routing. It never
  receives source credentials or a source driver.
- Validation compares canonical records, edges, endpoint availability, and
  source identity. Its mismatch output redacts connection secrets.
- A failed extraction or transformation writes nothing, and a failed write
  transaction leaves no partial scope. The store is disposable, so recovery is a
  rebuild rather than a restore of the previous map.

## Risks and controls

- **Wrong target database**: Distinct environment namespaces, identity
  comparison, and target label checks all run before writes.
- **Candidate used as a semantic target**: The target identity is compared with
  both the serving database and the configured candidate database before any
  label-based check.
- **Data exposure**: The extractor has an exact query allowlist and the MCP
  process has no operational source driver.
- **Incomplete or ambiguous endpoints**: Endpoint availability and provenance
  are explicit; missing links remain missing.
- **False constraint claims**: The three flags are read from `SHOW CONSTRAINTS`
  and `SHOW INDEXES`. A rejected command fails the ingest instead of writing
  `False`.
- **Schema drift**: Validation compares a fresh metadata-only extraction with the
  stored map and reports missing, unexpected, and changed records.
- **Stale `.env` after the namespace rename**: Every entry point refuses to start
  when an `OPS_NEO4J_*` variable is unset while its bare counterpart is set.
- **Meaningless primary labels**: `CiphosEntity` is demoted to
  `additional_labels`, and a test asserts that each contract label set reports
  its domain label as primary.
- **Unstable upstream LPG API**: The NeoCarta revision is pinned, its in-progress
  status is documented, and compatibility is covered by contract tests.
- **Confused semantic layers**: NeoCarta LPG metadata, OWL/RDFS ontology, SHACL
  validation, and the operational projection keep separate files, stores, and
  ownership.

## Planned repository changes

The expected implementation surfaces are:

- `src/ciphos_semantics/semantic_map_contract.py` for the frozen record, edge,
  source-scope, and context types shared by all workstreams.
- `src/ciphos_semantics/semantic_config.py` for source/store configuration and
  safety checks.
- `src/ciphos_semantics/neo4j_schema_extract.py` for allowlisted extraction and
  canonical transformation.
- `src/ciphos_semantics/semantic_store.py` for constraints, scoped replacement,
  and context reads.
- `src/ciphos_semantics/validate_semantic_map.py` for drift comparison.
- `src/ciphos_semantics/semantic_mcp.py` for the read-only MCP entry point.
- Dedicated `tests/test_semantic_config.py`,
  `tests/test_neo4j_schema_extract.py`, `tests/test_semantic_store.py`,
  `tests/test_validate_semantic_map.py`, and `tests/test_semantic_mcp.py` files.
- `tests/test_neocarta_lpg_contract.py` for the isolated check against the
  pinned NeoCarta LPG models.
- `pyproject.toml`, `uv.lock`, `.env.sample`, `Makefile`, and `README.md` for
  dependency, command, configuration, and operating documentation. `fastmcp` is
  the one new runtime dependency, and it resolves cleanly against `pandas` 3.

If implementation reveals a cleaner layout, update this section before moving
files so parallel work continues to have unambiguous ownership.

## Phased delivery plan

### Phase 0: Freeze contracts and compatibility

**Status:** Complete

**Outcome:** All parallel work shares one stable interface and dependency
baseline.

- [x] Inspect the exact local reference files listed above.
- [x] Record the selected NeoCarta version and pin it in the contract-test
  command rather than in the project dependencies.
- [x] Freeze the `OPS_NEO4J_*` and `NEO4J_*` meanings, and migrate every existing
  operational call site and document in one change.
- [x] Freeze canonical row, edge, source-scope, ID, and JSON context shapes.
- [x] Freeze the label-set split rule, including the `CiphosEntity`-only case.
- [x] Freeze `nullable = not mandatory`.
- [x] Constraint and index state is extracted from the source. Decided, see the
  frozen decision in the mapping model.
- [x] Define the exact seven-query allowlist and its error behavior, including
  the refusal to fall back to `False` when `SHOW CONSTRAINTS` or `SHOW INDEXES`
  is rejected.
- [x] Define the target-safety checks and redaction rules.
- [x] Decide how the LPG `UserWarning` is handled on import.
- [x] Create shared fixtures for single-label, multi-label,
  `CiphosEntity`-only, relationship property, unavailable-endpoint, and
  ambiguous-endpoint cases.

**Validation:** A short contract review confirms that extractor, persistence,
validator, and MCP work can proceed without changing shared interfaces.

### Phase 1: Build the metadata-only extractor

**Status:** Complete

**Outcome:** CIPHOS schema procedure results become validated, deterministic LPG
records in memory without operational data reads.

- [x] Implement required schema-procedure reads with read routing.
- [x] Make endpoint extraction optional and preserve its availability state.
- [x] Normalize label sets, relationship types, property unions, and nullability.
- [x] Split each label set into a primary label and additional labels by the
  frozen rule.
- [x] Populate `unique`, `indexed`, and `existence` from `SHOW CONSTRAINTS` and
  `SHOW INDEXES`, and fail rather than defaulting to `False`.
- [x] Construct deterministic source scopes and record IDs.
- [x] Validate records against the pinned NeoCarta LPG models.
- [x] Reject malformed or incomplete procedure results with actionable errors.

**Validation:** Unit tests cover canonicalization, ordering, stable IDs, allowed
queries, malformed rows, and optional endpoints. A driver spy proves that only
the exact allowlisted procedure calls occur.

### Phase 2: Add isolated persistence and configuration

**Status:** Complete

**Outcome:** One complete CIPHOS map can be safely replaced in a dedicated
semantic store in a single transaction.

- [x] Implement the `NEO4J_*` store and `OPS_NEO4J_*` source configuration
  contract, including the pre-rename refusal.
- [x] Reject targets matching either the serving or configured candidate
  identity, and reject targets containing CIPHOS operational labels.
- [x] Attach `source_scope` at write time, since no NeoCarta model declares it.
- [x] Install the LPG ID constraints and NeoCarta graph-version metadata.
- [x] Replace only the current source scope in one transaction.
- [x] Read the persisted scope back into the frozen context shape.
- [x] Add an ingest entry point that reports counts without secrets.

**Validation:** Unit tests prove target rejection, scoped deletion, transaction
ordering, idempotent re-ingest, and context round trips. One test proves that a
failed write leaves no partial scope behind.

### Phase 3: Expose safe retrieval

**Status:** Complete

**Outcome:** A client can retrieve CIPHOS graph structure without access to the
operational graph.

- [x] Add a focused MCP tool named for CIPHOS LPG schema context, on a CIPHOS
  server rather than by extending NeoCarta's relational one.
- [x] Return canonical records, links, source scope, reported types, and endpoint
  availability.
- [x] State that results contain no operational values or inferred definitions.
- [x] Construct the MCP process with the semantic-store read connection only,
  resolving `NEO4J_*` and no `OPS_NEO4J_*` name.
- [x] Add a structured-context command for local inspection and diagnostics.

**Validation:** Tool tests verify the response contract and prove that source
credentials, source drivers, and write paths are absent from retrieval. One test
asserts that the retrieval path resolves no `OPS_NEO4J_*` variable.

### Phase 4: Add drift validation and operations

**Status:** Complete

**Outcome:** Operators can detect drift and rebuild safely.

- [x] Compare a fresh extraction with the persisted canonical records and edges.
- [x] Report missing, unexpected, and changed items without secrets.
- [x] Add ingest, context, validation, and MCP targets to the project commands.
- [x] Add configuration, rebuild, and failure guidance to the README, including
  the `OPS_NEO4J_*` and `NEO4J_*` split and why it exists.
- [x] Document the order: validate the active CIPHOS projection, extract into
  memory, replace its semantic scope, validate the stored map, then enable
  retrieval.
- [x] Document that semantic-store cleanup must never touch a CIPHOS candidate or
  serving database.

**Validation:** The local suite passes and the documentation names every required
variable, safety condition, expected output, and recovery action.

### Phase 5: Run external-service acceptance

**Status:** Blocked by the configured operational source

**Outcome:** The pinned implementation is proven against real isolated Neo4j
source and semantic-store databases.

- [x] Confirm that `OPS_NEO4J_*` and `NEO4J_*` resolve to different
  URI-and-database pairs before anything is written.
- [x] Verify source procedure permissions. Confirmed on 2026-09-17.
- [x] Record whether `db.schema.visualization` returned endpoints.
- [ ] Ingest the active CIPHOS schema into an empty dedicated semantic store.
- [ ] Run drift validation and retrieve the map through MCP.
- [ ] Re-run ingestion to prove idempotency and source-scope isolation.
- [ ] Exercise a failed write and confirm that no partial scope is left behind.
- [ ] Capture counts, NeoCarta revision, source database identity hash, and
  validation results in an acceptance record without credentials.

**Validation:** All acceptance checks pass against isolated databases, and no
operational values appear in the semantic store or retrieval response.

**Current blocker (2026-09-18):** Read-only preflight proved the configured
source and store identities are distinct and that all seven metadata reads
succeed; endpoint metadata is available. The configured source is not the
isolated active CIPHOS projection required by this phase: its schema also
contains unrelated finance labels, it contains the excluded
`TagPropertyValue` label, and it has no `CiphosProjection` label. No semantic
store write was attempted. Point `OPS_NEO4J_*` at the active CIPHOS serving
projection, then resume the remaining acceptance checks.

**Local acceptance (2026-09-18):** The reusable Docker Compose source/store
environment completed ingestion, fresh drift validation, a second idempotent
ingestion, semantic-store context retrieval, and an in-process FastMCP client
call. A deliberately invalid property write failed with `CypherTypeError`; a
fresh comparison immediately afterward confirmed that the replacement
transaction left no partial scope. It produced 8 nodes, 2 relationships, 6
properties, and 17 links with no operational values. Neo4j 5.26 returned
virtual visualization rows without endpoint labels, so `endpoints_available`
correctly recorded `false`.

## Parallel implementation plan

Phase 0 is serial. Once its contracts and fixtures are frozen, three workstreams
can proceed in parallel with non-overlapping file ownership.

| Workstream | Owns | Depends on | Delivers |
| --- | --- | --- | --- |
| A: Extract and model | `neo4j_schema_extract.py`; `test_neo4j_schema_extract.py` | Phase 0 contracts | In-memory LPG map and extractor tests |
| B: Configure and persist | `semantic_config.py`; `semantic_store.py`; `test_semantic_config.py`; `test_semantic_store.py` | Phase 0 contracts | Safe connection separation, target guards, single-transaction scoped writer |
| C: Retrieve and validate | `semantic_mcp.py`; `validate_semantic_map.py`; their dedicated tests | Phase 0 context fixture | MCP registration and pure comparison logic using fake contexts |

One integrator owns shared files and integration seams:

- `pyproject.toml`, `uv.lock`, `.env`, `.env.sample`, `Makefile`, and `README.md`.
- The NeoCarta pin, which lives in the contract-test command.
- The environment-namespace rename, which spans existing operational modules
  that no workstream owns.
- `semantic_map_contract.py` and any public protocol shared across workstreams.
- Entry-point wiring that composes extraction, persistence, validation, and MCP.
- Cross-workstream tests and external-service acceptance.

Do not parallelize decisions about environment names, source-scope IDs, public
context shapes, dependency versions, or target safety. Do not assign two agents
to the same file. Keep extraction and persistence in separate modules rather
than recreating the Finance Genie prototype's single large schema-map module.

The recommended merge gates are:

1. Phase 0 contract and shared fixtures are complete.
2. A, B, and the pure portions of C pass their isolated unit tests.
3. The integrator connects extraction to persistence and retrieval, then runs
   the full local suite.
4. Documentation and command surfaces are merged after names stabilize.
5. External-service acceptance runs serially against one explicitly identified
   source/store pair to avoid concurrent replacement of the same scope.

## Completion criteria

- A dedicated NeoCarta store contains a source-scoped CIPHOS LPG structural map.
- The map contains validated `Database`, `Schema`, `Node`, `Relationship`, and
  `Property` records with the adopted links.
- Multi-label CIPHOS nodes retain their full label sets, and each one reports a
  domain label rather than `CiphosEntity` as its primary label.
- `unique`, `indexed`, and `existence` reflect real source state, and no run
  writes `False` as a stand-in for unknown.
- The store and source namespaces are separate, and a pre-rename `.env` is
  refused rather than guessed at.
- The extractor executes only approved schema procedures and never copies
  operational values.
- The writer cannot target a CIPHOS operational or candidate database by
  configuration accident.
- Failed extraction and failed persistence leave no partial scope. A rebuild is
  the recovery path.
- The stored map is available through one focused read-only MCP tool.
- Tests prove deterministic mapping, scoped replacement, isolation, retrieval
  safety, and fresh-source accuracy.
- The NeoCarta revision is pinned and its experimental LPG limitation is
  documented.
- Rebuild instructions keep the CIPHOS projection, ontology, SHACL shapes, and
  semantic store clearly separate.
