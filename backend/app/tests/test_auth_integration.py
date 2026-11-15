"""Integration tests for accounts, sessions, ownership and quotas (ADR-027).

Run against the real Postgres/Redis/Qdrant the app itself connects to and
skipped cleanly (not failed) when that infrastructure is unreachable or the
``users`` table has not been migrated yet. Every test creates its own users
and repositories (unique ids, torn down afterwards), so tests are
order-independent and never touch real data.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from pydantic import SecretStr
from sqlalchemy import delete, select, text, update

from app.auth.exceptions import (
    OAuthError,
    RefreshTokenReuseError,
    UnauthenticatedError,
)
from app.auth.github import GitHubOAuthClient
from app.auth.quota import QuotaService
from app.auth.service import AuthService
from app.auth.turnstile import TurnstileVerifier
from app.core.config import get_settings
from app.core.security import create_access_token
from app.db.postgres import check_postgres_connection, get_session_factory
from app.db.qdrant import check_qdrant_connection
from app.db.redis import check_redis_connection, get_redis_client
from app.models.refresh_token import RefreshToken
from app.models.repository import Repository
from app.models.user import User
from app.repository.service import RepositoryService


async def _infra_ready() -> bool:
    if not (await check_postgres_connection() and await check_redis_connection() and await check_qdrant_connection()):
        return False
    try:
        async with get_session_factory()() as session:
            await session.execute(text("SELECT 1 FROM users LIMIT 1"))
        return True
    except Exception:  # noqa: BLE001 -- table missing => migration not applied => skip
        return False


@pytest_asyncio.fixture
async def infra():
    if not await _infra_ready():
        pytest.skip("Postgres/Redis/Qdrant unreachable or `alembic upgrade head` not applied — skipping.")
    yield


@pytest_asyncio.fixture
async def tracked(infra):
    """Collects ids created by a test and deletes them afterwards (repositories first: FK is RESTRICT)."""
    bucket = {"users": [], "repos": []}
    yield bucket
    async with get_session_factory()() as session:
        owned = select(Repository.id).where(Repository.owner_id.in_(bucket["users"]))
        await session.execute(delete(Repository).where(Repository.id.in_(owned)))
        await session.execute(delete(Repository).where(Repository.id.in_(bucket["repos"])))
        await session.execute(delete(User).where(User.id.in_(bucket["users"])))
        await session.commit()


@pytest.fixture
def settings(monkeypatch):
    """The live settings object with abuse limits relaxed so unrelated tests never trip them."""
    live = get_settings()
    monkeypatch.setattr(live.auth, "guest_creations_per_ip_per_day", 10_000)
    monkeypatch.setattr(live.auth, "guest_global_daily_index_cap", 10_000)
    monkeypatch.setattr(live.auth, "guest_daily_repository_attempts", 10_000)
    monkeypatch.setattr(live.auth, "refresh_reuse_grace_seconds", 0)
    monkeypatch.setattr(live.auth, "github_client_id", "client-id")
    monkeypatch.setattr(live.auth, "github_client_secret", SecretStr("client-secret"))
    monkeypatch.setattr(live.auth, "github_redirect_uri", "https://app.example/auth/callback")
    return live


def github_transport(github_id: int, login: str = "octocat") -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/login/oauth/access_token":
            return httpx.Response(200, json={"access_token": "gho_token"})
        if request.url.path == "/user":
            return httpx.Response(200, json={"id": github_id, "login": login, "name": login.title(), "avatar_url": None})
        return httpx.Response(404)

    return httpx.MockTransport(handler)


def build_service(session, settings, transport=None) -> AuthService:
    client = get_redis_client()
    return AuthService(
        session=session,
        redis_client=client,
        settings=settings,
        quota=QuotaService(client, settings.auth),
        turnstile=TurnstileVerifier(settings),
        github=GitHubOAuthClient(settings.auth, transport=transport),
        repository_service=RepositoryService(session=session, settings=settings, workspace_service=None),  # type: ignore[arg-type]
    )


async def do(settings, action, *, transport=None):
    """Run one service call the way a request would: its own session, committed on success."""
    async with get_session_factory()() as session:
        result = await action(build_service(session, settings, transport))
        await session.commit()
        return result


def unique_ip() -> str:
    return f"test-{uuid.uuid4()}"


async def new_guest(settings, tracked):
    issued = await do(settings, lambda svc: svc.create_guest(None, unique_ip()))
    tracked["users"].append(issued.user.id)
    return issued


async def new_member(tracked, *, login: str | None = None, github_id: int | None = None) -> User:
    async with get_session_factory()() as session:
        user = User(
            id=uuid.uuid4(), kind="user", github_id=github_id or uuid.uuid4().int % 10**9,
            github_login=login or f"member-{uuid.uuid4().hex[:8]}",
        )
        session.add(user)
        await session.commit()
    tracked["users"].append(user.id)
    return user


async def seed_repo(tracked, owner_id, tmp_path: Path, *, is_demo: bool = False) -> uuid.UUID:
    repo_id = uuid.uuid4()
    async with get_session_factory()() as session:
        session.add(
            Repository(
                id=repo_id, name="seeded", github_url=f"https://github.com/o/{repo_id.hex[:8]}",
                local_path=str(tmp_path / repo_id.hex), status="ready", owner_id=owner_id, is_demo=is_demo,
            )
        )
        await session.commit()
    tracked["repos"].append(repo_id)
    return repo_id


async def owner_of(repo_id: uuid.UUID):
    async with get_session_factory()() as session:
        return (await session.get(Repository, repo_id)).owner_id


def bearer(user: User, settings) -> dict[str, str]:
    token, _ = create_access_token(user.id, user.kind, settings.auth)
    return {"Authorization": f"Bearer {token}"}


# =========================================================================================
# Sessions and refresh-token rotation
# =========================================================================================

async def test_guest_session_is_created_with_an_expiry(settings, tracked) -> None:
    issued = await new_guest(settings, tracked)
    assert issued.user.kind == "guest"
    hours = (issued.user.guest_expires_at - datetime.now(timezone.utc)).total_seconds() / 3600
    assert settings.auth.guest_ttl_hours - 0.1 < hours <= settings.auth.guest_ttl_hours
    assert issued.access_token and issued.refresh_token


async def test_refresh_rotates_the_token_and_retires_the_old_one(settings, tracked) -> None:
    first = await new_guest(settings, tracked)
    second = await do(settings, lambda svc: svc.refresh(first.refresh_token))
    assert second.refresh_token != first.refresh_token
    assert second.user.id == first.user.id
    third = await do(settings, lambda svc: svc.refresh(second.refresh_token))
    assert third.refresh_token not in (first.refresh_token, second.refresh_token)


async def test_replaying_a_rotated_token_revokes_the_whole_family(settings, tracked) -> None:
    first = await new_guest(settings, tracked)
    second = await do(settings, lambda svc: svc.refresh(first.refresh_token))
    with pytest.raises(RefreshTokenReuseError):
        await do(settings, lambda svc: svc.refresh(first.refresh_token))  # attacker replays the stolen token
    # ...and the legitimate holder's newer token is dead too: the family was revoked.
    with pytest.raises(UnauthenticatedError):
        await do(settings, lambda svc: svc.refresh(second.refresh_token))


async def test_a_replay_inside_the_grace_window_is_rejected_but_does_not_revoke(settings, tracked, monkeypatch) -> None:
    monkeypatch.setattr(settings.auth, "refresh_reuse_grace_seconds", 60)
    first = await new_guest(settings, tracked)
    second = await do(settings, lambda svc: svc.refresh(first.refresh_token))
    with pytest.raises(UnauthenticatedError) as caught:
        await do(settings, lambda svc: svc.refresh(first.refresh_token))  # e.g. a second browser tab racing
    assert not isinstance(caught.value, RefreshTokenReuseError)
    await do(settings, lambda svc: svc.refresh(second.refresh_token))  # the newest token still works


async def test_unknown_refresh_token_is_rejected(settings, infra) -> None:
    with pytest.raises(UnauthenticatedError):
        await do(settings, lambda svc: svc.refresh("x" * 64))


async def test_expired_refresh_token_is_rejected(settings, tracked) -> None:
    issued = await new_guest(settings, tracked)
    async with get_session_factory()() as session:
        await session.execute(
            update(RefreshToken)
            .where(RefreshToken.user_id == issued.user.id)
            .values(expires_at=datetime.now(timezone.utc) - timedelta(minutes=1))
        )
        await session.commit()
    with pytest.raises(UnauthenticatedError):
        await do(settings, lambda svc: svc.refresh(issued.refresh_token))


async def test_an_expired_guest_cannot_refresh(settings, tracked) -> None:
    issued = await new_guest(settings, tracked)
    async with get_session_factory()() as session:
        await session.execute(
            update(User).where(User.id == issued.user.id).values(guest_expires_at=datetime.now(timezone.utc) - timedelta(minutes=1))
        )
        await session.commit()
    with pytest.raises(UnauthenticatedError):
        await do(settings, lambda svc: svc.refresh(issued.refresh_token))


async def test_logout_revokes_the_session(settings, tracked) -> None:
    issued = await new_guest(settings, tracked)
    await do(settings, lambda svc: svc.logout(issued.refresh_token))
    with pytest.raises(UnauthenticatedError):
        await do(settings, lambda svc: svc.refresh(issued.refresh_token))
    await do(settings, lambda svc: svc.logout(issued.refresh_token))  # idempotent


async def test_refresh_tokens_are_stored_hashed(settings, tracked) -> None:
    issued = await new_guest(settings, tracked)
    async with get_session_factory()() as session:
        rows = (await session.execute(select(RefreshToken).where(RefreshToken.user_id == issued.user.id))).scalars().all()
    assert rows and all(issued.refresh_token != row.token_hash and len(row.token_hash) == 64 for row in rows)


# =========================================================================================
# GitHub login: new member, guest upgrade in place, merge into an existing member
# =========================================================================================

async def github_login(settings, github_id: int, current_user=None, login: str = "octocat"):
    transport = github_transport(github_id, login)
    _, state = await do(settings, lambda svc: svc.github_authorize(), transport=transport)
    return await do(settings, lambda svc: svc.github_login("code", state, current_user), transport=transport)


async def test_github_login_creates_a_new_member(settings, tracked) -> None:
    github_id = uuid.uuid4().int % 10**9
    result = await github_login(settings, github_id, login="newcomer")
    tracked["users"].append(result.session.user.id)
    user = result.session.user
    assert (user.kind, user.github_id, user.github_login) == ("user", github_id, "newcomer")
    assert user.guest_expires_at is None
    assert result.repositories_transferred == 0


async def test_oauth_state_is_single_use(settings, tracked) -> None:
    transport = github_transport(uuid.uuid4().int % 10**9)
    _, state = await do(settings, lambda svc: svc.github_authorize(), transport=transport)
    first = await do(settings, lambda svc: svc.github_login("code", state, None), transport=transport)
    tracked["users"].append(first.session.user.id)
    with pytest.raises(OAuthError):
        await do(settings, lambda svc: svc.github_login("code", state, None), transport=transport)


async def test_forged_oauth_state_is_rejected(settings, infra) -> None:
    with pytest.raises(OAuthError):
        await do(settings, lambda svc: svc.github_login("code", "never-issued", None), transport=github_transport(1))


async def test_guest_is_upgraded_in_place_and_keeps_their_repository(settings, tracked, tmp_path) -> None:
    guest = await new_guest(settings, tracked)
    repo_id = await seed_repo(tracked, guest.user.id, tmp_path)
    async with get_session_factory()() as session:
        current = await session.get(User, guest.user.id)
    result = await github_login(settings, uuid.uuid4().int % 10**9, current_user=current, login="converted")
    user = result.session.user
    assert user.id == guest.user.id  # same row: nothing had to be moved
    assert (user.kind, user.github_login, user.guest_expires_at) == ("user", "converted", None)
    assert await owner_of(repo_id) == guest.user.id
    with pytest.raises(UnauthenticatedError):  # the old guest session was retired
        await do(settings, lambda svc: svc.refresh(guest.refresh_token))


async def test_guest_repositories_move_into_an_existing_member(settings, tracked, tmp_path) -> None:
    github_id = uuid.uuid4().int % 10**9
    member = await new_member(tracked, github_id=github_id)
    guest = await new_guest(settings, tracked)
    repo_id = await seed_repo(tracked, guest.user.id, tmp_path)
    async with get_session_factory()() as session:
        current = await session.get(User, guest.user.id)
    result = await github_login(settings, github_id, current_user=current)
    assert result.session.user.id == member.id
    assert result.repositories_transferred == 1
    assert await owner_of(repo_id) == member.id


async def test_transfer_respects_the_members_repository_cap(settings, tracked, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings.auth, "user_max_repositories", 1)
    github_id = uuid.uuid4().int % 10**9
    member = await new_member(tracked, github_id=github_id)
    await seed_repo(tracked, member.id, tmp_path)  # member is already at the cap
    guest = await new_guest(settings, tracked)
    repo_id = await seed_repo(tracked, guest.user.id, tmp_path)
    async with get_session_factory()() as session:
        current = await session.get(User, guest.user.id)
    result = await github_login(settings, github_id, current_user=current)
    assert result.repositories_transferred == 0
    assert await owner_of(repo_id) == guest.user.id


# =========================================================================================
# Guest cleanup
# =========================================================================================

async def test_cleanup_removes_expired_guests_and_their_repositories_only(settings, tracked, tmp_path) -> None:
    expired = await new_guest(settings, tracked)
    live = await new_guest(settings, tracked)
    expired_repo = await seed_repo(tracked, expired.user.id, tmp_path)
    live_repo = await seed_repo(tracked, live.user.id, tmp_path)
    async with get_session_factory()() as session:
        await session.execute(
            update(User).where(User.id == expired.user.id).values(guest_expires_at=datetime.now(timezone.utc) - timedelta(minutes=5))
        )
        await session.commit()

    summary = await do(settings, lambda svc: svc.cleanup_expired_guests(limit=500))
    assert summary.guests_deleted >= 1 and summary.repositories_deleted >= 1

    async with get_session_factory()() as session:
        assert await session.get(User, expired.user.id) is None
        assert await session.get(Repository, expired_repo) is None
        assert await session.get(User, live.user.id) is not None
        assert await session.get(Repository, live_repo) is not None


async def test_cleanup_never_deletes_members_or_demo_repositories(settings, tracked, tmp_path) -> None:
    member = await new_member(tracked)
    demo = await seed_repo(tracked, member.id, tmp_path, is_demo=True)
    await do(settings, lambda svc: svc.cleanup_expired_guests(limit=500))
    async with get_session_factory()() as session:
        assert await session.get(User, member.id) is not None
        assert await session.get(Repository, demo) is not None


# =========================================================================================
# HTTP level: authentication, ownership (IDOR), demo read-only, quotas, internal endpoint
# =========================================================================================

@pytest_asyncio.fixture
async def client(infra):
    from app.main import app

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http:
        yield http


async def guest_over_http(client, tracked, ip: str | None = None):
    response = await client.post("/api/v1/auth/guest", json={}, headers={"x-forwarded-for": ip or unique_ip()})
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    tracked["users"].append(uuid.UUID(data["user"]["id"]))
    return data, {"Authorization": f"Bearer {data['tokens']['access_token']}"}


async def test_requests_without_credentials_are_rejected(client) -> None:
    response = await client.get("/api/v1/repositories")
    assert response.status_code == 401
    assert response.json()["errors"][0]["code"] == "UNAUTHENTICATED"
    assert response.headers["www-authenticate"] == "Bearer"


async def test_a_garbage_token_is_rejected(client) -> None:
    response = await client.get("/api/v1/repositories", headers={"Authorization": "Bearer not.a.jwt"})
    assert response.status_code == 401


async def test_health_stays_public(client) -> None:
    assert (await client.get("/health/live")).status_code == 200


async def test_guest_session_over_http_and_me_endpoint(client, settings, tracked) -> None:
    data, headers = await guest_over_http(client, tracked)
    assert data["user"]["kind"] == "guest" and data["user"]["is_admin"] is False
    me = (await client.get("/api/v1/auth/me", headers=headers)).json()["data"]
    assert me["user"]["id"] == data["user"]["id"]
    assert me["quota"]["repositories_limit"] == settings.auth.guest_max_repositories
    assert me["quota"]["repositories_used"] == 0


async def test_guest_creation_is_rate_limited_per_ip(client, settings, tracked, monkeypatch) -> None:
    monkeypatch.setattr(settings.auth, "trusted_proxy_hops", 1)
    monkeypatch.setattr(settings.auth, "guest_creations_per_ip_per_day", 2)
    ip = unique_ip()
    await guest_over_http(client, tracked, ip)
    await guest_over_http(client, tracked, ip)
    blocked = await client.post("/api/v1/auth/guest", json={}, headers={"x-forwarded-for": ip})
    assert blocked.status_code == 429
    assert blocked.json()["errors"][0]["code"] == "RATE_LIMITED"


async def test_refresh_over_http_rotates_and_flags_reuse(client, settings, tracked) -> None:
    data, _ = await guest_over_http(client, tracked)
    old = data["tokens"]["refresh_token"]
    rotated = await client.post("/api/v1/auth/refresh", json={"refresh_token": old})
    assert rotated.status_code == 200
    replay = await client.post("/api/v1/auth/refresh", json={"refresh_token": old})
    assert replay.status_code == 401
    assert replay.json()["errors"][0]["code"] == "TOKEN_REUSED"


async def test_github_authorize_endpoint(client, settings) -> None:
    response = await client.get("/api/v1/auth/github/authorize")
    assert response.status_code == 200
    body = response.json()["data"]
    assert "client_id=client-id" in body["authorize_url"] and body["state"] in body["authorize_url"]


async def test_github_authorize_reports_unconfigured_login(client, settings, monkeypatch) -> None:
    monkeypatch.setattr(settings.auth, "github_client_id", None)
    response = await client.get("/api/v1/auth/github/authorize")
    assert response.status_code == 503
    assert response.json()["errors"][0]["code"] == "SERVICE_UNAVAILABLE"


async def test_a_user_only_sees_their_own_repositories(client, settings, tracked, tmp_path) -> None:
    (data_a, headers_a), (data_b, headers_b) = await guest_over_http(client, tracked), await guest_over_http(client, tracked)
    repo_a = await seed_repo(tracked, uuid.UUID(data_a["user"]["id"]), tmp_path)

    mine = (await client.get("/api/v1/repositories", headers=headers_a)).json()["data"]["repositories"]
    theirs = (await client.get("/api/v1/repositories", headers=headers_b)).json()["data"]["repositories"]
    assert str(repo_a) in {r["id"] for r in mine}
    assert str(repo_a) not in {r["id"] for r in theirs}


async def test_another_users_repository_is_indistinguishable_from_a_missing_one(client, settings, tracked, tmp_path) -> None:
    (data_a, headers_a), (_, headers_b) = await guest_over_http(client, tracked), await guest_over_http(client, tracked)
    repo_a = await seed_repo(tracked, uuid.UUID(data_a["user"]["id"]), tmp_path)

    assert (await client.get(f"/api/v1/repositories/{repo_a}", headers=headers_a)).status_code == 200

    stolen = await client.get(f"/api/v1/repositories/{repo_a}", headers=headers_b)
    missing = await client.get(f"/api/v1/repositories/{uuid.uuid4()}", headers=headers_b)
    assert stolen.status_code == missing.status_code == 404
    # Same message shape: nothing reveals that the id is real.
    assert stolen.json()["message"].replace(str(repo_a), "ID") == missing.json()["message"].replace(
        missing.json()["message"].split("'")[1], "ID"
    )


async def test_every_sub_resource_is_protected_not_just_the_repository_route(client, settings, tracked, tmp_path) -> None:
    (data_a, _), (_, headers_b) = await guest_over_http(client, tracked), await guest_over_http(client, tracked)
    repo = await seed_repo(tracked, uuid.UUID(data_a["user"]["id"]), tmp_path)
    base = f"/api/v1/repositories/{repo}"

    reads = ["/workspace", "/tree", "/intelligence", "/call-graph", "/dependency-graph", "/symbols",
             "/knowledge", "/knowledge/chunks", "/retrieval/query?q=auth", "/reports", "/reports/summary"]
    writes = [("POST", "/refresh"), ("POST", "/reset"), ("POST", "/index"), ("POST", "/index/cancel"),
              ("POST", "/knowledge/reindex"), ("POST", "/ask"), ("POST", "/reports/summary"),
              ("PATCH", ""), ("DELETE", "")]

    for path in reads:
        assert (await client.get(base + path, headers=headers_b)).status_code == 404, f"GET {path} leaked"
    for method, path in writes:
        body = {"query": "how does auth work"} if path == "/ask" else ({"name": "x"} if method == "PATCH" else None)
        response = await client.request(method, base + path, headers=headers_b, json=body)
        assert response.status_code == 404, f"{method} {path} was not blocked"

    async with get_session_factory()() as session:
        assert await session.get(Repository, repo) is not None  # the attempted DELETE did nothing


async def test_a_blocked_request_does_not_cost_the_attacker_a_question(client, settings, tracked, tmp_path) -> None:
    (data_a, _), (data_b, headers_b) = await guest_over_http(client, tracked), await guest_over_http(client, tracked)
    repo = await seed_repo(tracked, uuid.UUID(data_a["user"]["id"]), tmp_path)
    await client.post(f"/api/v1/repositories/{repo}/ask", headers=headers_b, json={"query": "hello"})
    me = (await client.get("/api/v1/auth/me", headers=headers_b)).json()["data"]
    assert me["quota"]["questions_used_today"] == 0


async def test_owner_can_delete_their_repository(client, settings, tracked, tmp_path) -> None:
    data, headers = await guest_over_http(client, tracked)
    repo = await seed_repo(tracked, uuid.UUID(data["user"]["id"]), tmp_path)
    assert (await client.delete(f"/api/v1/repositories/{repo}", headers=headers)).status_code == 200
    assert (await client.get(f"/api/v1/repositories/{repo}", headers=headers)).status_code == 404


async def test_demo_repository_is_readable_by_everyone_but_writable_only_by_admins(client, settings, tracked, tmp_path, monkeypatch) -> None:
    admin = await new_member(tracked, login="the-admin")
    monkeypatch.setattr(settings.auth, "admin_github_logins", "the-admin")
    demo = await seed_repo(tracked, admin.id, tmp_path, is_demo=True)
    _, guest_headers = await guest_over_http(client, tracked)
    base = f"/api/v1/repositories/{demo}"

    listed = (await client.get("/api/v1/repositories", headers=guest_headers)).json()["data"]["repositories"]
    assert any(r["id"] == str(demo) and r["is_demo"] for r in listed)
    assert (await client.get(base, headers=guest_headers)).status_code == 200

    for method, path in [("PATCH", ""), ("DELETE", ""), ("POST", "/index"), ("POST", "/reset"),
                         ("POST", "/refresh"), ("POST", "/knowledge/reindex"), ("POST", "/index/cancel")]:
        response = await client.request(method, base + path, headers=guest_headers, json={"name": "x"} if method == "PATCH" else None)
        assert response.status_code == 403, f"{method} {path} let a guest modify the demo"
        assert response.json()["errors"][0]["code"] == "FORBIDDEN"

    renamed = await client.patch(base, headers=bearer(admin, settings), json={"name": "Express (demo)"})
    assert renamed.status_code == 200


async def test_guests_cannot_force_regenerate_demo_reports(client, settings, tracked, tmp_path) -> None:
    admin = await new_member(tracked)
    demo = await seed_repo(tracked, admin.id, tmp_path, is_demo=True)
    _, guest_headers = await guest_over_http(client, tracked)
    response = await client.post(
        f"/api/v1/repositories/{demo}/reports/summary", headers=guest_headers, json={"force_regenerate": True}
    )
    assert response.status_code == 403


async def test_guest_question_quota_prompts_sign_in(client, settings, tracked, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings.auth, "guest_daily_questions", 0)
    data, headers = await guest_over_http(client, tracked)
    repo = await seed_repo(tracked, uuid.UUID(data["user"]["id"]), tmp_path)
    response = await client.post(f"/api/v1/repositories/{repo}/ask", headers=headers, json={"query": "how does auth work"})
    assert response.status_code == 403
    assert response.json()["errors"][0]["code"] == "GUEST_QUOTA_EXCEEDED"


async def test_guest_cannot_create_a_second_repository(client, settings, tracked, tmp_path) -> None:
    data, headers = await guest_over_http(client, tracked)
    await seed_repo(tracked, uuid.UUID(data["user"]["id"]), tmp_path)
    response = await client.post(
        "/api/v1/repositories", headers=headers, json={"github_url": "https://github.com/octocat/Hello-World"}
    )
    assert response.status_code == 403
    assert response.json()["errors"][0]["code"] == "GUEST_QUOTA_EXCEEDED"
    me = (await client.get("/api/v1/auth/me", headers=headers)).json()["data"]
    assert me["quota"]["repositories_used"] == 1 == me["quota"]["repositories_limit"]


async def test_a_malformed_url_does_not_burn_a_guests_daily_attempts(client, settings, tracked) -> None:
    data, headers = await guest_over_http(client, tracked)
    response = await client.post("/api/v1/repositories", headers=headers, json={"github_url": "file:///etc/passwd"})
    assert response.status_code == 422
    key = f"codesage:quota:repo-attempts:{data['user']['id']}:{datetime.now(timezone.utc).strftime('%Y%m%d')}"
    assert await get_redis_client().get(key) is None


async def test_non_github_urls_are_refused(client, settings, tracked) -> None:
    _, headers = await guest_over_http(client, tracked)
    for url in ["http://github.com/o/r", "https://evil.example/o/r", "git@github.com:o/r.git",
                "https://github.com/o/r/../../etc", "https://github.com.evil.example/o/r", "file:///etc/passwd"]:
        response = await client.post("/api/v1/repositories", headers=headers, json={"github_url": url})
        assert response.status_code == 422, f"{url} was accepted"


async def test_logs_endpoint_is_admin_only(client, settings, tracked, monkeypatch) -> None:
    _, guest_headers = await guest_over_http(client, tracked)
    plain = await new_member(tracked)
    admin = await new_member(tracked, login="log-admin")
    monkeypatch.setattr(settings.auth, "admin_github_logins", "log-admin")
    assert (await client.get("/api/v1/logs")).status_code == 401
    assert (await client.get("/api/v1/logs", headers=guest_headers)).status_code == 403
    assert (await client.get("/api/v1/logs", headers=bearer(plain, settings))).status_code == 403
    assert (await client.get("/api/v1/logs", headers=bearer(admin, settings))).status_code == 200


async def test_internal_cleanup_endpoint_requires_the_shared_token(client, settings, tracked, monkeypatch) -> None:
    url = "/api/v1/internal/cleanup-guests"
    monkeypatch.setattr(settings.auth, "internal_api_token", None)
    assert (await client.post(url, headers={"x-internal-token": "anything"})).status_code == 503  # disabled, not open

    monkeypatch.setattr(settings.auth, "internal_api_token", SecretStr("correct-token"))
    assert (await client.post(url)).status_code == 403
    assert (await client.post(url, headers={"x-internal-token": "wrong"})).status_code == 403
    ok = await client.post(url, headers={"x-internal-token": "correct-token"})
    assert ok.status_code == 200
    assert {"guests_deleted", "repositories_deleted", "guests_failed"} <= ok.json()["data"].keys()
