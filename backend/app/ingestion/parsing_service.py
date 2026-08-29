"""Repository parsing pipeline — Tree-sitter symbol/import/relationship extraction.

Per CLAUDE.md §6, indexing runs as a FastAPI ``BackgroundTask`` — this
service is always invoked with its own freshly created database
session (see :func:`run_parsing_pipeline`), never the request-scoped
one, which is already closed by the time a background task actually
executes.

Pipeline, per file: language detection (already known from the file's
``language`` column, populated during Sprint 1B's scan) → Tree-sitter
parse → symbol/import/relationship extraction → persistence. A single
file's failure is logged and skipped; it never aborts the rest of the
repository (CLAUDE.md's error-isolation requirement for this sprint).
"""
from __future__ import annotations

import hashlib
import logging
import uuid
from pathlib import Path
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.postgres import get_session_factory
from app.ingestion import repository as ingestion_db
from app.ingestion.intelligence_service import RepositoryIntelligenceService
from app.ingestion.parsers import ParserManager, create_default_parser_manager
from app.ingestion.parsers.base import module_path_from_relative_path
from app.models.file import File
from app.models.repository import Repository
from app.repository import repository as repository_db

logger = logging.getLogger("codesage.ingestion.parsing_service")

RelationshipEdge = tuple[str, str, str]


class ParsingService:
    """Parses every supported file in a repository and persists the results."""

    def __init__(self, session: AsyncSession, parser_manager: Optional[ParserManager] = None) -> None:
        """Initialize the service.

        Args:
            session: The database session this parse run uses exclusively
                (its own, background-task-owned session — never shared
                with a concurrent request).
            parser_manager: Optional override, primarily for testing; a
                default Python/JS/TS/Java manager is used otherwise.
        """
        self._session = session
        self._parser_manager = parser_manager or create_default_parser_manager()

    async def parse_repository(self, repository_id: uuid.UUID) -> None:
        """Parse every supported file in a repository and persist the results.

        Updates ``Repository.indexing_status``/``indexing_progress``
        throughout so progress is visible via ``GET /repositories/{id}``
        while this runs in the background.

        Args:
            repository_id: The repository to parse.
        """
        repository = await repository_db.get_by_id(self._session, repository_id)
        if repository is None:
            logger.error("Cannot index repository %s: repository not found", repository_id)
            return

        files = await ingestion_db.list_files(self._session, repository_id)
        total_files = len(files)
        parsed_count = 0
        failed_count = 0
        skipped_count = 0
        all_relationships: set[RelationshipEdge] = set()

        logger.info("Indexing started for repository %s (%d files)", repository_id, total_files)

        for index, file_row in enumerate(files, start=1):
            extension = Path(file_row.path).suffix.lower()
            if not self._parser_manager.supports(extension):
                skipped_count += 1
            else:
                try:
                    relationships = await self._parse_single_file(repository, file_row, extension)
                    all_relationships.update(relationships)
                    parsed_count += 1
                except Exception as exc:  # noqa: BLE001 - isolate this file, keep indexing the rest
                    failed_count += 1
                    logger.error("Failed to parse '%s' in repository %s: %s", file_row.path, repository_id, exc)

            repository.indexing_progress = int(index / total_files * 100) if total_files else 100
            await repository_db.save(self._session, repository)
            logger.info(
                "Parsed %s (%d/%d, %d%%)", file_row.path, index, total_files, repository.indexing_progress
            )

        await ingestion_db.replace_relationships(self._session, repository_id, list(all_relationships))

        repository.indexing_status = "indexed"
        repository.indexing_progress = 100
        repository.error_message = (
            f"{failed_count} file(s) failed to parse; see logs for details." if failed_count else None
        )
        await repository_db.save(self._session, repository)

        logger.info(
            "Indexing complete for repository %s: parsed=%d failed=%d skipped=%d total=%d",
            repository_id,
            parsed_count,
            failed_count,
            skipped_count,
            total_files,
        )

    async def _parse_single_file(
        self, repository: Repository, file_row: File, extension: str
    ) -> list[RelationshipEdge]:
        """Parse one file and persist its symbols, returning its relationship edges.

        Args:
            repository: The owning repository (for its local clone path).
            file_row: The file to parse.
            extension: The file's lowercased extension (already confirmed supported).

        Returns:
            This file's relationship edges as ``(source, target, type)``
            tuples, to be merged into the repository-wide relationship set.

        Raises:
            OSError: If the file cannot be read from disk.
        """
        absolute_path = Path(repository.local_path) / file_row.path
        source_bytes = absolute_path.read_bytes()
        file_row.content_hash = hashlib.sha256(source_bytes).hexdigest()
        await ingestion_db.save_file(self._session, file_row)

        parser = self._parser_manager.get_parser_for_extension(extension)
        module_path = module_path_from_relative_path(file_row.path)
        parse_output = parser.parse(source_bytes, module_path)

        await ingestion_db.replace_symbols_for_file(self._session, file_row.id, parse_output.symbols)

        return [
            (edge.source_symbol, edge.target_symbol, edge.relationship_type) for edge in parse_output.relationships
        ]


async def run_parsing_pipeline(repository_id: uuid.UUID) -> None:
    """Background-task entry point: parse a repository using a fresh session.

    Never reuses the request-scoped session from the ``/index`` route —
    that session is closed once the endpoint returns, before this
    background task actually runs.

    Args:
        repository_id: The repository to parse.
    """
    session_factory = get_session_factory()
    async with session_factory() as session:
        try:
            service = ParsingService(session)
            await service.parse_repository(repository_id)

            # Sequential, same session/background task — no new deadlock
            # risk (see WorkspaceService.request_indexing's commit-before-
            # background-task note for the failure mode this avoids).
            intelligence_service = RepositoryIntelligenceService(session)
            await intelligence_service.analyze_repository(repository_id)

            await session.commit()
        except Exception:
            await session.rollback()
            logger.exception("Parsing pipeline crashed for repository %s", repository_id)
