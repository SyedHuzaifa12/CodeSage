"""Unit tests for duplicate-job prevention on ``POST /repositories/{id}/index``.

Without Celery (ADR-011 freezes it out for V1 — see the conflict noted
in this pass's final report), the concrete, in-scope fix for "re-clicking
index twice shouldn't double-run" is a guard in
``WorkspaceService.request_indexing``: reject a second trigger while a
previous run is still ``indexing``, rather than silently starting a
second concurrent ``run_parsing_pipeline`` background task against the
same repository/Qdrant collection.

Pure unit tests with monkeypatched data-access functions — no real
Postgres needed, since ``WorkspaceService`` only reaches the database
through ``repository_db``/``ingestion_db`` module-level functions.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Optional

import pytest

from app.ingestion.exceptions import IndexingAlreadyInProgressError, RepositoryNotReadyError
from app.ingestion.service import WorkspaceService


@dataclass
class FakeRepository:
    id: uuid.UUID
    status: str = "ready"
    indexing_status: str = "not_started"
    indexing_progress: int = 0
    error_message: Optional[str] = None
    celery_task_id: Optional[str] = None


@dataclass
class _FakeAsyncResult:
    id: str = "fake-task-id"


@dataclass
class FakeWorkspace:
    repository_id: uuid.UUID
    status: str = "ready"


class FakeSession:
    async def commit(self) -> None:
        return None


def _patch_data_access(monkeypatch: pytest.MonkeyPatch, repository: FakeRepository, workspace: FakeWorkspace):
    from app.ingestion import service as service_module

    async def _get_by_id(session, repository_id):
        return repository if repository.id == repository_id else None

    async def _get_workspace(session, repository_id):
        return workspace if workspace.repository_id == repository_id else None

    async def _save(session, obj):
        return obj

    monkeypatch.setattr(service_module.repository_db, "get_by_id", _get_by_id)
    monkeypatch.setattr(service_module.ingestion_db, "get_workspace", _get_workspace)
    monkeypatch.setattr(service_module.repository_db, "save", _save)

    from app.ingestion import tasks as tasks_module

    monkeypatch.setattr(tasks_module.run_indexing_task, "delay", lambda *args, **kwargs: _FakeAsyncResult())


class TestDuplicateIndexPrevention:
    async def test_second_trigger_while_indexing_is_rejected(self, monkeypatch: pytest.MonkeyPatch):
        repo_id = uuid.uuid4()
        repository = FakeRepository(id=repo_id, status="ready", indexing_status="indexing", indexing_progress=42)
        workspace = FakeWorkspace(repository_id=repo_id)
        _patch_data_access(monkeypatch, repository, workspace)

        service = WorkspaceService(session=FakeSession())

        with pytest.raises(IndexingAlreadyInProgressError):
            await service.request_indexing(repo_id)

    async def test_trigger_is_allowed_when_not_started(self, monkeypatch: pytest.MonkeyPatch):
        repo_id = uuid.uuid4()
        repository = FakeRepository(id=repo_id, status="ready", indexing_status="not_started")
        workspace = FakeWorkspace(repository_id=repo_id)
        _patch_data_access(monkeypatch, repository, workspace)

        service = WorkspaceService(session=FakeSession())
        await service.request_indexing(repo_id)

        assert repository.indexing_status == "indexing"

    async def test_trigger_is_allowed_after_a_previous_failure(self, monkeypatch: pytest.MonkeyPatch):
        repo_id = uuid.uuid4()
        repository = FakeRepository(id=repo_id, status="ready", indexing_status="failed")
        workspace = FakeWorkspace(repository_id=repo_id)
        _patch_data_access(monkeypatch, repository, workspace)

        service = WorkspaceService(session=FakeSession())
        await service.request_indexing(repo_id)

        assert repository.indexing_status == "indexing"

    async def test_trigger_is_allowed_after_a_previous_successful_run(self, monkeypatch: pytest.MonkeyPatch):
        repo_id = uuid.uuid4()
        repository = FakeRepository(id=repo_id, status="ready", indexing_status="indexed")
        workspace = FakeWorkspace(repository_id=repo_id)
        _patch_data_access(monkeypatch, repository, workspace)

        service = WorkspaceService(session=FakeSession())
        await service.request_indexing(repo_id)

        assert repository.indexing_status == "indexing"

    async def test_unready_repository_still_raises_not_ready_not_duplicate(self, monkeypatch: pytest.MonkeyPatch):
        repo_id = uuid.uuid4()
        repository = FakeRepository(id=repo_id, status="cloning", indexing_status="not_started")
        workspace = FakeWorkspace(repository_id=repo_id)
        _patch_data_access(monkeypatch, repository, workspace)

        service = WorkspaceService(session=FakeSession())

        with pytest.raises(RepositoryNotReadyError):
            await service.request_indexing(repo_id)
