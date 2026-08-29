"""Symbol Explorer — every parsed symbol for a repository, filterable by file/type/name."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from components.notifications import loading
from components.repository_picker import select_repository
from services.api_client import get_client

st.title("🔍 Symbol Explorer")

repo = select_repository(key="symbol_explorer_repo_picker")
if repo is None:
    st.stop()

client = get_client()

with loading("Loading symbols..."):
    result = client.get_symbols(repo["id"])

if not result.success:
    st.warning(f"Could not load symbols: {result.message}")
    st.stop()

symbols: list[dict] = (result.data or {}).get("symbols", [])
if not symbols:
    st.info("No symbols parsed for this repository yet.")
    st.stop()

df = pd.DataFrame(symbols)

col_type, col_file, col_search = st.columns(3)
with col_type:
    symbol_types = sorted(df["symbol_type"].unique())
    selected_types = st.multiselect("Symbol type", options=symbol_types, default=symbol_types)
with col_file:
    files = sorted(df["file_path"].unique())
    selected_files = st.multiselect("File", options=files, default=[])
with col_search:
    search = st.text_input("Search name / qualified name")

filtered = df[df["symbol_type"].isin(selected_types)]
if selected_files:
    filtered = filtered[filtered["file_path"].isin(selected_files)]
if search:
    needle = search.lower()
    filtered = filtered[
        filtered["name"].str.lower().str.contains(needle) | filtered["qualified_name"].str.lower().str.contains(needle)
    ]

st.caption(f"Showing {len(filtered)} of {len(df)} symbols")
st.dataframe(
    filtered[["symbol_type", "name", "qualified_name", "visibility", "file_path", "start_line", "end_line", "signature"]],
    width="stretch",
    hide_index=True,
)
