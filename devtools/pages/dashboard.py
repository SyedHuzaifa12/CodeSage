"""Dashboard — backend/dependency health and repository summary counts."""
from __future__ import annotations

import streamlit as st

from components.health_badge import render_status_metric
from components.notifications import loading
from services.api_client import get_client

st.title("🧠 CodeSage DevTools")
st.caption("Internal engineering dashboard — not the product frontend.")

client = get_client()

st.subheader("System Health")

with loading("Checking backend health..."):
    health_result = client.get_health()

if health_result.data is None:
    st.error(f"Backend unreachable: {health_result.message}")
else:
    data = health_result.data
    dependencies = data.get("dependencies", {})

    cols = st.columns(4)
    with cols[0]:
        render_status_metric("Backend", health_result.status_code == 200)
    with cols[1]:
        render_status_metric("PostgreSQL", bool(dependencies.get("postgresql")))
    with cols[2]:
        render_status_metric("Redis", bool(dependencies.get("redis")))
    with cols[3]:
        render_status_metric("Qdrant", bool(dependencies.get("qdrant")))

    st.caption(
        f"Version {data.get('version', '?')} · {data.get('environment', '?')} "
        f"· uptime {data.get('uptime_seconds', '?')}s"
    )

st.divider()
st.subheader("Repositories")

with loading("Loading repositories..."):
    repos_result = client.list_repositories()

if not repos_result.success:
    st.error(f"Could not load repositories: {repos_result.message}")
else:
    repositories = (repos_result.data or {}).get("repositories", [])
    total = len(repositories)

    scanned = 0
    with loading("Checking workspace status..."):
        for repo in repositories:
            workspace_result = client.get_workspace(repo["id"])
            if workspace_result.success and (workspace_result.data or {}).get("status") == "ready":
                scanned += 1

    col1, col2 = st.columns(2)
    col1.metric("Total Repositories", total)
    col2.metric("Scanned Repositories", scanned)

if st.button("🔄 Refresh Dashboard"):
    st.rerun()
