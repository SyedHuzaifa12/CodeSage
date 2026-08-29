"""Language-independent parsing interface and shared extraction helpers.

Every per-language parser (``python_parser.py``, ``javascript_parser.py``,
``typescript_parser.py``, ``java_parser.py``) implements
:class:`LanguageParser`, so the parsing pipeline in
``parsing_service.py`` never branches on language — it only asks
whichever parser is registered for a file's extension.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import ClassVar, Optional, Protocol

from tree_sitter import Language, Node, Parser


@dataclass
class ExtractedSymbol:
    """A single symbol extracted from a parsed file's AST."""

    name: str
    qualified_name: str
    symbol_type: str
    visibility: str
    start_line: int
    end_line: int
    signature: Optional[str] = None
    parent_qualified_name: Optional[str] = None


@dataclass
class ExtractedImport:
    """A single import/export/module-reference extracted from a file."""

    statement: str
    module: str
    imported_names: list[str] = field(default_factory=list)
    is_relative: bool = False
    kind: str = "import"


@dataclass
class ExtractedRelationship:
    """A structural relationship directly derivable from a single file's AST.

    Scoped to what a single file's own AST can prove without
    cross-file resolution: class/interface inheritance, interface
    implementation, symbol containment, and import edges.
    """

    source_symbol: str
    target_symbol: str
    relationship_type: str


@dataclass
class ExtractedCall:
    """A single call expression found inside a function/method body.

    Raw extraction only — resolving ``callee_name`` to an actual
    symbol's qualified name (or leaving it unresolved) is Sprint 2B's
    ``RepositoryIntelligenceService`` job, done at repository level once
    every file's symbols are known. Sprint 2A's per-file parse doesn't
    have that cross-file context.
    """

    caller_qualified_name: str
    callee_name: str
    is_self_reference: bool = False


@dataclass
class ParseOutput:
    """Everything extracted from parsing a single file."""

    symbols: list[ExtractedSymbol] = field(default_factory=list)
    imports: list[ExtractedImport] = field(default_factory=list)
    relationships: list[ExtractedRelationship] = field(default_factory=list)
    calls: list[ExtractedCall] = field(default_factory=list)


class LanguageParser(Protocol):
    """Interface every per-language parser must implement."""

    language_name: str
    file_extensions: frozenset[str]

    def parse(self, source_code: bytes, module_path: str) -> ParseOutput:
        """Parse a single file's source and extract symbols/imports/relationships.

        Args:
            source_code: The raw file bytes (never modified, never executed).
            module_path: A dotted module path derived from the file's
                repository-relative path (e.g. ``app.models.repository``),
                used as the root prefix for every qualified name.

        Returns:
            Everything extracted from this one file.
        """
        ...


def module_path_from_relative_path(relative_path: str) -> str:
    """Derive a dotted module path from a repository-relative file path.

    Args:
        relative_path: A POSIX-style path relative to the repository
            root, e.g. ``app/models/repository.py``.

    Returns:
        A dotted path with the extension stripped, e.g.
        ``app.models.repository``.
    """
    without_extension = relative_path.rsplit(".", 1)[0] if "." in relative_path.rsplit("/", 1)[-1] else relative_path
    return without_extension.replace("/", ".")


def iter_nodes_of_type(node: Node, *node_types: str, stop_at: frozenset[str] = frozenset()) -> "list[Node]":
    """Recursively collect every descendant node matching any of the given types.

    Shared across all language parsers so none of them re-implements
    its own tree-walking loop.

    Args:
        node: The subtree root to search from (inclusive).
        *node_types: One or more Tree-sitter node type names to match.
        stop_at: Node types whose subtrees should not be descended into
            (e.g. nested function bodies, to avoid picking up locals).

    Returns:
        Matching nodes in document order.
    """
    matches: list[Node] = []
    if node.type in node_types:
        matches.append(node)
    if node.type in stop_at and node.type not in node_types:
        return matches
    for child in node.children:
        matches.extend(iter_nodes_of_type(child, *node_types, stop_at=stop_at))
    return matches


def direct_children_of_type(node: Node, *node_types: str) -> "list[Node]":
    """Return only the immediate children of a node matching given types.

    Args:
        node: The parent node.
        *node_types: One or more Tree-sitter node type names to match.

    Returns:
        Matching direct children, in document order.
    """
    return [child for child in node.children if child.type in node_types]


def node_text(node: Optional[Node], source_code: bytes) -> str:
    """Safely decode a node's source text.

    Args:
        node: The AST node (or ``None``).
        source_code: The full file's source bytes.

    Returns:
        The decoded UTF-8 text, or an empty string if ``node`` is ``None``.
    """
    if node is None:
        return ""
    return source_code[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


class BaseTreeSitterParser(ABC):
    """Shared Tree-sitter setup and parse-orchestration for all language parsers.

    Subclasses provide the grammar and language-specific extraction
    logic; this base class owns constructing the Tree-sitter
    ``Parser``/``Language`` once (lazily, via the manager) and running
    the parse itself.
    """

    language_name: ClassVar[str]
    file_extensions: ClassVar[frozenset[str]]

    def __init__(self) -> None:
        """Load this parser's Tree-sitter grammar and construct its parser."""
        self._language: Language = self._load_language()
        self._parser = Parser(self._language)

    @abstractmethod
    def _load_language(self) -> Language:
        """Construct this parser's Tree-sitter ``Language``.

        Returns:
            The loaded grammar, wrapped as a :class:`tree_sitter.Language`.
        """
        raise NotImplementedError

    @abstractmethod
    def _extract(self, root_node: Node, source_code: bytes, module_path: str) -> ParseOutput:
        """Walk the parsed tree and extract symbols/imports/relationships.

        Args:
            root_node: The AST root produced by this parser's grammar.
            source_code: The full file's source bytes.
            module_path: Dotted module path used as the qualified-name root.

        Returns:
            Everything extracted from this file.
        """
        raise NotImplementedError

    def parse(self, source_code: bytes, module_path: str) -> ParseOutput:
        """Parse a single file's source and extract symbols/imports/relationships.

        Args:
            source_code: The raw file bytes.
            module_path: Dotted module path used as the qualified-name root.

        Returns:
            Everything extracted from this file.
        """
        tree = self._parser.parse(source_code)
        return self._extract(tree.root_node, source_code, module_path)
