"""Unit tests for the Turnstile and GitHub OAuth clients using mocked HTTP (ADR-027). No network or DB."""
from __future__ import annotations

import httpx
import pytest

from app.auth.exceptions import OAuthError, ServiceUnavailableError, TurnstileVerificationError
from app.auth.github import GitHubOAuthClient
from app.auth.turnstile import TurnstileVerifier
from app.core.config import AuthSettings, Settings


def settings_with(environment: str = "development", **auth_overrides) -> Settings:
    settings = Settings()
    settings.app.environment = environment
    settings.auth = AuthSettings(**auth_overrides)
    return settings


def oauth_settings(**overrides) -> AuthSettings:
    values = dict(
        github_client_id="client-123", github_client_secret="secret-456",
        github_redirect_uri="https://app.example/auth/callback",
    )
    values.update(overrides)
    return AuthSettings(**values)


# --- Turnstile ---------------------------------------------------------------------

async def test_turnstile_is_skipped_outside_production_when_unconfigured() -> None:
    await TurnstileVerifier(settings_with("development")).verify(None, None)


async def test_turnstile_fails_closed_in_production_when_unconfigured() -> None:
    with pytest.raises(ServiceUnavailableError):
        await TurnstileVerifier(settings_with("production")).verify("token", None)


async def test_turnstile_requires_a_token_when_configured() -> None:
    verifier = TurnstileVerifier(settings_with(turnstile_secret_key="s3cret"))
    with pytest.raises(TurnstileVerificationError):
        await verifier.verify(None, "198.51.100.1")


async def test_turnstile_accepts_a_valid_token_and_sends_the_expected_fields() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(dict(pair.split("=") for pair in request.content.decode().split("&")))
        return httpx.Response(200, json={"success": True})

    verifier = TurnstileVerifier(settings_with(turnstile_secret_key="s3cret"), transport=httpx.MockTransport(handler))
    await verifier.verify("good-token", "198.51.100.1")
    assert seen["secret"] == "s3cret"
    assert seen["response"] == "good-token"
    assert seen["remoteip"] == "198.51.100.1"


async def test_turnstile_rejects_a_failed_challenge() -> None:
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json={"success": False, "error-codes": ["invalid-input-response"]}))
    verifier = TurnstileVerifier(settings_with(turnstile_secret_key="s3cret"), transport=transport)
    with pytest.raises(TurnstileVerificationError):
        await verifier.verify("bad", None)


async def test_turnstile_fails_closed_when_cloudflare_is_unreachable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    verifier = TurnstileVerifier(settings_with(turnstile_secret_key="s3cret"), transport=httpx.MockTransport(handler))
    with pytest.raises(ServiceUnavailableError):
        await verifier.verify("token", None)


# --- GitHub OAuth ----------------------------------------------------------------------

def test_authorize_url_requests_identity_only_scope_and_carries_state() -> None:
    url = GitHubOAuthClient(oauth_settings()).build_authorize_url("state-abc")
    assert url.startswith("https://github.com/login/oauth/authorize?")
    assert "client_id=client-123" in url
    assert "state=state-abc" in url
    assert "scope=read%3Auser" in url  # no repo scopes: public repositories only
    assert "repo" not in url.split("scope=")[1].split("&")[0].replace("read%3Auser", "")


def test_authorize_url_requires_configuration() -> None:
    with pytest.raises(ServiceUnavailableError):
        GitHubOAuthClient(AuthSettings()).build_authorize_url("s")


def github_transport(profile: dict | None = None, token: str | None = "gho_token") -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/login/oauth/access_token":
            return httpx.Response(200, json={"access_token": token} if token else {"error": "bad_verification_code"})
        if request.url.path == "/user":
            assert request.headers["authorization"] == "Bearer gho_token"
            return httpx.Response(200, json=profile or {})
        return httpx.Response(404)

    return httpx.MockTransport(handler)


async def test_code_exchange_returns_the_profile() -> None:
    profile = {"id": 4242, "login": "octocat", "name": "The Octocat", "avatar_url": "https://a/b.png"}
    client = GitHubOAuthClient(oauth_settings(), transport=github_transport(profile))
    result = await client.fetch_profile_for_code("the-code")
    assert (result.id, result.login, result.name) == (4242, "octocat", "The Octocat")


async def test_a_rejected_code_is_an_oauth_error() -> None:
    client = GitHubOAuthClient(oauth_settings(), transport=github_transport(token=None))
    with pytest.raises(OAuthError):
        await client.fetch_profile_for_code("stale-code")


async def test_a_malformed_profile_is_an_oauth_error() -> None:
    client = GitHubOAuthClient(oauth_settings(), transport=github_transport({"id": "not-an-int", "login": "x"}))
    with pytest.raises(OAuthError):
        await client.fetch_profile_for_code("code")


async def test_github_being_down_is_a_service_error_not_a_crash() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("github unreachable")

    client = GitHubOAuthClient(oauth_settings(), transport=httpx.MockTransport(handler))
    with pytest.raises(ServiceUnavailableError):
        await client.fetch_profile_for_code("code")
