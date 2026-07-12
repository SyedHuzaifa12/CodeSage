"""Repository Explorer — nested folder/file tree, no file contents."""
from __future__ import annotations

from typing import Any

import streamlit as st

from components.notifications import loading
from components.repository_picker import select_repository
from services.api_client import get_client

st.title("🗂️ Repository Explorer")

repo = select_repository(key="explorer_repo_picker")
if repo is None:
    st.stop()

client = get_client()

with loading("Loading repository tree..."):
    tree_result = client.get_tree(repo["id"])

if not tree_result.success:
    st.warning(f"Could not load tree: {tree_result.message}")
    st.stop()

root_nodes: list[dict[str, Any]] = (tree_result.data or {}).get("root", [])


def render_node(node: dict[str, Any], depth: int = 0) -> None:
    """Recursively render a tree node as an expandable folder or a file line.

    Args:
        node: A single tree node (file or folder).
        depth: Current nesting depth — only the top level auto-expands.
    """
    if node["type"] == "folder":
        with st.expander(f"📁 {node['name']}", expanded=(depth == 0)):
            for child in node.get("children") or []:
                render_node(child, depth + 1)
    else:
        language = f" · {node['language']}" if node.get("language") else ""
        size = node.get("size_bytes")
        size_label = f" · {size:,} bytes" if size is not None else ""
        st.markdown(f"📄 {node['name']}{language}{size_label}")


if not root_nodes:
    st.info("This repository has no scanned files yet. Try Refresh in Repository Management.")
else:
    for node in root_nodes:
        render_node(node)
