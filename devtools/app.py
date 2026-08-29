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
repository_statistics = st.Page("pages/repository_statistics.py", title="Repository Statistics", icon="📈")
call_graph = st.Page("pages/call_graph.py", title="Call Graph", icon="📞")
dependency_graph = st.Page("pages/dependency_graph.py", title="Dependency Graph", icon="🕸️")
symbol_explorer = st.Page("pages/symbol_explorer.py", title="Symbol Explorer", icon="🔍")
logs = st.Page("pages/logs.py", title="Logs", icon="📜")

navigation = st.navigation(
    [
        dashboard,
        repository_management,
        repository_explorer,
        workspace_statistics,
        repository_statistics,
        call_graph,
        dependency_graph,
        symbol_explorer,
        logs,
    ]
)
navigation.run()
