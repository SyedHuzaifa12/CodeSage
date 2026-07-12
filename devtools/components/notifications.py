"""Reusable success/error notification and loading-indicator helpers."""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator, Optional

import streamlit as st

from services.api_client import ApiResult


def show_result(result: ApiResult, success_message: Optional[str] = None) -> None:
    """Render a success or error notification for an API result.

    Args:
        result: The API call's outcome.
        success_message: Optional override for the message shown on success.
    """
    if result.success:
        st.success(success_message or result.message or "Done.")
    else:
        st.error(result.message or "Something went wrong.")


@contextmanager
def loading(message: str = "Loading...") -> Iterator[None]:
    """Show a spinner for the duration of the wrapped block.

    Args:
        message: The spinner's label.
    """
    with st.spinner(message):
        yield
