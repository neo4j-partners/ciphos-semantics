"""High-level overview of how the Ask page turns a question into an answer."""

from __future__ import annotations

from pathlib import Path

import streamlit as st

_DIAGRAM_PATH = Path(__file__).parent / "assets" / "ask_flow.svg"


def render() -> None:
    st.title("How Ask works")
    st.caption(
        "Retrieval is deterministic Python calling NeoCarta over MCP. "
        "Generation is the only step that calls an LLM."
    )

    st.image(str(_DIAGRAM_PATH), use_container_width=True)

    st.subheader("Phase 1: deterministic retrieval")
    st.markdown(
        "Typing a question and clicking Ask does not invoke an agent. The raw "
        "question string passes unmodified into `ciphos_semantics.mcp_retrieval.retrieve`. "
        "That function opens one MCP session against the NeoCarta server per click.\n\n"
        "It picks the strongest tool NeoCarta registered for each entity type, using a "
        "fixed priority list in `SEARCH_TOOL_PRIORITIES`. No LLM chooses the tool or "
        "rewrites the query.\n\n"
        "The selected hybrid search tool embeds the question once, using the "
        "Databricks-served gte-large-en model, for a vector similarity search. It also "
        "lucene-escapes the same string for a full-text search. Neo4j runs both searches "
        "against the semantic map graph, normalizes each score, and keeps the stronger "
        "score per table or column. Matches expand into full metadata: columns, types, "
        "example values, and foreign key references."
    )

    st.subheader("Phase 2: grounded generation")
    st.markdown(
        "The retrieved tables, columns, and graph schema context return as a trace. The "
        "Ask page renders this trace as the Retrieved from the map panel.\n\n"
        "Only after retrieval does the pipeline call an LLM. "
        "`query_generation.generate_queries` sends the question and the retrieved context "
        "to `databricks-claude-sonnet-5`, guided by a fixed system prompt. The prompt "
        "instructs the model to write SQL and Cypher using only names present in the "
        "retrieved context. `grounding.ground` checks the generated queries against that "
        "same context and rejects any name that was not retrieved."
    )

    st.subheader("What hybrid search means here")
    st.markdown(
        "Hybrid search means a Neo4j-native vector index fused with a Neo4j-native "
        "full-text index inside the semantic map graph. It is not Databricks Vector "
        "Search. The Databricks Silver tables are the metadata source that gets ingested "
        "into that graph, not the search backend itself."
    )

    with st.expander("Source files"):
        st.table(
            [
                {
                    "File": "demo/page_ask.py",
                    "Role": "Text input, Ask button, renders the trace",
                },
                {
                    "File": "mcp_retrieval.py",
                    "Role": "Opens the MCP session, picks and calls the search tools",
                },
                {
                    "File": "query_generation.py",
                    "Role": "System prompt and LLM call that writes SQL and Cypher",
                },
                {
                    "File": "grounding.py",
                    "Role": "Rejects any generated name not present in the retrieved context",
                },
            ]
        )
