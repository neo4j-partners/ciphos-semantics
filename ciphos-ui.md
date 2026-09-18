# CIPHOS lakehouse and graph UI

A three-page Streamlit app that shows the CIPHOS data as it actually sits in
the two systems: the Bronze and Silver Delta tables in the lakehouse, and the
current-state Neo4j projection built from them. It extends the existing
single-page hybrid demo (`ciphos_semantics.demo.app`) into a small
multi-page app, reusing its Delta and Neo4j adapters rather than replacing
them.

This follows the shape of `semantic-investigation-copilot/ui-v2.md` — a data
page per system plus a page that composes both — with the semantic-mapping
layer removed. That project's "THE MAP" half exists because NeoCarta infers
and stores a live metadata graph over sources it does not otherwise control.
CIPHOS has no equivalent inferred layer to visualize: the node and
relationship allowlist, the exclusions, and the projection rules are already
written down once, as data, in [`contracts/ciphos-v1.json`](contracts/ciphos-v1.json),
and loaded by `contract.py` and `graph_projection_manifest.py`. There is
nothing to retrieve there — only something to read and print. This proposal
does that in the sidebar and drops the map canvas, the MCP retrieval step, and
the grounding panel entirely.

The app reads two sources, both read-only:

| Source | What the app reads | Used on |
|---|---|---|
| Databricks SQL warehouse | Bronze and Silver table/view metadata and sample rows | Lakehouse, Traceability |
| Neo4j serving database (`NEO4J_DATABASE`) | The active `CiphosProjection`, a bounded subgraph, and the traceability query | Operational graph, Traceability |

## The claim

> The lakehouse and the graph hold the same CIPHOS assets in two shapes for
> two different questions — Delta for the value and its provenance, Neo4j for
> what an asset is connected to — and one contract keeps both shapes honest
> about what the graph does and does not carry.

## What this drops from `ui-v2.md`

```text
ui-v2.md (NeoCarta)                     This proposal                        Why
--------------------------------------  ------------------------------------ ------------------------------------------
THE MAP half on every data page         Removed                              There is no store to retrieve from. The
                                                                              allowlist is `contract.py`, already static.
MCP stdio retrieval per Ask click       Removed                              No metadata store means no retrieval step.
Grounding panel (declared vs retrieved) Removed                              Nothing is generated, so nothing to ground.
NL question + serving-endpoint SQL/     Traceability page keyed by tag       The repository already answers one bounded
Cypher generation                       number, no generation                question this way; keep it deterministic.
Semantic-map trace selector             Contract/projection caption in the   `contract_version()` and
                                         sidebar                             `active_projection()` already exist in
                                                                             `demo/graph.py` and `contract.py`.
```

Everything else about the shape of `ui-v2.md` carries over: one data page per
system, a shared selector driving what's shown, `neo4j-viz` for the graph
canvas, caps stated in captions, read-only enforced at the connection, and a
deferred list at the end.

## App shell

```text
+--------------------------------------------------------------------------------+
|  CIPHOS lakehouse and graph                                                    |
+--------------------------+-----------------------------------------------------+
| SIDEBAR                  | PAGE                                                |
|                          |                                                     |
| DATA                     |  Page-specific content                             |
|   Lakehouse              |                                                     |
|   Operational graph      |                                                     |
|                          |                                                     |
| BOTH SYSTEMS             |                                                     |
|   Traceability           |                                                     |
|                          |                                                     |
| [Contract v]             |                                                     |
| [Projection v]           |                                                     |
| [Connections v]          |                                                     |
+--------------------------+-----------------------------------------------------+
```

Use `st.navigation` with two sections, same as `ui-v2.md`. Three sidebar
expanders instead of the reference's three connection badges plus two
expanders — CIPHOS only has two live connections, not three:

- `Contract` — `contract.contract_version()`, the projected node and
  relationship counts from `contract.projected_nodes()` /
  `projected_relationships()`, and the excluded set, so a viewer can see the
  allowlist without opening the JSON.
- `Projection` — the output of the existing `graph.active_projection()`:
  graph/source snapshot IDs, source materialization, content digest, node and
  relationship counts. This is the one already rendered in `app.py`'s
  `render_sidebar`; move it here so it shows on every page, not only
  Traceability.
- `Connections` — warehouse ID, catalog, schema, and the Neo4j URI/database
  from `.env`, masked the way secrets already are not printed elsewhere in
  this repo.

Each connection is opened through a `st.cache_resource`-wrapped call —
`get_connection()` and `get_delta()` already exist in `app.py` and move here
unchanged. A page whose source is unreachable reports the error in place and
leaves the other page usable, matching `lakehouse_traceability`'s existing
try/except-to-`ServiceResult` pattern.

## 1. Lakehouse

The Bronze and Silver tables as they exist in Unity Catalog, browsable by
name, with real sample rows.

```text
Lakehouse                        graph-on-databricks.ciphos-semantics · warehouse

[Layer: Bronze v]   [Table: bronze_node_tag v]

THE DATA                                                        10 sample rows
+--------+----------------+----------------------+-----------------+-------------------+
| tag_id | tag_number     | source_row_number     | source_batch_id | ingested_at        |
+--------+----------------+----------------------+-----------------+-------------------+
| ...    | 21-FIC-1042    | 4821                  | ciphos-...      | 2026-09-10 08:14   |
+--------+----------------+----------------------+-----------------+-------------------+
Column comments carry the original CSV header. 27 node tables, 47
relationship tables, plus bronze_ingestion_control and bronze_quarantine.

Layer: Silver
[Table/view: silver_tag_property_value_enriched v]

+--------+-------------+---------------+------------+-------------+--------------------+
| tpv_id | tag_number  | property_name | raw_value  | parse_status| silver_snapshot_id |
+--------+-------------+---------------+------------+-------------+--------------------+
| ...    | 21-FIC-1042 | high_alarm    | 1200.0     | parsed      | ciphos-...         |
+--------+-------------+---------------+------------+-------------+--------------------+
One row per value. silver_data_quality_results pinned to the same snapshot.
```

The layer selector picks `Bronze` or `Silver`. The table selector below it
lists whichever tables exist for that layer:

- **Bronze**: every `bronze_node_*` and `bronze_relationship_*` table from
  `contract.source_nodes()` / `source_relationships()`, plus
  `bronze_ingestion_control` and `bronze_quarantine`.
- **Silver**: `silver_snapshots`, `silver_tag_property_value_snapshots`,
  `silver_tag_property_value_source_snapshots`,
  `silver_data_quality_results`, and the three views —
  `silver_tag_property_value`, `silver_tag_property_value_sources`,
  `silver_tag_property_value_enriched`.

Rows come from `SELECT * FROM <table> LIMIT 10`, reusing the same
`execute_statement`/`Format.JSON_ARRAY` call `DeltaTraceability` already makes,
generalized to an arbitrary allowlisted table name instead of one hardcoded
view. The identifier still goes through `_qualified_identifier`'s
three-part-name check before it reaches SQL — table names are drawn from the
contract's own lists, never typed free text, so there is no injection surface
to add.

For a Silver table with a `silver_snapshot_id` column, show the most recent
snapshot's row count in the caption. That is the one number this page adds
that the reference's Lakehouse page did not need, because CIPHOS Silver is
snapshot-append and the reference's warehouse tables were not.

No ER diagram and no map canvas. The six sample foreign keys `ui-v2.md`
drew as `REFERENCES` edges have a CIPHOS analogue — Bronze relationship
tables reference two Bronze node tables by ID — but that structure is already
fully stated as the `source_nodes` / `source_relationships` lists in the
contract, printed in the sidebar. Drawing it a second time as a graph adds a
canvas with nothing new on it.

## 2. Operational graph

The same assets as the current-state Neo4j projection, browsable by label,
starting from one instance.

```text
Operational graph                              neo4j+s://<host> · <NEO4J_DATABASE>

[Label: Tag v]   [Tag: 21-FIC-1042 v]   [Depth: 2 v]   [Types: CONTAINS_TAG, CLASSIFIED_AS, HAS_OT_REPRESENTATION v]

THE DATA
   (Plant: North Yard) --HAS_FACILITY--> (Facility: Unit 4) --HAS_SYSTEM--> (System: Feedwater)
                                                                                  |
                                                                            CONTAINS_TAG
                                                                                  v
                                                                    (Tag: 21-FIC-1042) --CLASSIFIED_AS--> (EquipmentClass: Flow Transmitter)
                                                                                  |
                                                                      HAS_OT_REPRESENTATION
                                                                                  v
                                                                          (OTAsset: OT-8842) --HAS_VULNERABILITY--> (Vulnerability: CVE-2023-...)

Legend  (Tag)   (EquipmentClass)   (OTAsset)   (Vulnerability)
Selected: Tag 21-FIC-1042
Showing 41 of 118 nodes within depth 2. Capped at 150 nodes.
```

`Label` picks the starting node type from `contract.projected_nodes()` — 26
labels once `TagPropertyValue` is excluded. `Tag`/`OTAsset`/etc. — whichever
identifying property that label uses — picks one instance, sourced the same
way `demo/graph.py`'s `sample_tags()` already does for `Tag`, generalized to
read `db.schema.nodeTypeProperties` once per label so the selector doesn't
need one hardcoded query per label. `Depth` and `Types` bound the subgraph the
way they do in the reference; the type filter defaults to the types actually
touching the selected label, drawn from `contract.projected_relationships()`.

State the node cap and the shown/of-total count in the caption every time,
matching the reference's convention exactly.

Below the canvas, the same sidebar `Projection` expander already described —
no separate map half here, because the projection lineage already answers
"what does the graph currently hold," which is the only question the
reference's map half was answering for the operational-graph page.

Endpoint pairs are not shown as a separate inventory the way `ui-v2.md`'s map
half showed them, because this page renders the real, observed subgraph
directly rather than a schema-visualization statistic. If the rendered graph
is empty for a selected label, say so — most CIPHOS labels other than `Tag`
will have shallow fan-out at depth 2, and an empty canvas with no caption is
the one outcome to avoid, same rule as `ui-v2.md`'s Ask page.

## 3. Traceability

The existing hybrid demo, unchanged in behavior, promoted from the app's only
page to the third page of the navigation. Delta answers what the value is and
where it came from; Neo4j answers what it's connected to.

```text
Traceability

[Tag number: 21-FIC-1042 v]

LAKEHOUSE FACTS AND PROVENANCE                  Source snapshot: ciphos-2026-09-01
+--------+---------------+-----------+------------+-------------+
| tpv_id | property_name | raw_value | parse_status | source_document_numbers |
+--------+---------------+-----------+------------+-------------+
| ...    | high_alarm    | 1200.0    | parsed     | DOC-4471, DOC-4488       |
+--------+---------------+-----------+------------+-------------+

GRAPH CONTEXT                                   Graph snapshot: ciphos-2026-09-01
+-------------+------------------------------+------------------------------+
| tag         | hierarchy                    | OT and vulnerability context |
+-------------+------------------------------+------------------------------+
| 21-FIC-1042 | North Yard / Unit 4 /         | OT-8842 / Zone-3 /           |
|             | Feedwater                    | CVE-2023-...(high)           |
+-------------+------------------------------+------------------------------+

[Snapshot match: same snapshot on both sides]
```

No changes to `hybrid_data.py`, `demo/graph.py`, or the Cypher in
`GRAPH_TRACEABILITY_CYPHER` — `app.py`'s current body becomes this page's
body, with the sidebar's projection/contract/connection panels lifted out to
the shared sidebar described above so they render once instead of once per
page.

There is no NL question box and no query generation here, unlike the
reference's Ask page. This page already asks one bounded, well-formed
question — "give me everything for this tag" — deterministically. Turning
that into free-text NL retrieval-and-generation is a separate, larger
proposal, not a UI change; see Deferred.

## Safety

```text
Surface                    Enforcement
------------------------   ----------------------------------------------
Lakehouse queries          A warehouse reached by a principal with SELECT
                           grants only on CIPHOS_CATALOG.CIPHOS_SCHEMA.
                           Table names come only from the contract's own
                           lists, never from typed input.
Operational graph queries  NEO4J_DATABASE is the one configured serving
                           database; every call is a read query, no write
                           clause is ever constructed by this app.
Row and node display       LIMIT 10 on every sample query; node budget and
                           depth cap on every rendered subgraph, stated in
                           the caption.
```

Read-only is enforced the same way `import_ciphos_graph.py` already
separates `NEO4J_DATABASE` from `CIPHOS_CANDIDATE_DATABASE` — this app only
ever opens `NEO4J_DATABASE` and only ever runs `MATCH`/`RETURN`. It has no
path to `--candidate`, `--activate`, or `--clear`.

## Implementation boundary

```text
Page                 Widgets                          Backing call
------------------   -------------------------------  ---------------------------
Sidebar              3 expanders                       contract.load_contract();
                                                        graph.active_projection()
                                                        (cached probes, reused
                                                        from app.py)
Lakehouse            1 selectbox (layer), 1 selectbox  SELECT * FROM <table>
                     (table), 1 dataframe, 1 caption   LIMIT 10, generalized from
                                                        DeltaTraceability
Operational graph    1 selectbox (label),               db.schema.nodeTypeProperties
                     1 selectbox (instance),            for the instance list;
                     1 selectbox (depth),                bounded MATCH from the
                     1 multiselect (types),              selected instance, capped
                     1 graph component, 1 caption        by depth and node budget
Traceability         1 selectbox (tag), 2 dataframes,   hybrid_data.graph_traceability
                     1 status banner, 2 expanders        + lakehouse_traceability,
                                                          unchanged from app.py
```

Use `neo4j-viz` for the Operational graph canvas, matching the reference and
this repository's own convention.

## Build state

No new Makefile targets. This app reads what `make lakehouse-tables`,
`make graph-activate`, and the existing `make demo` already produce; `make
demo` becomes a three-page app instead of a one-page app, same entry point
(`ciphos-demo`).

## Deferred

```text
Deferred item                  Why it waits
---------------------------    -----------------------------------------------
NL question + LLM-generated    This is the actual feature `ui-v2.md`'s Ask page
SQL/Cypher                     demonstrates, and it needs something to retrieve
                                from (a metadata store) to ground the generated
                                query in. CIPHOS has no such store today; adding
                                one is a separate proposal, not this UI change.
Gold-output browsing            No Gold writer exists yet — gold_contract.py is
                                row-grain and idempotency helpers only. A page
                                for it waits on a publisher to read from.
Free-form Cypher editor         Traceability already runs one fixed, reviewed
                                query. A hand-editable box adds surface area
                                the read-only user does not need to justify.
Cross-source join assertion    The graph does not claim that a Delta tag_number
                                and a Neo4j Tag.tagNumber are reconciled beyond
                                what render_comparison's snapshot-ID check
                                already verifies.
Run history                    Nothing here needs evidence to persist across a
                                browser session.
```
