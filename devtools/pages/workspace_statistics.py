"""Workspace Statistics — persisted scan statistics for a repository."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from components.notifications import loading
from components.repository_picker import select_repository
from services.api_client import get_client

st.title("📊 Workspace Statistics")

repo = select_repository(key="stats_repo_picker")
if repo is None:
    st.stop()

client = get_client()

with loading("Loading workspace statistics..."):
    workspace_result = client.get_workspace(repo["id"])

if not workspace_result.success:
    st.warning(f"No workspace statistics yet: {workspace_result.message}")
    st.stop()

workspace = workspace_result.data or {}

st.subheader(f"Statistics for {repo['name']}")
st.caption(f"Status: `{workspace.get('status')}` · Progress: {workspace.get('progress')}%")

cols = st.columns(4)
cols[0].metric("Total Files", workspace.get("total_files", 0))
cols[1].metric("Supported Files", workspace.get("supported_files", 0))
cols[2].metric("Ignored Files", workspace.get("ignored_files", 0))
cols[3].metric("Folder Count", workspace.get("folder_count", 0))

size_mb = workspace.get("repository_size_bytes", 0) / (1024 * 1024)
st.metric("Repository Size", f"{size_mb:.2f} MB")

st.divider()
st.subheader("Language Distribution")

language_distribution: dict[str, int] = workspace.get("language_distribution") or {}
if not language_distribution:
    st.info("No recognized languages found yet.")
else:
    df = pd.DataFrame(
        sorted(language_distribution.items(), key=lambda item: item[1], reverse=True),
        columns=["Language", "Files"],
    )
    st.bar_chart(df.set_index("Language"))
    st.dataframe(df, width="stretch", hide_index=True)

if workspace.get("error_message"):
    st.error(f"Last scan error: {workspace['error_message']}")
