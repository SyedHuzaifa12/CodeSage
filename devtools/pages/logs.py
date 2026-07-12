"""Logs — recent backend log lines, with optional auto-refresh."""
from __future__ import annotations

import time

import pandas as pd
import streamlit as st

from config import LOGS_AUTO_REFRESH_SECONDS
from services.api_client import get_client

st.title("📜 Backend Logs")

client = get_client()

control_col, slider_col = st.columns([1, 3])
auto_refresh = control_col.toggle("Auto-refresh", value=False)
limit = slider_col.slider("Lines to show", min_value=25, max_value=500, value=100, step=25)

placeholder = st.empty()


def render_logs() -> None:
    """Fetch and render the most recent log lines into the placeholder."""
    result = client.get_logs(limit=limit)
    with placeholder.container():
        if not result.success:
            st.error(f"Could not load logs: {result.message}")
            return

        entries = (result.data or {}).get("lines", [])
        if not entries:
            st.info("No log entries yet.")
            return

        rows = []
        for entry in entries:
            if "raw" in entry:
                rows.append({"timestamp": "", "level": "", "logger": "", "message": entry["raw"]})
            else:
                rows.append(
                    {
                        "timestamp": entry.get("timestamp", ""),
                        "level": entry.get("level", ""),
                        "logger": entry.get("logger", ""),
                        "message": entry.get("message", ""),
                    }
                )
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True, height=500)


render_logs()

if auto_refresh:
    time.sleep(LOGS_AUTO_REFRESH_SECONDS)
    st.rerun()
