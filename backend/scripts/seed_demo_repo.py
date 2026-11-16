"""Seed (or rebuild) the public, read-only demo repository (ADR-027).

The demo is a famous open-source repository, indexed once under a system
account and flagged ``is_demo``: every visitor — guest or member — can
explore it and ask questions without using up their one free repository,
and only an admin can modify it. It is never touched by guest cleanup.

Usage (from the ``backend/`` directory, with Postgres/Redis/Qdrant running
and ``alembic upgrade head`` applied; needs internet access to clone):

    python -m scripts.seed_demo_repo                  # expressjs/express
    python -m scripts.seed_demo_repo --force          # delete and rebuild it
    python -m scripts.seed_demo_repo --url https://github.com/pallets/flask --name Flask

Idempotent: if the demo already exists and is fully indexed, it does
nothing. It runs the same parse -> intelligence -> knowledge pipeline the
indexing worker runs, in this process, so no Celery worker is needed.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import time
import uuid

from sqlalchemy import select

from app.core.config import get_settings
from app.db.postgres import close_postgres_connection, get_session_factory
from app.db.qdrant import close_qdrant_connection, get_qdrant_client
from app.db.redis import close_redis_connection
from app.ingestion.parsing_service import run_parsing_pipeline
from app.ingestion.service import WorkspaceService
from app.knowledge.qdrant_store import ensure_collection
from app.models.repository import Repository
from app.models.user import User
from app.repository import repository as repository_db
from app.repository.schemas import RepositoryCreateRequest
from app.repository.service import RepositoryService

DEFAULT_URL = "https://github.com/expressjs/express"
DEFAULT_NAME = "Express"
# An underscore is not a legal GitHub login character, so no real GitHub account can ever
# share this login (and thereby inherit admin rights if it were ever listed as an admin).
OWNER_LOGIN = "codesage_demo"


async def get_or_create_owner(session) -> User:
    """The system account that owns demo repositories."""
    owner = (
        await session.execute(select(User).where(User.kind == "user", User.github_login == OWNER_LOGIN))
    ).scalar_one_or_none()
    if owner is None:
        owner = User(id=uuid.uuid4(), kind="user", github_login=OWNER_LOGIN, display_name="CodeSage Demo")
        session.add(owner)
        await session.flush()
    return owner


async def find_demo(session, url: str) -> Repository | None:
    return (
        await session.execute(select(Repository).where(Repository.is_demo.is_(True), Repository.github_url == url))
    ).scalar_one_or_none()


async def seed(url: str, name: str, force: bool) -> int:
    settings = get_settings()
    await ensure_collection(get_qdrant_client())
    factory = get_session_factory()

    async with factory() as session:
        existing = await find_demo(session, url)
        if existing is not None and existing.indexing_status == "indexed" and not force:
            print(f"Demo '{existing.name}' already exists and is indexed ({existing.id}). Use --force to rebuild.")
            return 0

        service = RepositoryService(session=session, settings=settings, workspace_service=WorkspaceService(session))
        if existing is not None:
            print(f"Removing the previous demo ({existing.id}) ...")
            await service.delete_repository(existing.id)  # also clears its Qdrant vectors and clone
            await session.commit()

        owner = await get_or_create_owner(session)
        print(f"Cloning and scanning {url} ...")
        started = time.perf_counter()
        repository = await service.create_repository(RepositoryCreateRequest(github_url=url, name=name), owner.id)
        repository.is_demo = True
        # Mirrors WorkspaceService.request_indexing: the pipeline's failure handler expects "indexing".
        repository.indexing_status = "indexing"
        repository.indexing_progress = 0
        repository.error_message = None
        await repository_db.save(session, repository)
        await session.commit()
        repository_id = repository.id
        print(f"Cloned in {time.perf_counter() - started:.1f}s. Indexing (parse -> intelligence -> embeddings) ...")

    started = time.perf_counter()
    await run_parsing_pipeline(repository_id)

    async with factory() as session:
        repository = await repository_db.get_by_id(session, repository_id)
        if repository is None or repository.indexing_status != "indexed":
            problem = repository.error_message if repository else "repository vanished"
            print(f"Indexing did not complete: {problem}", file=sys.stderr)
            return 1
        print(f"Done in {time.perf_counter() - started:.1f}s. Demo '{repository.name}' is live: {repository.id}")
    return 0


async def main() -> int:
    parser = argparse.ArgumentParser(description="Seed the public demo repository.")
    parser.add_argument("--url", default=DEFAULT_URL, help="Public GitHub URL to use as the demo.")
    parser.add_argument("--name", default=DEFAULT_NAME, help="Display name.")
    parser.add_argument("--force", action="store_true", help="Delete and rebuild an existing demo.")
    args = parser.parse_args()
    try:
        return await seed(args.url, args.name, args.force)
    finally:
        await close_postgres_connection()
        await close_redis_connection()
        await close_qdrant_connection()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
