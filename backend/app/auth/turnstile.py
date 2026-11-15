"""Cloudflare Turnstile verification — bot protection for guest creation (ADR-027)."""
from __future__ import annotations

import logging
from typing import Optional

import httpx

from app.auth.exceptions import ServiceUnavailableError, TurnstileVerificationError
from app.core.config import Settings

logger = logging.getLogger("codesage.auth.turnstile")

_SITEVERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"


class TurnstileVerifier:
    """Verifies a Turnstile response token server-side.

    With no secret configured it accepts everything **in development only**
    (so local development needs no Cloudflare account); in staging or
    production a missing secret is both a startup error and a hard failure here.
    """

    def __init__(self, settings: Settings, transport: Optional[httpx.AsyncBaseTransport] = None) -> None:
        self._settings = settings
        self._transport = transport  # injectable for tests

    async def verify(self, token: Optional[str], remote_ip: Optional[str]) -> None:
        """Validate a challenge token.

        Args:
            token: The token the browser widget produced.
            remote_ip: The caller's IP, forwarded to Cloudflare as an extra signal.

        Raises:
            TurnstileVerificationError: The token is missing or Cloudflare rejected it.
            ServiceUnavailableError: Verification could not run (unconfigured in
                production, or Cloudflare unreachable) — fails closed.
        """
        secret = self._settings.auth.turnstile_secret_key
        if secret is None:
            if self._settings.app.environment != "development":
                raise ServiceUnavailableError("Bot protection is not configured.")
            return
        if not token:
            raise TurnstileVerificationError("Please complete the bot-protection challenge.")

        data = {"secret": secret.get_secret_value(), "response": token}
        if remote_ip:
            data["remoteip"] = remote_ip
        try:
            async with httpx.AsyncClient(timeout=5.0, transport=self._transport) as client:
                response = await client.post(_SITEVERIFY_URL, data=data)
            response.raise_for_status()
            outcome = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.exception("Turnstile verification could not be completed")
            raise ServiceUnavailableError("Bot protection is temporarily unavailable; please retry.") from exc

        if not outcome.get("success"):
            logger.info("Turnstile rejected a token: %s", outcome.get("error-codes"))
            raise TurnstileVerificationError("Bot-protection challenge failed. Please retry.")
