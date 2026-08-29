"""Repository Management — add, list, refresh, reset, and delete repositories."""
from __future__ import annotations

import streamlit as st

from components.notifications import loading, show_result
from services.api_client import get_client

st.title("📦 Repository Management")

client = get_client()

st.subheader("Add Repository")
with st.form("add_repository_form", clear_on_submit=True):
    github_url = st.text_input("GitHub URL", placeholder="https://github.com/owner/repo")
    name = st.text_input("Display name (optional)")
    submitted = st.form_submit_button("Clone Repository", type="primary")

if submitted:
    if not github_url:
        st.warning("A GitHub URL is required.")
    else:
        with loading("Cloning repository..."):
            create_result = client.create_repository(github_url, name or None)
        success_message = None
        if create_result.success and create_result.data:
            success_message = f"Repository '{create_result.data.get('name')}' imported."
        show_result(create_result, success_message=success_message)
        if create_result.success:
            st.rerun()

st.divider()
st.subheader("Repositories")

with loading("Loading repositories..."):
    repos_result = client.list_repositories()

if not repos_result.success:
    st.error(f"Could not load repositories: {repos_result.message}")
    st.stop()

repositories = (repos_result.data or {}).get("repositories", [])
if not repositories:
    st.info("No repositories yet — add one above.")

for repo in repositories:
    with st.container(border=True):
        info_col, action_col = st.columns([3, 2])

        with info_col:
            st.markdown(f"**{repo['name']}**")
            st.caption(repo["github_url"] or "(local)")
            st.caption(f"Status: `{repo['status']}` · id `{repo['id']}`")
            st.caption(
                f"Indexing: `{repo.get('indexing_status', 'not_started')}` "
                f"({repo.get('indexing_progress', 0)}%)"
            )
            if repo.get("error_message"):
                st.caption(f"⚠️ {repo['error_message']}")

        with action_col:
            button_cols = st.columns(4)

            if button_cols[0].button("Refresh", key=f"refresh_{repo['id']}"):
                with loading("Refreshing workspace..."):
                    refresh_result = client.refresh_workspace(repo["id"])
                show_result(refresh_result)

            if button_cols[1].button("Reset", key=f"reset_{repo['id']}"):
                with loading("Resetting workspace..."):
                    reset_result = client.reset_workspace(repo["id"])
                show_result(reset_result)

            if button_cols[2].button("Index", key=f"index_{repo['id']}"):
                with loading("Starting indexing..."):
                    index_result = client.trigger_index(repo["id"])
                show_result(index_result, success_message="Indexing started in the background.")

            if button_cols[3].button("Delete", key=f"delete_btn_{repo['id']}"):
                st.session_state[f"confirm_delete_{repo['id']}"] = True

        if st.session_state.get(f"confirm_delete_{repo['id']}"):
            st.warning(f"Delete '{repo['name']}' and its local clone? This cannot be undone.")
            confirm_col, cancel_col = st.columns(2)
            if confirm_col.button("Confirm Delete", key=f"confirm_{repo['id']}", type="primary"):
                with loading("Deleting repository..."):
                    delete_result = client.delete_repository(repo["id"])
                show_result(delete_result)
                st.session_state[f"confirm_delete_{repo['id']}"] = False
                if delete_result.success:
                    st.rerun()
            if cancel_col.button("Cancel", key=f"cancel_{repo['id']}"):
                st.session_state[f"confirm_delete_{repo['id']}"] = False
                st.rerun()
