"""Shared auth for the evaluation scripts (ADR-027).

Every API route now needs a bearer token. These scripts evaluate one
already-indexed repository over HTTP, so they need an identity that is
allowed to read it:

* ``CODESAGE_ACCESS_TOKEN`` — a bearer token for a user who owns the
  repository (use this for your own repositories); or
* nothing — a throwaway **guest** session is created, which can read the
  public *demo* repository but not anyone else's (the API answers 404).
  Note a guest has a daily question cap, so a long ``ai_eval`` run against
  the demo may hit it; raise ``GUEST_DAILY_QUESTIONS`` in the backend
  ``.env`` for local runs.
"""
from __future__ import annotations

import os
import sys

import httpx


def authorized_client(base_url: str, timeout: float) -> httpx.Client:
    """Build an ``httpx.Client`` that already carries a valid bearer token.

    Args:
        base_url: The backend base URL.
        timeout: Per-request timeout in seconds.

    Returns:
        A client with an ``Authorization`` header set.
    """
    token = os.environ.get("CODESAGE_ACCESS_TOKEN", "").strip()
    if not token:
        response = httpx.post(f"{base_url.rstrip('/')}/api/v1/auth/guest", json={}, timeout=timeout)
        if response.status_code != 200:
            sys.exit(
                f"Could not start a guest session ({response.status_code}): {response.text[:300]}\n"
                "Set CODESAGE_ACCESS_TOKEN to a valid bearer token instead."
            )
        token = response.json()["data"]["tokens"]["access_token"]
    return httpx.Client(base_url=base_url, timeout=timeout, headers={"Authorization": f"Bearer {token}"})
