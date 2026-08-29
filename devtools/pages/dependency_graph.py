"""Dependency Graph — resolved internal import edges, circular deps, and orphan files."""
from __future__ import annotations

import streamlit as st

from components.notifications import loading
from components.repository_picker import select_repository
from services.api_client import get_client

st.title("🕸️ Dependency Graph")

repo = select_repository(key="dependency_graph_repo_picker")
if repo is None:
    st.stop()

client = get_client()

with loading("Loading dependency graph..."):
    result = client.get_dependency_graph(repo["id"])

if not result.success:
    st.warning(f"No dependency graph yet: {result.message}")
    st.info("The dependency graph is generated automatically right after indexing finishes.")
    st.stop()

data = result.data or {}
nodes: list[str] = data.get("nodes", [])
edges: list[dict] = data.get("edges", [])
cycles: list[list[str]] = data.get("circular_dependencies") or []
orphans: list[str] = data.get("orphan_files") or []

st.caption(f"{len(nodes)} modules · {len(edges)} resolved internal import edges")

cycle_modules = {module for cycle in cycles for module in cycle}

if not edges:
    st.info("No resolved internal imports found for this repository.")
else:
    max_edges = st.slider(
        "Max edges to render", min_value=10, max_value=max(10, len(edges)), value=min(150, len(edges))
    )

    dot_lines = ["digraph DependencyGraph {", "rankdir=LR;", "node [shape=box, fontsize=10];"]
    for edge in edges[:max_edges]:
        source, target = edge["source"], edge["target"]
        color = ' [color=red, penwidth=2]' if source in cycle_modules and target in cycle_modules else ""
        dot_lines.append(f'"{source}" -> "{target}"{color};')
    dot_lines.append("}")

    st.graphviz_chart("\n".join(dot_lines), width="stretch")

st.divider()
col_left, col_right = st.columns(2)

with col_left:
    st.markdown("#### Circular Dependencies")
    if not cycles:
        st.success("No circular dependencies detected.")
    else:
        for cycle in cycles:
            st.warning(" → ".join(cycle))

with col_right:
    st.markdown("#### Orphan Files")
    if not orphans:
        st.success("No orphan files detected.")
    else:
        st.dataframe({"Orphan File": orphans}, width="stretch", hide_index=True)

st.divider()
st.markdown("#### Raw Edges")
st.dataframe(edges, width="stretch", hide_index=True)
