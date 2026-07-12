"""Reusable repository selector, shared across Explorer/Statistics pages."""
from __future__ import annotations

from typing import Optional

import streamlit as st

from services.api_client import get_client


def select_repository(key: str) -> Optional[dict]:
    """Render a repository dropdown and return the selected repository.

    Args:
        key: A unique Streamlit widget key (each page using this picker
            must pass its own key).

    Returns:
        The selected repository as a dict, or ``None`` if none exist.
    """
    client = get_client()
    result = client.list_repositories()
    if not result.success:
        st.error(f"Could not load repositories: {result.message}")
        return None

    repositories = (result.data or {}).get("repositories", [])
    if not repositories:
        st.info("No repositories yet. Add one from Repository Management.")
        return None

    options = {f"{repo['name']} ({repo['status']})": repo for repo in repositories}
    selected_label = st.selectbox("Repository", options=list(options.keys()), key=key)
    return options.get(selected_label)
