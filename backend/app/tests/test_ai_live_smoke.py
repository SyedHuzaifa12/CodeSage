"""One genuine end-to-end smoke test against the real Groq API.

Skip-guarded on a configured ``GROQ_API_KEY`` — never required for the
suite to pass in an environment without one (spec §17: "do not make
tests depend on a real paid LLM API"). This is the one deliberate
exception, kept to a single small test, run only when credentials are
actually available.
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio

from app.core.config import get_settings
from app.db.postgres import check_postgres_connection, get_session_factory
from app.db.qdrant import check_qdrant_connection, get_qdrant_client
from app.db.redis import check_redis_connection
from app.knowledge.qdrant_store import build_point, delete_points_by_repository, ensure_collection, upsert_points
from app.models.file import File
from app.models.knowledge_index_state import KnowledgeIndexState
from app.models.repository import Repository
from app.models.symbol import Symbol
from app.models.knowledge_chunk import KnowledgeChunk

pytestmark = pytest.mark.skipif(
    not get_settings().llm.groq_api_key, reason="GROQ_API_KEY not configured — skipping real-LLM smoke test."
)


async def _infra_available() -> bool:
    return await check_postgres_connection() and await check_qdrant_connection() and await check_redis_connection()


@pytest_asyncio.fixture
async def real_seeded_repository():
    if not await _infra_available():
        pytest.skip("Postgres/Qdrant/Redis not reachable.")

    settings = get_settings()
    session_factory = get_session_factory()
    qdrant_client = get_qdrant_client()
    await ensure_collection(qdrant_client)

    async with session_factory() as session:
        repository = Repository(
            id=uuid.uuid4(), name=f"ai-live-smoke-{uuid.uuid4().hex[:8]}", local_path="/tmp/x",
            status="ready", indexing_status="indexed",
        )
        session.add(repository)
        await session.flush()
        auth_file = File(id=uuid.uuid4(), repository_id=repository.id, path="app/auth.py", language="Python")
        session.add(auth_file)
        await session.flush()
        auth_service = Symbol(
            id=uuid.uuid4(), file_id=auth_file.id, name="AuthService", qualified_name="app.auth.AuthService",
            symbol_type="class", visibility="public", start_line=1, end_line=10,
        )
        session.add(auth_service)
        await session.flush()
        chunk_id = uuid.uuid4()
        session.add(
            KnowledgeChunk(
                id=chunk_id, repository_id=repository.id, file_id=auth_file.id, symbol_id=auth_service.id,
                chunk_index=0, chunk_type="symbol", start_line=1, end_line=10, char_count=100,
                language="Python", content_hash="a" * 64, file_content_hash="b" * 64,
                embedding_model_version=settings.llm.embedding_version,
            )
        )
        session.add(KnowledgeIndexState(id=uuid.uuid4(), repository_id=repository.id, status="ready", progress=100, total_chunks=1))
        await session.commit()

    from app.knowledge.embedding import get_embedding_provider

    provider = get_embedding_provider()
    vector = provider.embed(["class AuthService: verifies user credentials and issues session tokens"])[0]
    await upsert_points(qdrant_client, [
        build_point(
            chunk_id, vector, repository_id=repository.id, file_id=auth_file.id, symbol_id=auth_service.id,
            file_path="app/auth.py", language="Python", chunk_type="symbol", start_line=1, end_line=10,
            content_hash="a" * 64, embedding_model_version=settings.llm.embedding_version,
        )
    ])

    yield repository.id

    await delete_points_by_repository(qdrant_client, repository.id)
    async with session_factory() as session:
        db_repository = await session.get(Repository, repository.id)
        if db_repository is not None:
            await session.delete(db_repository)
            await session.commit()


async def test_real_groq_call_produces_a_grounded_answer(real_seeded_repository) -> None:
    from app.ai.services.ai_service import AIOrchestratorService

    session_factory = get_session_factory()
    async with session_factory() as session:
        service = AIOrchestratorService(session, get_settings())
        response = await service.ask(real_seeded_repository, "How is authentication implemented in this repository?")

    assert response.answer
    assert response.metadata.provider == "groq"
    assert response.verification.status in ("supported", "partially_supported", "insufficient_evidence")
    # A real fabrication (CONTRADICTED) would indicate either the model ignored
    # the grounding instructions or the verification gate has a real bug —
    # either way, that's a genuine finding this smoke test exists to catch.
    assert response.verification.status != "contradicted"
