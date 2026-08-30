"""Unit test for post-ranking symbol enrichment (Sprint 4).

Semantic hits carry a ``symbol_id`` from Qdrant's payload but not the
symbol's name — ``RetrievalService._enrich_missing_symbol_info``
backfills it with one batched query, bounded to the final ranked set.
"""
from __future__ import annotations

import uuid

import pytest

from app.core.config import Settings
from app.retrieval.candidates import Candidate
from app.retrieval.service import RetrievalService

REPO = uuid.uuid4()


class _FakeSymbol:
    def __init__(self, id_: uuid.UUID, name: str, qualified_name: str, symbol_type: str) -> None:
        self.id = id_
        self.name = name
        self.qualified_name = qualified_name
        self.symbol_type = symbol_type


async def test_enriches_only_candidates_missing_a_symbol_name(monkeypatch: pytest.MonkeyPatch) -> None:
    symbol_id = uuid.uuid4()
    already_named_id = uuid.uuid4()

    needs_enrichment = Candidate(
        dedup_key="a", repository_id=REPO, file_id=uuid.uuid4(), file_path="a.py", symbol_id=symbol_id,
    )
    already_named = Candidate(
        dedup_key="b", repository_id=REPO, file_id=uuid.uuid4(), file_path="b.py",
        symbol_id=already_named_id, symbol_name="AlreadyKnown",
    )

    calls: list[list[uuid.UUID]] = []

    async def fake_get_symbols_by_ids(session, symbol_ids):
        calls.append(list(symbol_ids))
        return {symbol_id: _FakeSymbol(symbol_id, "AuthService", "app.auth.AuthService", "class")}

    import app.retrieval.service as service_module

    monkeypatch.setattr(service_module, "get_symbols_by_ids", fake_get_symbols_by_ids)

    service = RetrievalService(session=None, settings=Settings())
    await service._enrich_missing_symbol_info([needs_enrichment, already_named])

    assert calls == [[symbol_id]]  # never asked to re-resolve the already-named one
    assert needs_enrichment.symbol_name == "AuthService"
    assert needs_enrichment.qualified_name == "app.auth.AuthService"
    assert already_named.symbol_name == "AlreadyKnown"  # untouched


async def test_no_op_when_nothing_needs_enrichment(monkeypatch: pytest.MonkeyPatch) -> None:
    called = False

    async def fail_if_called(session, symbol_ids):
        nonlocal called
        called = True

    import app.retrieval.service as service_module

    monkeypatch.setattr(service_module, "get_symbols_by_ids", fail_if_called)

    service = RetrievalService(session=None, settings=Settings())
    candidate = Candidate(dedup_key="a", repository_id=REPO, file_id=uuid.uuid4(), file_path="a.py")
    await service._enrich_missing_symbol_info([candidate])

    assert called is False
