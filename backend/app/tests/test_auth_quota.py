"""Unit tests for quota enforcement, client-IP resolution, and production config checks (ADR-027)."""
from __future__ import annotations

import uuid

import pytest
from redis.exceptions import RedisError
from starlette.requests import Request

from app.auth.exceptions import GuestQuotaExceededError, RateLimitedError, ServiceUnavailableError
from app.auth.quota import QuotaService
from app.auth.utils import client_ip, is_admin
from pydantic import SecretStr

from app.core.config import AuthSettings, Settings
from app.models.user import User


class FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, int] = {}
        self.expiries: dict[str, int] = {}

    async def incr(self, key: str) -> int:
        self.store[key] = self.store.get(key, 0) + 1
        return self.store[key]

    async def expire(self, key: str, seconds: int) -> None:
        self.expiries[key] = seconds

    async def get(self, key: str):
        return str(self.store[key]) if key in self.store else None


class BrokenRedis:
    async def incr(self, key: str) -> int:
        raise RedisError("simulated outage")

    async def expire(self, key: str, seconds: int) -> None:
        raise RedisError("simulated outage")

    async def get(self, key: str):
        raise RedisError("simulated outage")


def guest() -> User:
    return User(id=uuid.uuid4(), kind="guest")


def member(login: str = "someone") -> User:
    return User(id=uuid.uuid4(), kind="user", github_login=login)


def service(client=None, **overrides) -> QuotaService:
    return QuotaService(client or FakeRedis(), AuthSettings(**overrides))


def request_with(headers: dict[str, str], client=("203.0.113.7", 1234)) -> Request:
    scope = {
        "type": "http", "method": "GET", "path": "/",
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
        "client": client,
    }
    return Request(scope)


# --- questions ---------------------------------------------------------------

async def test_guest_question_limit_prompts_sign_in() -> None:
    quota, user = service(guest_daily_questions=2), guest()
    await quota.consume_question(user)
    await quota.consume_question(user)
    with pytest.raises(GuestQuotaExceededError):
        await quota.consume_question(user)


async def test_member_question_limit_is_a_rate_limit_not_a_sign_in_prompt() -> None:
    quota, user = service(user_daily_questions=1), member()
    await quota.consume_question(user)
    with pytest.raises(RateLimitedError):
        await quota.consume_question(user)


async def test_question_counters_are_per_user() -> None:
    quota = service(guest_daily_questions=1)
    await quota.consume_question(guest())
    await quota.consume_question(guest())  # a different guest is unaffected


async def test_question_counting_fails_open_when_redis_is_down() -> None:
    await service(BrokenRedis(), guest_daily_questions=1).consume_question(guest())


async def test_usage_report_reflects_consumption() -> None:
    quota, user = service(guest_daily_questions=5), guest()
    await quota.consume_question(user)
    await quota.consume_question(user)
    assert await quota.questions_used_today(user) == 2
    assert quota.question_limit(user) == 5


# --- repositories --------------------------------------------------------------

async def test_guest_at_repository_cap_is_asked_to_sign_in() -> None:
    with pytest.raises(GuestQuotaExceededError):
        await service(guest_max_repositories=1).check_repository_creation(guest(), active_repositories=1)


async def test_member_at_repository_cap_is_rate_limited() -> None:
    with pytest.raises(RateLimitedError):
        await service(user_max_repositories=2).check_repository_creation(member(), active_repositories=2)


async def test_guest_under_cap_is_allowed() -> None:
    await service(guest_max_repositories=1).check_repository_creation(guest(), active_repositories=0)


async def test_guest_daily_attempts_are_capped() -> None:
    quota, user = service(guest_daily_repository_attempts=2, guest_global_daily_index_cap=100), guest()
    await quota.check_repository_creation(user, 0)
    await quota.check_repository_creation(user, 0)
    with pytest.raises(GuestQuotaExceededError):
        await quota.check_repository_creation(user, 0)


async def test_global_guest_indexing_cap_protects_shared_capacity() -> None:
    quota = service(guest_global_daily_index_cap=2, guest_daily_repository_attempts=10)
    await quota.check_repository_creation(guest(), 0)
    await quota.check_repository_creation(guest(), 0)
    with pytest.raises(RateLimitedError):
        await quota.check_repository_creation(guest(), 0)


async def test_members_do_not_consume_the_guest_global_budget() -> None:
    redis_client = FakeRedis()
    quota = service(redis_client, guest_global_daily_index_cap=1)
    for _ in range(5):
        await quota.check_repository_creation(member(), 0)
    assert not any("guest-index-global" in key for key in redis_client.store)


async def test_a_user_at_their_cap_does_not_burn_the_global_budget() -> None:
    redis_client = FakeRedis()
    quota = service(redis_client, guest_max_repositories=1)
    with pytest.raises(GuestQuotaExceededError):
        await quota.check_repository_creation(guest(), 1)
    assert not redis_client.store


async def test_repository_creation_fails_closed_when_redis_is_down() -> None:
    with pytest.raises(ServiceUnavailableError):
        await service(BrokenRedis()).check_repository_creation(guest(), 0)


# --- guest creation --------------------------------------------------------------

async def test_guest_creation_is_limited_per_ip() -> None:
    quota = service(guest_creations_per_ip_per_day=2)
    await quota.check_guest_creation("198.51.100.1")
    await quota.check_guest_creation("198.51.100.1")
    with pytest.raises(RateLimitedError):
        await quota.check_guest_creation("198.51.100.1")
    await quota.check_guest_creation("198.51.100.2")  # another network is unaffected


async def test_guest_creation_fails_closed_when_redis_is_down() -> None:
    with pytest.raises(ServiceUnavailableError):
        await service(BrokenRedis()).check_guest_creation("198.51.100.1")


async def test_counters_get_an_expiry_so_they_cannot_leak_forever() -> None:
    redis_client = FakeRedis()
    await service(redis_client).check_guest_creation("198.51.100.1")
    assert redis_client.expiries and all(ttl > 0 for ttl in redis_client.expiries.values())


# --- client IP -----------------------------------------------------------------------

def test_forwarded_header_is_ignored_unless_proxies_are_trusted() -> None:
    request = request_with({"x-forwarded-for": "1.1.1.1, 2.2.2.2"})
    assert client_ip(request, AuthSettings(trusted_proxy_hops=0)) == "203.0.113.7"


def test_forwarded_header_uses_entry_appended_by_the_trusted_proxy() -> None:
    # A client can prepend fake entries; only the one our proxy appended counts.
    request = request_with({"x-forwarded-for": "6.6.6.6, 198.51.100.9"})
    assert client_ip(request, AuthSettings(trusted_proxy_hops=1)) == "198.51.100.9"
    assert client_ip(request, AuthSettings(trusted_proxy_hops=2)) == "6.6.6.6"


def test_missing_forwarded_header_falls_back_to_socket_address() -> None:
    assert client_ip(request_with({}), AuthSettings(trusted_proxy_hops=1)) == "203.0.113.7"


def test_too_few_forwarded_entries_falls_back_to_socket_address() -> None:
    request = request_with({"x-forwarded-for": "198.51.100.9"})
    assert client_ip(request, AuthSettings(trusted_proxy_hops=3)) == "203.0.113.7"


# --- admin + production config ----------------------------------------------------------

def test_only_listed_members_are_admins() -> None:
    settings = AuthSettings(admin_github_logins="Alice, bob")
    assert is_admin(member("alice"), settings)
    assert is_admin(member("BOB"), settings)
    assert not is_admin(member("mallory"), settings)


def test_a_guest_is_never_an_admin_even_with_a_listed_login() -> None:
    settings = AuthSettings(admin_github_logins="alice")
    assert not is_admin(User(id=uuid.uuid4(), kind="guest", github_login="alice"), settings)


def test_blank_values_from_a_copied_env_example_mean_unset() -> None:
    blank = AuthSettings(
        turnstile_secret_key="", github_client_id="  ", github_client_secret="", github_redirect_uri="",
        internal_api_token="", jwt_secret="",
    )
    assert blank.turnstile_secret_key is None  # so development skips Turnstile instead of demanding a token
    assert blank.internal_api_token is None
    assert not blank.github_oauth_configured
    assert len(blank.jwt_secret.get_secret_value()) >= 32  # never an empty signing key


def test_staging_is_held_to_the_same_rules_as_production() -> None:
    settings = Settings()
    settings.app.environment = "staging"
    settings.app.debug = False
    settings.auth = AuthSettings()
    assert any("JWT_SECRET" in problem for problem in settings.production_problems())


def test_development_has_no_production_problems() -> None:
    settings = Settings()
    settings.app.environment = "development"
    assert settings.production_problems() == []


def test_production_refuses_weak_or_missing_security_configuration() -> None:
    settings = Settings()
    settings.app.environment = "production"
    settings.app.debug = True
    settings.auth = AuthSettings()  # all defaults: dev secret, nothing configured
    problems = " ".join(settings.production_problems())
    for expected in ("JWT_SECRET", "TURNSTILE_SECRET_KEY", "GITHUB_CLIENT_ID", "INTERNAL_API_TOKEN", "DEBUG"):
        assert expected in problems


def test_production_rejects_a_short_jwt_secret() -> None:
    settings = Settings()
    settings.app.environment = "production"
    settings.app.debug = False
    settings.auth = AuthSettings(
        jwt_secret="too-short", turnstile_secret_key="t", github_client_id="i", github_client_secret="s",
        github_redirect_uri="https://app.example/auth/callback", internal_api_token="tok",
    )
    assert any("JWT_SECRET" in problem for problem in settings.production_problems())


def test_production_accepts_a_fully_configured_setup() -> None:
    settings = Settings()
    settings.app.environment = "production"
    settings.app.debug = False
    # Hosting guards (Phase 6): real hostnames and origins, and a real database credential.
    settings.app.allowed_hosts = "api.example.com"
    settings.app.cors_origins = "https://app.example"
    settings.database.database_url = SecretStr("postgresql://app:s3cret@db.example.com/app")
    settings.auth = AuthSettings(
        jwt_secret="a-long-random-production-secret-0123456789", turnstile_secret_key="t",
        github_client_id="i", github_client_secret="s",
        github_redirect_uri="https://app.example/auth/callback", internal_api_token="tok",
    )
    assert settings.production_problems() == []
