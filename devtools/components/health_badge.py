"""Reusable health-status badge rendering."""
from __future__ import annotations

import streamlit as st


def render_status_metric(label: str, healthy: bool) -> None:
    """Render a single dependency's health as a colored status metric.

    Args:
        label: The dependency's display name.
        healthy: Whether it is currently healthy/reachable.
    """
    icon = "🟢" if healthy else "🔴"
    status_text = "Healthy" if healthy else "Unavailable"
    st.metric(label=label, value=f"{icon} {status_text}")
