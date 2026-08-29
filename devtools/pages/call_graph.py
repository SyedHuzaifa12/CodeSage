"""Call Graph — resolved caller -> callee edges, from already-persisted relationships."""
from __future__ import annotations

import streamlit as st

from components.notifications import loading
from components.repository_picker import select_repository
from services.api_client import get_client

st.title("📞 Call Graph")

repo = select_repository(key="call_graph_repo_picker")
if repo is None:
    st.stop()

client = get_client()

with loading("Loading call graph..."):
    result = client.get_call_graph(repo["id"])

if not result.success:
    st.warning(f"No call graph yet: {result.message}")
    st.info("The call graph is generated automatically right after indexing finishes.")
    st.stop()

data = result.data or {}
nodes: list[str] = data.get("nodes", [])
edges: list[dict] = data.get("edges", [])

st.caption(f"{len(nodes)} symbols involved · {len(edges)} resolved call edges")

if not edges:
    st.info("No resolved calls found for this repository.")
    st.stop()

max_edges = st.slider("Max edges to render", min_value=10, max_value=max(10, len(edges)), value=min(150, len(edges)))

dot_lines = ["digraph CallGraph {", "rankdir=LR;", "node [shape=box, fontsize=10];"]
for edge in edges[:max_edges]:
    source = edge["source"].replace('"', "'")
    target = edge["target"].replace('"', "'")
    dot_lines.append(f'"{source}" -> "{target}";')
dot_lines.append("}")

st.graphviz_chart("\n".join(dot_lines), width="stretch")

st.divider()
st.markdown("#### Raw Edges")
st.dataframe(edges, width="stretch", hide_index=True)
