"""Repository Statistics — Sprint 2B repository intelligence: symbol/relationship counts."""
from __future__ import annotations

import streamlit as st

from components.notifications import loading
from components.repository_picker import select_repository
from services.api_client import get_client

st.title("📈 Repository Statistics")

repo = select_repository(key="intelligence_stats_repo_picker")
if repo is None:
    st.stop()

client = get_client()

with loading("Loading repository intelligence..."):
    result = client.get_intelligence(repo["id"])

if not result.success:
    st.warning(f"No repository intelligence yet: {result.message}")
    st.info("Intelligence is generated automatically right after indexing finishes.")
    st.stop()

data = result.data or {}

st.subheader(f"Statistics for {repo['name']}")
st.caption(f"Analysis status: `{data.get('status')}` · Progress: {data.get('progress')}%")
if data.get("error_message"):
    st.error(f"Last analysis error: {data['error_message']}")

st.markdown("#### Symbols")
cols = st.columns(4)
cols[0].metric("Total Symbols", data.get("total_symbols", 0))
cols[1].metric("Classes", data.get("total_classes", 0))
cols[2].metric("Interfaces", data.get("total_interfaces", 0))
cols[3].metric("Enums", data.get("total_enums", 0))

cols = st.columns(4)
cols[0].metric("Functions", data.get("total_functions", 0))
cols[1].metric("Methods", data.get("total_methods", 0))
cols[2].metric("Variables", data.get("total_variables", 0))
cols[3].metric("Namespaces", data.get("total_namespaces", 0))

st.markdown("#### Relationships")
cols = st.columns(4)
cols[0].metric("Imports", data.get("total_imports", 0))
cols[1].metric("Resolved Calls", data.get("total_calls", 0))
cols[2].metric("Inheritance Edges", data.get("inheritance_count", 0))
cols[3].metric("Dependencies", data.get("dependency_count", 0))

st.divider()
st.markdown("#### Circular Dependencies")
cycles: list[list[str]] = data.get("circular_dependencies") or []
if not cycles:
    st.success("No circular dependencies detected.")
else:
    for cycle in cycles:
        st.warning(" → ".join(cycle))

st.markdown("#### Orphan Files")
orphans: list[str] = data.get("orphan_files") or []
if not orphans:
    st.success("No orphan files detected.")
else:
    st.dataframe({"Orphan File": orphans}, width="stretch", hide_index=True)

st.divider()
st.markdown("#### Repository Summary")
st.write("**Architecture hints**")
hints: list[str] = data.get("architecture_hints") or []
if hints:
    for hint in hints:
        st.markdown(f"- {hint}")
else:
    st.caption("No hints available yet.")

col_left, col_right = st.columns(2)
with col_left:
    st.write("**Entry Points**")
    entry_points: list[str] = data.get("entry_points") or []
    st.dataframe({"Path": entry_points}, width="stretch", hide_index=True) if entry_points else st.caption("None found.")

with col_right:
    st.write("**Largest Modules**")
    largest_modules: list[dict] = data.get("largest_modules") or []
    st.dataframe(largest_modules, width="stretch", hide_index=True) if largest_modules else st.caption("None found.")

st.write("**Dependency Hotspots** (most depended-upon internal modules)")
hotspots: list[dict] = data.get("dependency_hotspots") or []
st.dataframe(hotspots, width="stretch", hide_index=True) if hotspots else st.caption("None found.")
