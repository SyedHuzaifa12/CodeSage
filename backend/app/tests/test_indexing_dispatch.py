"""Tests for the API side of queue mode (ADR-028): wake/keep-alive, internal endpoints,
the queue branches of the services and routes, config guards, and role-based routing.

No infrastructure needed: collaborators are faked.
"""
from __future__ import annotations

import json
import subprocess
import sys
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import BackgroundTasks
from pydantic import SecretStr

from app.core.config import Settings, get_settings
from app.indexing import notify
from app.indexing.registry import get_runner, set_runner
from app.ingestion.exceptions import IndexingAlreadyInProgressError, NoIndexingInProgressError


@pytest.fixture
def settings(monkeypatch):
    live = get_settings()
    monkeypatch.setattr(live.indexing, "indexing_backend", "postgres")
    monkeypatch.setattr(live.indexing, "indexer_url", "https://indexer.example")
    monkeypatch.setattr(live.auth, "internal_api_token", SecretStr("s3cret"))
    monkeypatch.setattr(live.indexing, "indexer_wake_timeout_seconds", 5.0)
    return live


@pytest.fixture(autouse=True)
def no_leftover_runner():
    set_runner(None)
    yield
    set_runner(None)


def capture_http(monkeypatch, handler):
    """Make ``notify``'s httpx client talk to ``handler`` instead of the network."""
    real = httpx.AsyncClient
    monkeypatch.setattr(
        notify.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw)
    )


class TestWakeIndexer:
    async def test_posts_to_the_indexer_with_the_shared_secret(self, settings, monkeypatch):
        seen = []
        capture_http(monkeypatch, lambda request: (seen.append(request), httpx.Response(200))[1])

        await notify.wake_indexer(settings)

        request = seen[0]
        assert request.method == "POST"
        assert str(request.url) == "https://indexer.example/api/v1/internal/wake"
        assert request.headers["x-internal-token"] == "s3cret"

    async def test_heartbeat_uses_its_own_path(self, settings, monkeypatch):
        seen = []
        capture_http(monkeypatch, lambda request: (seen.append(request), httpx.Response(200))[1])
        await notify.wake_indexer(settings, path="heartbeat")
        assert str(seen[0].url).endswith("/internal/heartbeat")

    async def test_a_runner_in_this_process_is_woken_directly_without_any_http(self, settings, monkeypatch):
        capture_http(monkeypatch, lambda request: pytest.fail("must not make an HTTP call"))
        runner = SimpleNamespace(wake=lambda: runner.woken.append(1), woken=[])
        set_runner(runner)

        await notify.wake_indexer(settings)

        assert runner.woken == [1]

    @pytest.mark.parametrize("failure", [httpx.ConnectTimeout("asleep"), httpx.ConnectError("down")])
    async def test_a_failed_wake_never_raises(self, settings, monkeypatch, failure):
        def boom(request):
            raise failure

        capture_http(monkeypatch, boom)
        await notify.wake_indexer(settings)  # the job stays queued; the next wake picks it up

    async def test_an_error_status_never_raises(self, settings, monkeypatch):
        capture_http(monkeypatch, lambda request: httpx.Response(403))
        await notify.wake_indexer(settings)

    async def test_missing_configuration_is_logged_not_raised(self, settings, monkeypatch, caplog):
        monkeypatch.setattr(settings.indexing, "indexer_url", None)
        capture_http(monkeypatch, lambda request: pytest.fail("must not make an HTTP call"))
        await notify.wake_indexer(settings)
        assert "INDEXER_URL" in caplog.text


class _FakeRedis:
    def __init__(self, fail=False):
        self.keys, self.fail = {}, fail

    async def set(self, key, value, nx=False, ex=None):
        if self.fail:
            raise ConnectionError("redis down")
        if nx and key in self.keys:
            return None
        self.keys[key] = value
        return True


class TestKeepAlivePing:
    async def test_sends_at_most_one_ping_per_interval(self, settings, monkeypatch):
        redis = _FakeRedis()  # one shared instance: the limiter state must persist between polls
        monkeypatch.setattr(notify, "get_redis_client", lambda: redis)
        woke = AsyncMock()
        monkeypatch.setattr(notify, "wake_indexer", woke)

        for _ in range(5):  # five polls in a row
            await notify.ping_indexer_if_due(settings)

        assert woke.await_count == 1
        assert woke.await_args.kwargs == {"path": "heartbeat"}

    async def test_an_unavailable_rate_limiter_is_skipped_silently(self, settings, monkeypatch):
        monkeypatch.setattr(notify, "get_redis_client", lambda: _FakeRedis(fail=True))
        woke = AsyncMock()
        monkeypatch.setattr(notify, "wake_indexer", woke)

        await notify.ping_indexer_if_due(settings)  # must not turn a status poll into an error

        woke.assert_not_awaited()


class TestInternalEndpoints:
    @pytest.fixture
    def client(self, settings):
        from app.main import app

        return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")

    async def test_rejects_calls_without_the_token(self, client):
        for path in ("wake", "heartbeat"):
            assert (await client.post(f"/api/v1/internal/{path}")).status_code == 403
            assert (await client.post(f"/api/v1/internal/{path}", headers={"X-Internal-Token": "wrong"})).status_code == 403

    async def test_wake_reaches_the_runner(self, client):
        woken = []
        set_runner(SimpleNamespace(wake=lambda: woken.append(1), status=lambda: {"worker_id": "w", "running_job_id": None}))

        response = await client.post("/api/v1/internal/wake", headers={"X-Internal-Token": "s3cret"})

        assert response.status_code == 200 and woken == [1]
        assert response.json()["data"] == {"runner": True, "worker_id": "w", "running_job_id": None}

    async def test_heartbeat_also_wakes_so_a_lost_wake_is_recovered(self, client):
        woken = []
        set_runner(SimpleNamespace(wake=lambda: woken.append(1), status=lambda: {}))
        await client.post("/api/v1/internal/heartbeat", headers={"X-Internal-Token": "s3cret"})
        assert woken == [1]

    async def test_a_process_without_a_runner_answers_instead_of_erroring(self, client):
        response = await client.post("/api/v1/internal/wake", headers={"X-Internal-Token": "s3cret"})
        assert response.status_code == 200 and response.json()["data"] == {"runner": False}


class _Session:
    def __init__(self):
        self.events = []

    async def commit(self):
        self.events.append("commit")

    async def rollback(self):
        self.events.append("rollback")

    async def execute(self, *args, **kwargs):
        return None

    def expunge(self, obj):
        self.events.append("expunge")


class TestRepositoryRoutes:
    def _guard(self):
        return SimpleNamespace(
            user=SimpleNamespace(id=uuid.uuid4()),
            authorize=AsyncMock(return_value=SimpleNamespace(max_files=1500, max_bytes=40_000_000)),
        )

    async def test_queue_mode_registers_enqueues_commits_then_wakes_and_never_clones_inline(self, settings, monkeypatch):
        from app.repository import api

        session, tasks = _Session(), BackgroundTasks()
        repository = SimpleNamespace(id=uuid.uuid4(), status="cloning")
        service = SimpleNamespace(
            register_repository=AsyncMock(return_value=repository),
            create_repository=AsyncMock(side_effect=AssertionError("must not clone inside the request")),
        )

        async def enqueue(sess, repository_id, kind, **kw):
            session.events.append(("enqueue", kind, kw["max_files"], kw["max_bytes"]))

        monkeypatch.setattr(api, "enqueue_job", enqueue)
        guard = self._guard()

        response = await api.create_repository(
            SimpleNamespace(github_url="https://github.com/o/r"), tasks, service, guard, session, settings
        )

        assert response.data is repository and repository.status == "cloning"
        assert session.events == [("enqueue", "full_index", 1500, 40_000_000), "commit"]  # committed before any wake
        assert [t.func for t in tasks.tasks] == [api.wake_indexer]

    async def test_celery_mode_still_clones_inline_and_queues_nothing(self, settings, monkeypatch):
        from app.repository import api

        monkeypatch.setattr(settings.indexing, "indexing_backend", "celery")
        session, tasks = _Session(), BackgroundTasks()
        repository = SimpleNamespace(id=uuid.uuid4(), status="ready")
        service = SimpleNamespace(
            register_repository=AsyncMock(side_effect=AssertionError("queue path must not run")),
            create_repository=AsyncMock(return_value=repository),
        )
        monkeypatch.setattr(api, "enqueue_job", AsyncMock(side_effect=AssertionError("must not enqueue")))

        response = await api.create_repository(
            SimpleNamespace(github_url="u"), tasks, service, self._guard(), session, settings
        )

        assert response.data is repository and tasks.tasks == []
        service.create_repository.assert_awaited_once()

    @pytest.mark.parametrize(
        ("status", "indexing_status", "backend", "pings"),
        [
            ("cloning", "not_started", "postgres", True),
            ("pending", "not_started", "postgres", True),
            ("ready", "indexing", "postgres", True),
            ("ready", "indexed", "postgres", False),  # nothing in flight
            ("failed", "not_started", "postgres", False),
            ("ready", "indexing", "celery", False),  # no indexer to keep awake
        ],
    )
    async def test_status_polls_ping_the_indexer_only_while_work_is_in_flight(
        self, settings, monkeypatch, status, indexing_status, backend, pings
    ):
        from app.repository import api

        monkeypatch.setattr(settings.indexing, "indexing_backend", backend)
        tasks = BackgroundTasks()
        repository = SimpleNamespace(status=status, indexing_status=indexing_status)

        response = await api.get_repository(tasks, repository, settings)

        assert response.data is repository
        assert [t.func for t in tasks.tasks] == ([api.ping_indexer_if_due] if pings else [])


class TestWorkspaceServiceQueueMode:
    @pytest.fixture
    def service(self, settings, monkeypatch):
        from app.ingestion import service as service_module

        repo = SimpleNamespace(id=uuid.uuid4(), status="ready", indexing_status="not_started", indexing_progress=0,
                               error_message=None, celery_task_id=None)
        session = _Session()
        self.repo, self.session, self.module = repo, session, service_module
        monkeypatch.setattr(service_module.repository_db, "get_by_id", AsyncMock(return_value=repo))
        monkeypatch.setattr(service_module.repository_db, "save", AsyncMock())
        monkeypatch.setattr(service_module.ingestion_db, "get_workspace", AsyncMock(return_value=SimpleNamespace()))
        monkeypatch.setattr(
            service_module, "enqueue_job",
            AsyncMock(side_effect=lambda *a, **k: session.events.append("enqueue")),
        )
        monkeypatch.setattr(service_module, "cancel_job", AsyncMock(side_effect=lambda *a, **k: session.events.append("cancel")))
        return service_module.WorkspaceService(session=session)

    async def test_index_request_queues_a_job_and_never_touches_celery(self, service, monkeypatch):
        from app.ingestion import tasks

        monkeypatch.setattr(tasks.run_indexing_task, "delay", lambda *a, **k: pytest.fail("Celery must not be used"))

        await service.request_indexing(self.repo.id)

        assert self.repo.indexing_status == "indexing"
        assert self.session.events == ["enqueue", "commit"]
        assert self.repo.celery_task_id is None

    async def test_a_racing_duplicate_is_rolled_back_and_reported(self, service):
        self.module.enqueue_job.side_effect = IndexingAlreadyInProgressError("already queued")

        with pytest.raises(IndexingAlreadyInProgressError):
            await service.request_indexing(self.repo.id)

        assert self.session.events == ["rollback"]  # the optimistic 'indexing' flip is undone

    async def test_cancel_withdraws_the_job_and_marks_the_repository_failed(self, service):
        self.repo.indexing_status = "indexing"

        repository = await service.cancel_indexing(self.repo.id)

        # The job cancellation is committed on its own first, so the indexer can see it before anything can block.
        assert self.session.events == ["cancel", "commit", "commit"]
        assert (repository.indexing_status, repository.error_message) == ("failed", "Indexing was cancelled by request.")
        assert repository.status == "ready"

    async def test_when_the_repository_row_is_locked_by_the_running_job_the_request_still_returns(self, service, monkeypatch):
        """The running job holds the row lock; the cancel must not hang, and the indexer finishes the job."""
        from sqlalchemy.exc import DBAPIError

        self.repo.indexing_status = "indexing"
        busy = DBAPIError("UPDATE ...", {}, SimpleNamespace(sqlstate="55P03"))
        self.module.repository_db.save.side_effect = busy

        repository = await service.cancel_indexing(self.repo.id)

        assert self.session.events == ["cancel", "commit", "rollback", "expunge"]  # job cancelled + committed first
        assert (repository.indexing_status, repository.error_message) == ("failed", "Indexing was cancelled by request.")

    async def test_any_other_database_error_is_not_swallowed(self, service):
        from sqlalchemy.exc import DBAPIError

        self.repo.indexing_status = "indexing"
        self.module.repository_db.save.side_effect = DBAPIError("UPDATE ...", {}, SimpleNamespace(sqlstate="23505"))

        with pytest.raises(DBAPIError):
            await service.cancel_indexing(self.repo.id)

    async def test_a_repository_still_cloning_can_be_cancelled(self, service):
        self.repo.status, self.repo.indexing_status = "cloning", "not_started"

        repository = await service.cancel_indexing(self.repo.id)

        assert (repository.status, repository.indexing_status) == ("failed", "failed")

    async def test_cancel_with_nothing_running_is_refused(self, service):
        self.repo.indexing_status = "indexed"
        with pytest.raises(NoIndexingInProgressError):
            await service.cancel_indexing(self.repo.id)
        assert self.session.events == []


class TestConfigurationGuards:
    def _production(self, monkeypatch, **overrides):
        settings = Settings()
        monkeypatch.setattr(settings.app, "environment", "production")
        for key, value in overrides.items():
            group, name = key.split("__")
            monkeypatch.setattr(getattr(settings, group), name, value)
        return settings.production_problems()

    def test_an_api_role_in_queue_mode_must_know_where_the_indexer_is(self, monkeypatch):
        problems = self._production(monkeypatch, app__role="api", indexing__indexing_backend="postgres", indexing__indexer_url=None)
        assert any("INDEXER_URL" in p for p in problems)

    def test_an_api_role_with_an_indexer_url_is_fine(self, monkeypatch):
        problems = self._production(
            monkeypatch, app__role="api", indexing__indexing_backend="postgres", indexing__indexer_url="https://i.example"
        )
        assert not any("INDEXER_URL" in p for p in problems)

    def test_an_indexer_role_needs_the_queue_backend(self, monkeypatch):
        problems = self._production(monkeypatch, app__role="indexer", indexing__indexing_backend="celery")
        assert any("ROLE=indexer" in p for p in problems)

    def test_defaults_keep_local_development_unchanged(self):
        settings = Settings()
        assert (settings.app.role, settings.indexing.indexing_backend) == ("all", "celery")

    def test_a_blank_or_padded_indexer_url_is_normalised(self):
        from app.core.config import IndexingSettings

        assert IndexingSettings(indexer_url="  ").indexer_url is None
        assert IndexingSettings(indexer_url=" https://i.example/ ").indexer_url == "https://i.example"


class TestRolesMountOnlyWhatTheyNeed:
    @pytest.mark.parametrize(
        ("role", "has_user_routes", "has_wake"),
        [("api", True, False), ("indexer", False, True), ("all", True, True)],
    )
    def test_routes_by_role(self, role, has_user_routes, has_wake):
        code = (
            "import json; from app.main import app; "
            "print(json.dumps(sorted({r.path for r in app.routes if hasattr(r, 'path')})))"
        )
        result = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True, timeout=60,
            env={**__import__("os").environ, "ROLE": role},
        )
        assert result.returncode == 0, result.stderr
        paths = json.loads(result.stdout.strip().splitlines()[-1])

        assert any(p.endswith("/repositories") for p in paths) is has_user_routes
        assert any(p.endswith("/auth/guest") for p in paths) is has_user_routes
        assert any(p.endswith("/internal/wake") for p in paths) is has_wake
        assert "/health/live" in paths  # every role is probe-able
