"""GitHub OAuth web-flow client — identity only (ADR-027).

Requests the ``read:user`` scope and nothing else: no repository scopes,
so CodeSage can never read a private repository through this login.
GitHub proves *who* the user is; sessions are CodeSage's own JWTs.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlencode

import httpx

from app.auth.exceptions import OAuthError, ServiceUnavailableError
from app.core.config import AuthSettings

logger = logging.getLogger("codesage.auth.github")

_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
_TOKEN_URL = "https://github.com/login/oauth/access_token"
_USER_URL = "https://api.github.com/user"


@dataclass(frozen=True)
class GitHubProfile:
    """The GitHub identity fields CodeSage stores."""

    id: int
    login: str
    name: Optional[str]
    avatar_url: Optional[str]


class GitHubOAuthClient:
    """Builds the authorize URL and completes the code exchange."""

    def __init__(self, settings: AuthSettings, transport: Optional[httpx.AsyncBaseTransport] = None) -> None:
        self._settings = settings
        self._transport = transport  # injectable for tests

    def _require_configured(self) -> None:
        if not self._settings.github_oauth_configured:
            raise ServiceUnavailableError("GitHub login is not configured on this server.")

    def build_authorize_url(self, state: str) -> str:
        """Return the GitHub URL that starts the login flow.

        Args:
            state: The CSRF token that GitHub will echo back to the callback.
        """
        self._require_configured()
        query = urlencode(
            {
                "client_id": self._settings.github_client_id,
                "redirect_uri": self._settings.github_redirect_uri,
                "scope": "read:user",
                "state": state,
                "allow_signup": "true",
            }
        )
        return f"{_AUTHORIZE_URL}?{query}"

    async def fetch_profile_for_code(self, code: str) -> GitHubProfile:
        """Exchange an authorization code for the user's GitHub profile.

        The GitHub access token is used once to read the profile and then
        discarded; it is never stored.

        Args:
            code: The one-time code GitHub redirected back with.

        Returns:
            The user's GitHub identity.

        Raises:
            OAuthError: GitHub rejected the code or returned an unusable profile.
            ServiceUnavailableError: GitHub login is unconfigured or GitHub is unreachable.
        """
        self._require_configured()
        try:
            async with httpx.AsyncClient(timeout=10.0, transport=self._transport) as client:
                token_response = await client.post(
                    _TOKEN_URL,
                    data={
                        "client_id": self._settings.github_client_id,
                        "client_secret": self._settings.github_client_secret.get_secret_value(),  # type: ignore[union-attr]
                        "code": code,
                        "redirect_uri": self._settings.github_redirect_uri,
                    },
                    headers={"Accept": "application/json"},
                )
                token_response.raise_for_status()
                access_token = token_response.json().get("access_token")
                if not access_token:
                    raise OAuthError("GitHub did not accept the login code. Please try signing in again.")

                profile_response = await client.get(
                    _USER_URL,
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Accept": "application/vnd.github+json",
                    },
                )
                profile_response.raise_for_status()
                payload = profile_response.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.exception("GitHub OAuth exchange failed")
            raise ServiceUnavailableError("GitHub is temporarily unavailable; please retry.") from exc

        if not isinstance(payload.get("id"), int) or not payload.get("login"):
            raise OAuthError("GitHub returned an unexpected profile.")
        return GitHubProfile(
            id=payload["id"],
            login=str(payload["login"]),
            name=payload.get("name"),
            avatar_url=payload.get("avatar_url"),
        )
