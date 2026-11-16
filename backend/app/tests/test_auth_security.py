"""Unit tests for the JWT / refresh-token primitives (ADR-027). No infrastructure needed."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import jwt
import pytest

from app.core.config import AuthSettings
from app.core.security import (
    AccessTokenError,
    constant_time_equals,
    create_access_token,
    decode_access_token,
    generate_refresh_token,
    hash_refresh_token,
)

SECRET = "unit-test-secret-" + "x" * 32


def make_settings(**overrides) -> AuthSettings:
    return AuthSettings(jwt_secret=SECRET, **overrides)


def test_access_token_round_trip() -> None:
    settings = make_settings()
    user_id = uuid.uuid4()
    token, expires_in = create_access_token(user_id, "guest", settings)
    claims = decode_access_token(token, settings)
    assert claims.user_id == user_id
    assert claims.kind == "guest"
    assert expires_in == settings.access_token_ttl_minutes * 60
    assert claims.expires_at > datetime.now(timezone.utc)


def test_expired_token_is_reported_as_expired() -> None:
    settings = make_settings()
    long_ago = datetime.now(timezone.utc) - timedelta(hours=2)
    token, _ = create_access_token(uuid.uuid4(), "user", settings, now=long_ago)
    with pytest.raises(AccessTokenError) as caught:
        decode_access_token(token, settings)
    assert caught.value.reason == "expired"


def test_token_signed_with_another_secret_is_rejected() -> None:
    token, _ = create_access_token(uuid.uuid4(), "user", AuthSettings(jwt_secret="a" * 40))
    with pytest.raises(AccessTokenError) as caught:
        decode_access_token(token, make_settings())
    assert caught.value.reason == "invalid"


def test_tampered_payload_is_rejected() -> None:
    settings = make_settings()
    token, _ = create_access_token(uuid.uuid4(), "guest", settings)
    header, payload, signature = token.split(".")
    forged = ".".join([header, payload[:-2] + ("AA" if not payload.endswith("AA") else "BB"), signature])
    with pytest.raises(AccessTokenError):
        decode_access_token(forged, settings)


def test_alg_none_token_is_rejected() -> None:
    """The classic JWT bypass: an unsigned token claiming alg=none must never validate."""
    settings = make_settings()
    now = datetime.now(timezone.utc)
    unsigned = jwt.encode(
        {
            "sub": str(uuid.uuid4()), "kind": "user", "jti": "x", "iss": settings.jwt_issuer,
            "iat": int(now.timestamp()), "exp": int((now + timedelta(hours=1)).timestamp()),
        },
        key=None,
        algorithm="none",
    )
    with pytest.raises(AccessTokenError):
        decode_access_token(unsigned, settings)


def test_wrong_issuer_is_rejected() -> None:
    other = AuthSettings(jwt_secret=SECRET, jwt_issuer="someone-else")
    token, _ = create_access_token(uuid.uuid4(), "user", other)
    with pytest.raises(AccessTokenError):
        decode_access_token(token, make_settings())


def test_token_missing_required_claims_is_rejected() -> None:
    settings = make_settings()
    token = jwt.encode({"sub": str(uuid.uuid4())}, SECRET, algorithm="HS256")
    with pytest.raises(AccessTokenError):
        decode_access_token(token, settings)


def test_garbage_is_rejected() -> None:
    with pytest.raises(AccessTokenError):
        decode_access_token("not-a-jwt", make_settings())


def test_refresh_tokens_are_unique_and_hash_deterministically() -> None:
    first, second = generate_refresh_token(), generate_refresh_token()
    assert first != second
    assert len(first) >= 60
    assert hash_refresh_token(first) == hash_refresh_token(first)
    assert hash_refresh_token(first) != hash_refresh_token(second)
    assert len(hash_refresh_token(first)) == 64
    assert first not in hash_refresh_token(first)


def test_constant_time_equals() -> None:
    assert constant_time_equals("abc", "abc")
    assert not constant_time_equals("abc", "abd")
    assert not constant_time_equals("abc", "abcd")
