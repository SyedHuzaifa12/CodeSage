"""Thin HTTP client for CodeSage's FastAPI backend.

Every DevTools page goes through this client — no page calls
``requests`` directly, and no API URL, envelope-parsing, or endpoint
path is duplicated across pages.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

import requests
import streamlit as st

from config import BACKEND_API_URL, REQUEST_TIMEOUT_SECONDS


@dataclass
class ApiResult:
    """Outcome of a single API call, already unwrapped from the standard envelope."""

    success: bool
    message: str
    data: Any = None
    status_code: Optional[int] = None


class ApiClient:
    """Wraps every backend endpoint the DevTools console needs."""

    def __init__(self, base_url: str = BACKEND_API_URL) -> None:
        """Initialize the client.

        Args:
            base_url: The backend's base URL (no trailing slash).
        """
        self._base_url = base_url.rstrip("/")
        self._session = requests.Session()

    def _request(self, method: str, path: str, **kwargs: Any) -> ApiResult:
        """Perform a request and unwrap the standard response envelope.

        Args:
            method: HTTP method (GET/POST/PATCH/DELETE).
            path: Path appended to the base URL.
            **kwargs: Passed through to ``requests``.

        Returns:
            An :class:`ApiResult`. Network failures are reported as a
            failed result rather than raised, so pages never need a
            try/except around every call.
        """
        url = f"{self._base_url}{path}"
        try:
            response = self._session.request(method, url, timeout=REQUEST_TIMEOUT_SECONDS, **kwargs)
        except requests.RequestException as exc:
            return ApiResult(success=False, message=f"Could not reach backend at {url}: {exc}")

        try:
            payload = response.json()
        except ValueError:
            payload = {"success": response.ok, "message": response.text or "Empty response"}

        return ApiResult(
            success=payload.get("success", response.ok),
            message=payload.get("message", ""),
            data=payload.get("data"),
            status_code=response.status_code,
        )

    # ---- Health ----

    def get_health(self) -> ApiResult:
        """Fetch full backend/dependency health status."""
        return self._request("GET", "/health")

    # ---- Repositories ----

    def list_repositories(self) -> ApiResult:
        """List every registered repository."""
        return self._request("GET", "/api/v1/repositories")

    def get_repository(self, repository_id: str) -> ApiResult:
        """Fetch a single repository by id."""
        return self._request("GET", f"/api/v1/repositories/{repository_id}")

    def create_repository(self, github_url: str, name: Optional[str] = None) -> ApiResult:
        """Register and clone a new repository."""
        payload: dict[str, str] = {"github_url": github_url}
        if name:
            payload["name"] = name
        return self._request("POST", "/api/v1/repositories", json=payload)

    def update_repository(self, repository_id: str, name: str) -> ApiResult:
        """Rename a repository."""
        return self._request("PATCH", f"/api/v1/repositories/{repository_id}", json={"name": name})

    def delete_repository(self, repository_id: str) -> ApiResult:
        """Delete a repository's local clone and metadata."""
        return self._request("DELETE", f"/api/v1/repositories/{repository_id}")

    # ---- Workspace / Ingestion ----

    def get_workspace(self, repository_id: str) -> ApiResult:
        """Fetch a repository's workspace scan status and statistics."""
        return self._request("GET", f"/api/v1/repositories/{repository_id}/workspace")

    def get_tree(self, repository_id: str) -> ApiResult:
        """Fetch a repository's nested file/folder tree."""
        return self._request("GET", f"/api/v1/repositories/{repository_id}/tree")

    def refresh_workspace(self, repository_id: str) -> ApiResult:
        """Re-scan a repository's workspace without re-cloning."""
        return self._request("POST", f"/api/v1/repositories/{repository_id}/refresh")

    def reset_workspace(self, repository_id: str) -> ApiResult:
        """Clear a repository's workspace processing state."""
        return self._request("POST", f"/api/v1/repositories/{repository_id}/reset")

    def trigger_index(self, repository_id: str) -> ApiResult:
        """Trigger the (placeholder) indexing endpoint."""
        return self._request("POST", f"/api/v1/repositories/{repository_id}/index")

    # ---- Repository Intelligence ----

    def get_intelligence(self, repository_id: str) -> ApiResult:
        """Fetch a repository's statistics, dependency analysis, and summary."""
        return self._request("GET", f"/api/v1/repositories/{repository_id}/intelligence")

    def get_call_graph(self, repository_id: str) -> ApiResult:
        """Fetch a repository's resolved call graph."""
        return self._request("GET", f"/api/v1/repositories/{repository_id}/call-graph")

    def get_dependency_graph(self, repository_id: str) -> ApiResult:
        """Fetch a repository's resolved import/dependency graph."""
        return self._request("GET", f"/api/v1/repositories/{repository_id}/dependency-graph")

    def get_symbols(self, repository_id: str) -> ApiResult:
        """Fetch every parsed symbol for a repository."""
        return self._request("GET", f"/api/v1/repositories/{repository_id}/symbols")

    # ---- Logs ----

    def get_logs(self, limit: int = 200) -> ApiResult:
        """Fetch the most recent backend log lines."""
        return self._request("GET", "/api/v1/logs", params={"limit": limit})


@st.cache_resource
def get_client() -> ApiClient:
    """Return a cached, shared :class:`ApiClient` for the Streamlit session.

    Returns:
        A single reused client (and underlying HTTP connection pool)
        across reruns, rather than reconnecting on every interaction.
    """
    return ApiClient()
