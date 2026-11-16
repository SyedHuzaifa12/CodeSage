"""Quota and rate-limit enforcement (ADR-027).

Counters are Redis fixed windows (``INCR`` + ``EXPIRE`` on first hit),
the cheapest primitive in commands — relevant because the hosted Redis
has a monthly command budget. Postgres remains the source of truth for
*ownership* limits (repository counts); Redis only holds time-windowed
counters.

Failure policy: abuse-sensitive paths (guest creation, guest repository
creation) **fail closed** if Redis is unavailable; the per-question
counter **fails open**, since blocking every chat because a counter
store hiccupped costs more than it protects.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

import redis.asyncio as redis
from redis.exceptions import RedisError

from app.auth.exceptions import GuestQuotaExceededError, RateLimitedError, ServiceUnavailableError
from app.core.config import AuthSettings
from app.models.user import User

logger = logging.getLogger("codesage.auth.quota")

_KEY_PREFIX = "codesage:quota"
_DAY_SECONDS = 24 * 60 * 60
_KEEP_SECONDS = 2 * _DAY_SECONDS  # outlive the UTC day boundary so a late INCR never resets early


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d")


class QuotaService:
    """Enforces per-user, per-IP, and global usage limits."""

    def __init__(self, client: redis.Redis, settings: AuthSettings) -> None:
        self._redis = client
        self._settings = settings

    async def _bump(self, key: str) -> int:
        """Increment a daily counter, starting its expiry on first use."""
        count = int(await self._redis.incr(key))
        if count == 1:
            await self._redis.expire(key, _KEEP_SECONDS)
        return count

    async def _peek(self, key: str) -> int:
        value = await self._redis.get(key)
        return int(value) if value is not None else 0

    def repository_limit(self, user: User) -> int:
        """Maximum non-failed repositories this user may own."""
        return self._settings.guest_max_repositories if user.kind == "guest" else self._settings.user_max_repositories

    def question_limit(self, user: User) -> int:
        """Maximum questions this user may ask per UTC day."""
        return self._settings.guest_daily_questions if user.kind == "guest" else self._settings.user_daily_questions

    async def questions_used_today(self, user: User) -> int:
        """Questions already counted today (0 if the counter store is unavailable)."""
        try:
            return await self._peek(f"{_KEY_PREFIX}:q:{user.id}:{_today()}")
        except RedisError:
            logger.warning("Redis unavailable while reading question usage", exc_info=True)
            return 0

    async def check_guest_creation(self, ip: str | None) -> None:
        """Rate-limit guest-account creation per client IP.

        Args:
            ip: The caller's address; ``None`` is rate-limited as one shared bucket.

        Raises:
            RateLimitedError: When the IP exceeded today's allowance.
            ServiceUnavailableError: If Redis is unavailable (fail closed).
        """
        key = f"{_KEY_PREFIX}:guest-create:{ip or 'unknown'}:{_today()}"
        try:
            count = await self._bump(key)
        except RedisError as exc:
            logger.exception("Redis unavailable during guest creation check")
            raise ServiceUnavailableError("Temporarily unable to create sessions; please retry shortly.") from exc
        if count > self._settings.guest_creations_per_ip_per_day:
            raise RateLimitedError("Too many guest sessions created from this network today. Try again tomorrow.")

    async def check_repository_creation(self, user: User, active_repositories: int) -> None:
        """Enforce repository limits before cloning anything.

        Order matters: the cheap ownership limit is checked first so a
        user who is already at their cap never consumes the guest-wide
        daily budget.

        Args:
            user: The creating user.
            active_repositories: How many non-failed repositories they already own.

        Raises:
            GuestQuotaExceededError: A guest reached a limit that signing in lifts.
            RateLimitedError: A member reached their repository cap.
            ServiceUnavailableError: If Redis is unavailable for a guest (fail closed).
        """
        limit = self.repository_limit(user)
        if active_repositories >= limit:
            if user.kind == "guest":
                raise GuestQuotaExceededError(
                    "Guests can index one repository. Sign in with GitHub to index more."
                )
            raise RateLimitedError(f"Repository limit reached ({limit}). Delete one to add another.")

        if user.kind != "guest":
            return
        try:
            attempts = await self._bump(f"{_KEY_PREFIX}:repo-attempts:{user.id}:{_today()}")
            if attempts > self._settings.guest_daily_repository_attempts:
                raise GuestQuotaExceededError("Too many repository attempts today. Sign in with GitHub to continue.")
            global_count = await self._bump(f"{_KEY_PREFIX}:guest-index-global:{_today()}")
        except RedisError as exc:
            logger.exception("Redis unavailable during repository quota check")
            raise ServiceUnavailableError("Temporarily unable to start indexing; please retry shortly.") from exc
        if global_count > self._settings.guest_global_daily_index_cap:
            raise RateLimitedError(
                "The free demo has reached its daily indexing capacity. Sign in with GitHub or try again tomorrow."
            )

    async def consume_question(self, user: User) -> None:
        """Count one question and enforce the daily cap (fails open on Redis errors).

        Raises:
            GuestQuotaExceededError: A guest used their daily questions.
            RateLimitedError: A member used their daily questions.
        """
        try:
            count = await self._bump(f"{_KEY_PREFIX}:q:{user.id}:{_today()}")
        except RedisError:
            logger.warning("Redis unavailable while counting a question; allowing it", exc_info=True)
            return
        if count > self.question_limit(user):
            if user.kind == "guest":
                raise GuestQuotaExceededError("Daily question limit reached. Sign in with GitHub to keep asking.")
            raise RateLimitedError("Daily question limit reached. Try again tomorrow.")


def question_key_for(user_id: uuid.UUID) -> str:
    """The Redis key holding a user's question count today (exposed for tests/ops)."""
    return f"{_KEY_PREFIX}:q:{user_id}:{_today()}"
