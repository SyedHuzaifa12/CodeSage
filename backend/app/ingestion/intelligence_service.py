"""Repository Intelligence Builder — Sprint 2B.

Transforms Sprint 2A's already-persisted symbols/imports/relationships
into repository-level intelligence: statistics, an import/dependency
graph, circular-dependency and orphan-file detection, a resolved call
graph, and a pure rule-based repository summary.

Per CLAUDE.md §6, this stays inside the Ingestion module (no new
top-level module is introduced) and runs as a background-task step
chained directly after ``ParsingService.parse_repository`` completes,
using that same background task's own session (see
``parsing_service.run_parsing_pipeline``) — sequential, not a second
concurrent task, so it carries no new deadlock risk.

Everything here is offline analysis over data Ingestion already parsed
and persisted: no Knowledge Graph construction, no embeddings, no
retrieval, no LLM calls, and no query-time graph traversal or ranking.
The two new relationship types this module adds (``depends_on`` for
resolved internal imports, ``calls`` for the resolved call graph) are
additional *layers* of the same flat relationships table Sprint 2A
already writes to (CLAUDE.md §8 documents four such layers: Call Graph,
Import Graph, Dependency Graph, Symbol Relationships) — persisted via a
type-scoped replace so Sprint 2A's own extends/implements/belongs_to/
imports rows are never touched.
"""
from __future__ import annotations

import logging
import posixpath
import uuid
from collections import Counter
from pathlib import Path
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.ingestion import repository as ingestion_db
from app.ingestion.exceptions import IntelligenceNotFoundError
from app.ingestion.parsers import ParserManager, create_default_parser_manager
from app.ingestion.parsers.base import module_path_from_relative_path
from app.models.file import File
from app.models.relationship import Relationship
from app.models.repository import Repository
from app.models.repository_intelligence import RepositoryIntelligence
from app.models.symbol import Symbol
from app.repository import repository as repository_db
from app.repository.exceptions import RepositoryNotFoundError

logger = logging.getLogger("codesage.ingestion.intelligence_service")

DependencyEdge = tuple[str, str]

_INHERITANCE_RELATIONSHIP_TYPES = frozenset({"extends", "implements"})

_ENTRY_POINT_FILENAMES = frozenset(
    {
        "main.py", "__main__.py", "__init__.py", "app.py", "manage.py", "setup.py", "wsgi.py", "asgi.py",
        "index.js", "index.jsx", "index.ts", "index.tsx", "main.js", "main.ts", "server.js", "server.ts",
        "Main.java", "Application.java",
    }
)

_JS_RESOLUTION_SUFFIXES = ("", ".js", ".jsx", ".ts", ".tsx", "/index.js", "/index.jsx", "/index.ts", "/index.tsx")

_MAX_SUMMARY_ITEMS = 10


class RepositoryIntelligenceService:
    """Builds and persists a repository's post-parsing intelligence."""

    def __init__(self, session: AsyncSession, parser_manager: Optional[ParserManager] = None) -> None:
        """Initialize the service.

        Args:
            session: The database session this analysis run uses
                exclusively (shared with the parsing pipeline step that
                precedes it — see module docstring).
            parser_manager: Optional override, primarily for testing; a
                default Python/JS/TS/Java manager is used otherwise.
        """
        self._session = session
        self._parser_manager = parser_manager or create_default_parser_manager()

    async def analyze_repository(self, repository_id: uuid.UUID) -> RepositoryIntelligence:
        """Run the full intelligence pipeline for a repository and persist the result.

        Args:
            repository_id: The repository to analyze; must already be
                fully parsed (Sprint 2A) — symbols/relationships are
                read as-is, never re-derived from scratch here except
                for calls (which Sprint 2A's parse never persisted).

        Returns:
            The persisted (or updated) intelligence row.
        """
        intelligence = await ingestion_db.get_intelligence(self._session, repository_id)
        if intelligence is None:
            intelligence = await ingestion_db.create_intelligence(
                self._session, RepositoryIntelligence(repository_id=repository_id, status="pending")
            )

        intelligence.status = "analyzing"
        intelligence.progress = 0
        intelligence.error_message = None
        await ingestion_db.save_intelligence(self._session, intelligence)
        logger.info("Repository intelligence %s transitioning to ANALYZING for repository %s", intelligence.id, repository_id)

        try:
            repository = await repository_db.get_by_id(self._session, repository_id)
            if repository is None:
                raise ValueError(f"Repository '{repository_id}' was not found.")

            files = await ingestion_db.list_files(self._session, repository_id)
            symbols = await ingestion_db.list_symbols_for_repository(self._session, repository_id)
            relationships = await ingestion_db.list_relationships(self._session, repository_id)
            logger.info(
                "Analyzing repository %s: %d files, %d symbols, %d relationships",
                repository_id, len(files), len(symbols), len(relationships),
            )

            dependency_graph = self._resolve_import_graph(files, symbols, relationships)
            intelligence.progress = 25
            await ingestion_db.save_intelligence(self._session, intelligence)

            cycles = self._detect_cycles(dependency_graph)
            orphans = self._detect_orphans(files, dependency_graph)
            logger.info(
                "Dependency analysis for repository %s: %d resolved edges, %d cycles, %d orphan files",
                repository_id, sum(len(v) for v in dependency_graph.values()), len(cycles), len(orphans),
            )
            await ingestion_db.replace_relationships_of_type(
                self._session, repository_id, "depends_on",
                [(source, target) for source, targets in dependency_graph.items() for target in targets],
            )
            intelligence.progress = 50
            await ingestion_db.save_intelligence(self._session, intelligence)

            resolved_calls = self._build_call_graph(repository, files, symbols)
            await ingestion_db.replace_relationships_of_type(self._session, repository_id, "calls", resolved_calls)
            logger.info("Call graph for repository %s: %d resolved calls", repository_id, len(resolved_calls))
            intelligence.progress = 75
            await ingestion_db.save_intelligence(self._session, intelligence)

            statistics = self._compute_statistics(symbols, relationships, len(resolved_calls))
            workspace = await ingestion_db.get_workspace(self._session, repository_id)
            summary = self._generate_summary(files, symbols, dependency_graph, cycles, workspace)

            for field_name, value in statistics.items():
                setattr(intelligence, field_name, value)
            intelligence.circular_dependencies = cycles
            intelligence.orphan_files = orphans
            for field_name, value in summary.items():
                setattr(intelligence, field_name, value)

            intelligence.status = "ready"
            intelligence.progress = 100
            await ingestion_db.save_intelligence(self._session, intelligence)
            logger.info("Repository intelligence %s transitioned to READY for repository %s", intelligence.id, repository_id)
        except Exception as exc:  # noqa: BLE001 -- record failure, never crash the calling background task
            intelligence.status = "failed"
            intelligence.error_message = str(exc)
            await ingestion_db.save_intelligence(self._session, intelligence)
            logger.exception("Repository intelligence analysis failed for repository %s", repository_id)

        return intelligence

    # -- Statistics ---------------------------------------------------

    @staticmethod
    def _compute_statistics(symbols: list[Symbol], relationships: list[Relationship], total_calls: int) -> dict:
        """Aggregate pure counts from already-parsed symbols and relationships.

        Args:
            symbols: Every symbol row across the repository.
            relationships: Every relationship row across the repository
                (all types — filtered here by type as needed).
            total_calls: Count of resolved call-graph edges (computed
                separately since it isn't derivable from ``symbols``).

        Returns:
            A flat dict matching :class:`RepositoryIntelligence`'s
            statistics column names, ready for ``setattr``.
        """
        symbol_type_counts = Counter(symbol.symbol_type for symbol in symbols)
        relationship_type_counts = Counter(relationship.relationship_type for relationship in relationships)
        total_imports = relationship_type_counts["imports"]

        return {
            "total_symbols": len(symbols),
            "total_classes": symbol_type_counts["class"],
            "total_interfaces": symbol_type_counts["interface"],
            "total_enums": symbol_type_counts["enum"],
            "total_functions": symbol_type_counts["function"],
            "total_methods": symbol_type_counts["method"],
            "total_variables": symbol_type_counts["variable"],
            "total_namespaces": symbol_type_counts["namespace"],
            "total_imports": total_imports,
            "total_calls": total_calls,
            "inheritance_count": sum(relationship_type_counts[t] for t in _INHERITANCE_RELATIONSHIP_TYPES),
            "dependency_count": total_imports,
        }

    # -- Import / dependency resolution --------------------------------

    def _resolve_import_graph(
        self, files: list[File], symbols: list[Symbol], relationships: list[Relationship]
    ) -> dict[str, set[str]]:
        """Resolve every ``imports`` edge that targets another file *within this repository*.

        Resolution is language-specific because each ecosystem encodes
        module references differently (Python dotted paths, JS/TS
        relative file paths, Java fully-qualified class names). Edges
        that can't be resolved to a known internal file (third-party
        packages, unresolvable bare relative imports, wildcard Java
        imports) are simply dropped from this graph — they remain
        exactly as Sprint 2A persisted them in the untouched ``imports``
        relationship rows.

        Args:
            files: Every file row for the repository.
            symbols: Every symbol row for the repository (used to build
                the Java class/interface/enum qualified-name index).
            relationships: Every relationship row for the repository
                (only ``relationship_type == "imports"`` rows are used).

        Returns:
            Adjacency map of source file ``module_path`` to the set of
            resolved target file ``module_path`` values.
        """
        module_path_to_file = {module_path_from_relative_path(f.path): f for f in files}
        file_path_to_file = {f.path: f for f in files}
        file_by_id = {f.id: f for f in files}
        java_type_index: dict[str, File] = {
            symbol.qualified_name: file_by_id[symbol.file_id]
            for symbol in symbols
            if symbol.symbol_type in ("class", "interface", "enum") and symbol.file_id in file_by_id
        }

        graph: dict[str, set[str]] = {}
        for relationship in relationships:
            if relationship.relationship_type != "imports":
                continue
            source_file = module_path_to_file.get(relationship.source_symbol)
            if source_file is None or not source_file.language:
                continue

            target_module_path = self._resolve_import_target(
                source_file, relationship.target_symbol, module_path_to_file, file_path_to_file, java_type_index
            )
            if target_module_path and target_module_path != relationship.source_symbol:
                graph.setdefault(relationship.source_symbol, set()).add(target_module_path)

        return graph

    def _resolve_import_target(
        self,
        source_file: File,
        target: str,
        module_path_to_file: dict[str, File],
        file_path_to_file: dict[str, File],
        java_type_index: dict[str, File],
    ) -> Optional[str]:
        """Dispatch a single import edge to its language-specific resolver.

        Args:
            source_file: The importing file (its ``language`` selects
                the resolution strategy).
            target: The raw import target string, as persisted on the
                ``imports`` relationship row.
            module_path_to_file: Every known internal module_path (Python).
            file_path_to_file: Every known internal file path (JS/TS).
            java_type_index: Every known class/interface/enum qualified_name (Java).

        Returns:
            The resolved internal module_path, or ``None`` if
            unresolvable / external.
        """
        if source_file.language == "Python":
            return self._resolve_python_import(module_path_from_relative_path(source_file.path), target, module_path_to_file)
        if source_file.language in ("JavaScript", "TypeScript"):
            return self._resolve_js_import(source_file, target, file_path_to_file)
        if source_file.language == "Java":
            return self._resolve_java_import(target, java_type_index)
        return None

    @staticmethod
    def _resolve_python_import(
        importer_module_path: str, target: str, module_path_to_file: dict[str, File]
    ) -> Optional[str]:
        """Resolve one Python import's target module string to an internal module_path.

        Args:
            importer_module_path: The importing file's own module_path
                (used to anchor relative imports).
            target: The raw module string captured by the parser — an
                absolute dotted path, or a relative-import string
                (leading dots, e.g. ``".foo"``/``".."``).
            module_path_to_file: Every known internal module_path.

        Returns:
            The resolved internal module_path, or ``None`` if the
            import refers to an external package or an unresolvable
            bare relative import (``from . import x`` — the imported
            name itself isn't persisted, so there's nothing to anchor
            the target to).
        """
        if target.startswith("."):
            dots = len(target) - len(target.lstrip("."))
            remainder = target[dots:]
            base = importer_module_path.rsplit(".", 1)[0] if "." in importer_module_path else ""
            for _ in range(dots - 1):
                base = base.rsplit(".", 1)[0] if "." in base else ""
            if not remainder:
                return None
            candidate = f"{base}.{remainder}" if base else remainder
        else:
            candidate = target

        if candidate in module_path_to_file:
            return candidate
        package_init = f"{candidate}.__init__"
        if package_init in module_path_to_file:
            return package_init
        return None

    @staticmethod
    def _resolve_js_import(source_file: File, target: str, file_path_to_file: dict[str, File]) -> Optional[str]:
        """Resolve one JS/TS import specifier to an internal file's module_path.

        Args:
            source_file: The importing file (used for its directory,
                since JS/TS resolution is relative-path based).
            target: The raw import specifier (e.g. ``"./utils/helper"``,
                ``"react"``).
            file_path_to_file: Every known internal file, keyed by its
                repository-relative path.

        Returns:
            The resolved internal module_path, or ``None`` for a bare
            (non-relative) specifier — those are external packages by
            convention and unresolvable to a single file without a
            module-resolution algorithm this sprint doesn't implement.
        """
        if not target.startswith("."):
            return None
        importer_dir = posixpath.dirname(source_file.path)
        joined = posixpath.normpath(posixpath.join(importer_dir, target))
        for suffix in _JS_RESOLUTION_SUFFIXES:
            candidate_path = f"{joined}{suffix}"
            matched = file_path_to_file.get(candidate_path)
            if matched is not None:
                return module_path_from_relative_path(matched.path)
        return None

    @staticmethod
    def _resolve_java_import(target: str, type_qualified_names: dict[str, File]) -> Optional[str]:
        """Resolve one Java import to an internal type's owning file.

        Args:
            target: The raw import target — a fully-qualified class
                name, a static-member import, or a ``.*`` wildcard.
            type_qualified_names: Every known class/interface/enum
                qualified_name mapped to its owning file.

        Returns:
            The resolved internal module_path, or ``None`` for a
            wildcard package import (unresolvable to one file) or an
            external/JDK type.
        """
        if target.endswith(".*"):
            return None
        matched = type_qualified_names.get(target)
        if matched is None and "." in target:
            matched = type_qualified_names.get(target.rsplit(".", 1)[0])
        return module_path_from_relative_path(matched.path) if matched is not None else None

    # -- Circular dependency + orphan detection ------------------------

    @staticmethod
    def _detect_cycles(graph: dict[str, set[str]]) -> list[list[str]]:
        """Find every cycle in the resolved internal import graph.

        Iterative white/gray/black DFS (not recursive) so this scales
        to large repositories without risking Python's recursion limit
        on deep import chains.

        Args:
            graph: Adjacency map of module_path to its resolved
                internal import targets.

        Returns:
            Each detected cycle as an ordered list of module_paths,
            starting and ending at the repeated node.
        """
        nodes: set[str] = set(graph.keys())
        for targets in graph.values():
            nodes.update(targets)

        WHITE, GRAY, BLACK = 0, 1, 2
        color = dict.fromkeys(nodes, WHITE)
        cycles: list[list[str]] = []

        for start in sorted(nodes):
            if color[start] != WHITE:
                continue
            path = [start]
            frames = [(start, sorted(graph.get(start, ())), 0)]
            color[start] = GRAY
            while frames:
                node, neighbors, index = frames[-1]
                if index >= len(neighbors):
                    color[node] = BLACK
                    path.pop()
                    frames.pop()
                    continue
                frames[-1] = (node, neighbors, index + 1)
                neighbor = neighbors[index]
                state = color.get(neighbor, WHITE)
                if state == WHITE:
                    color[neighbor] = GRAY
                    path.append(neighbor)
                    frames.append((neighbor, sorted(graph.get(neighbor, ())), 0))
                elif state == GRAY:
                    cycle_start = path.index(neighbor)
                    cycles.append(path[cycle_start:] + [neighbor])

        return cycles

    @staticmethod
    def _detect_orphans(files: list[File], dependency_graph: dict[str, set[str]]) -> list[str]:
        """Find parsed files that no other internal file resolves-imports into.

        Args:
            files: Every file row for the repository.
            dependency_graph: The resolved internal import adjacency map.

        Returns:
            Repository-relative paths of orphan files — parsed, but
            never a resolved import target, and not a well-known
            entry-point filename.
        """
        all_targets: set[str] = set()
        for targets in dependency_graph.values():
            all_targets.update(targets)

        orphans: list[str] = []
        for file_row in files:
            if not file_row.language:
                continue
            if Path(file_row.path).name in _ENTRY_POINT_FILENAMES:
                continue
            if module_path_from_relative_path(file_row.path) not in all_targets:
                orphans.append(file_row.path)
        return sorted(orphans)

    # -- Call graph -----------------------------------------------------

    def _build_call_graph(
        self, repository: Repository, files: list[File], symbols: list[Symbol]
    ) -> list[DependencyEdge]:
        """Re-parse every supported file to resolve caller -> callee call edges.

        Sprint 2A's per-file parse extracts ``ExtractedCall`` values but
        never persists them (no repository-wide symbol context was
        available at that point). This re-parses from disk purely to
        recover that per-file call data, then resolves each call against
        the already-persisted, repository-wide symbol set: self-reference
        calls (``self.x()``/``this.x()``) resolve against the caller's
        own enclosing class's methods; bare calls resolve against the
        caller's *own file's* top-level functions only — cross-file bare
        calls are out of scope (documented limitation).

        Args:
            repository: The owning repository (for its local clone path).
            files: Every file row for the repository.
            symbols: Every symbol row for the repository.

        Returns:
            Deduplicated ``(caller_qualified_name, callee_qualified_name)``
            pairs — resolved edges only; unresolved calls are dropped.
        """
        symbols_by_qualified_name = {symbol.qualified_name: symbol for symbol in symbols}
        top_level_functions_by_file: dict[uuid.UUID, dict[str, Symbol]] = {}
        methods_by_parent_id: dict[uuid.UUID, dict[str, Symbol]] = {}
        for symbol in symbols:
            if symbol.symbol_type == "function" and symbol.parent_symbol_id is None:
                top_level_functions_by_file.setdefault(symbol.file_id, {})[symbol.name] = symbol
            elif symbol.symbol_type == "method" and symbol.parent_symbol_id is not None:
                methods_by_parent_id.setdefault(symbol.parent_symbol_id, {})[symbol.name] = symbol

        resolved: set[DependencyEdge] = set()
        for file_row in files:
            extension = Path(file_row.path).suffix.lower()
            parser = self._parser_manager.get_parser_for_extension(extension)
            if parser is None:
                continue
            try:
                source_bytes = (Path(repository.local_path) / file_row.path).read_bytes()
            except OSError as exc:
                logger.warning("Skipping call-graph extraction for '%s': %s", file_row.path, exc)
                continue

            module_path = module_path_from_relative_path(file_row.path)
            try:
                parse_output = parser.parse(source_bytes, module_path)
            except Exception as exc:  # noqa: BLE001 - one file's failure must not abort the graph
                logger.warning("Failed to re-parse '%s' for call graph: %s", file_row.path, exc)
                continue

            for call in parse_output.calls:
                caller = symbols_by_qualified_name.get(call.caller_qualified_name)
                if caller is None:
                    continue
                target: Optional[Symbol] = None
                if call.is_self_reference and caller.parent_symbol_id is not None:
                    target = methods_by_parent_id.get(caller.parent_symbol_id, {}).get(call.callee_name)
                elif not call.is_self_reference:
                    target = top_level_functions_by_file.get(caller.file_id, {}).get(call.callee_name)
                if target is not None:
                    resolved.add((caller.qualified_name, target.qualified_name))

        return sorted(resolved)

    # -- Summary ----------------------------------------------------------

    @staticmethod
    def _generate_summary(
        files: list[File],
        symbols: list[Symbol],
        dependency_graph: dict[str, set[str]],
        cycles: list[list[str]],
        workspace,
    ) -> dict:
        """Produce a pure rule-based repository summary — no LLM involved.

        Args:
            files: Every file row for the repository.
            symbols: Every symbol row for the repository.
            dependency_graph: The resolved internal import adjacency map.
            cycles: Already-detected circular dependencies.
            workspace: The repository's workspace row (for its
                already-computed ``language_distribution`` — Sprint 1B
                did this work already, so it's reused rather than
                recomputed).

        Returns:
            A flat dict matching :class:`RepositoryIntelligence`'s
            summary column names, ready for ``setattr``.
        """
        languages = dict(workspace.language_distribution) if workspace is not None else {}

        entry_points = sorted(
            file_row.path for file_row in files if Path(file_row.path).name in _ENTRY_POINT_FILENAMES
        )

        symbol_count_by_file_id = Counter(symbol.file_id for symbol in symbols)
        largest_modules = [
            {"path": file_row.path, "symbol_count": symbol_count_by_file_id[file_row.id]}
            for file_row in sorted(files, key=lambda f: symbol_count_by_file_id[f.id], reverse=True)
            if symbol_count_by_file_id[file_row.id] > 0
        ][:_MAX_SUMMARY_ITEMS]

        in_degree: Counter = Counter()
        for targets in dependency_graph.values():
            for target in targets:
                in_degree[target] += 1
        dependency_hotspots = [
            {"module_path": module_path, "incoming_dependencies": count}
            for module_path, count in in_degree.most_common(_MAX_SUMMARY_ITEMS)
        ]

        architecture_hints: list[str] = []
        if len(languages) > 1:
            architecture_hints.append("Multi-language repository")
        if any(_looks_like_test_path(file_row.path) for file_row in files):
            architecture_hints.append("Contains a test suite")
        if cycles:
            architecture_hints.append("Has circular dependencies between modules")
        if entry_points:
            architecture_hints.append("Has one or more identifiable application entry points")
        if any(Path(f.path).name.lower() in ("dockerfile", "docker-compose.yml", "docker-compose.yaml") for f in files):
            architecture_hints.append("Containerized (Docker configuration present)")

        return {
            "languages": languages,
            "architecture_hints": architecture_hints,
            "entry_points": entry_points,
            "largest_modules": largest_modules,
            "dependency_hotspots": dependency_hotspots,
        }

    # -- Read queries (API / DevTools) -----------------------------------

    async def _get_ready_intelligence(self, repository_id: uuid.UUID) -> RepositoryIntelligence:
        """Fetch a repository's intelligence row, requiring the repository to exist.

        Args:
            repository_id: The repository's UUID.

        Returns:
            The intelligence row (any status — callers decide how to
            handle ``pending``/``analyzing``/``failed``).

        Raises:
            RepositoryNotFoundError: If no repository has that id.
            IntelligenceNotFoundError: If the repository has never been analyzed.
        """
        repository = await repository_db.get_by_id(self._session, repository_id)
        if repository is None:
            raise RepositoryNotFoundError(f"Repository '{repository_id}' was not found.")
        intelligence = await ingestion_db.get_intelligence(self._session, repository_id)
        if intelligence is None:
            raise IntelligenceNotFoundError(
                f"Repository '{repository_id}' has not been analyzed yet — run indexing first."
            )
        return intelligence

    async def get_intelligence(self, repository_id: uuid.UUID) -> RepositoryIntelligence:
        """Fetch a repository's full intelligence row.

        Args:
            repository_id: The repository's UUID.

        Returns:
            The intelligence row.
        """
        return await self._get_ready_intelligence(repository_id)

    async def get_call_graph(self, repository_id: uuid.UUID) -> tuple[list[str], list[DependencyEdge]]:
        """Fetch the resolved call graph as nodes and edges.

        Args:
            repository_id: The repository's UUID.

        Returns:
            A ``(nodes, edges)`` tuple — nodes are every qualified name
            appearing in at least one edge; edges are
            ``(caller_qualified_name, callee_qualified_name)`` pairs.
        """
        await self._get_ready_intelligence(repository_id)
        relationships = await ingestion_db.list_relationships(self._session, repository_id, "calls")
        edges = [(r.source_symbol, r.target_symbol) for r in relationships]
        nodes = sorted({node for edge in edges for node in edge})
        return nodes, edges

    async def get_dependency_graph(
        self, repository_id: uuid.UUID
    ) -> tuple[list[str], list[DependencyEdge], list[list[str]], list[str]]:
        """Fetch the resolved import/dependency graph plus its analysis results.

        Args:
            repository_id: The repository's UUID.

        Returns:
            A ``(nodes, edges, circular_dependencies, orphan_files)`` tuple.
        """
        intelligence = await self._get_ready_intelligence(repository_id)
        relationships = await ingestion_db.list_relationships(self._session, repository_id, "depends_on")
        edges = [(r.source_symbol, r.target_symbol) for r in relationships]
        nodes = sorted({node for edge in edges for node in edge})
        return nodes, edges, intelligence.circular_dependencies, intelligence.orphan_files

    async def get_symbols(self, repository_id: uuid.UUID) -> list[tuple[Symbol, str]]:
        """Fetch every symbol for a repository, paired with its owning file's path.

        Args:
            repository_id: The repository's UUID.

        Returns:
            ``(symbol, file_path)`` pairs, for the Symbol Explorer.
        """
        await self._get_ready_intelligence(repository_id)
        symbols = await ingestion_db.list_symbols_for_repository(self._session, repository_id)
        files = await ingestion_db.list_files(self._session, repository_id)
        file_path_by_id = {f.id: f.path for f in files}
        return [(symbol, file_path_by_id.get(symbol.file_id, "")) for symbol in symbols]


def _looks_like_test_path(path: str) -> bool:
    """Heuristically detect whether a file path belongs to a test suite.

    Args:
        path: A repository-relative file path.

    Returns:
        ``True`` if the path or filename matches common test-file
        naming conventions across Python/JS/TS/Java.
    """
    lowered = path.lower()
    name = Path(lowered).name
    return (
        "/test/" in f"/{lowered}" or "/tests/" in f"/{lowered}" or "/__tests__/" in f"/{lowered}"
        or name.startswith("test_") or name.endswith("_test.py")
        or name.endswith(".test.js") or name.endswith(".test.ts") or name.endswith(".spec.js") or name.endswith(".spec.ts")
        or name.endswith("test.java")
    )
