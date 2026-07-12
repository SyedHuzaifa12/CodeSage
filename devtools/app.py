"""CodeSage DevTools — internal engineering console.

Not the product frontend. Consumes the FastAPI backend exclusively
through ``services/api_client.py`` — never touches PostgreSQL, Redis,
or Qdrant directly.
"""
from __future__ import annotations

import streamlit as st

st.set_page_config(page_title="CodeSage DevTools", page_icon="🧠", layout="wide")

dashboard = st.Page("pages/dashboard.py", title="Dashboard", icon="🏠", default=True)
repository_management = st.Page("pages/repository_management.py", title="Repository Management", icon="📦")
repository_explorer = st.Page("pages/repository_explorer.py", title="Repository Explorer", icon="🗂️")
workspace_statistics = st.Page("pages/workspace_statistics.py", title="Workspace Statistics", icon="📊")
logs = st.Page("pages/logs.py", title="Logs", icon="📜")

navigation = st.navigation(
    [dashboard, repository_management, repository_explorer, workspace_statistics, logs]
)
navigation.run()
