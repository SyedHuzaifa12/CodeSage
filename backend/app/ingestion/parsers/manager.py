"""Tree-sitter Parser Manager — registration, lazy loading, and lifecycle.

Language-independent: the manager knows nothing about Python/JS/TS/Java
specifically — it dispatches to whichever :class:`LanguageParser` is
registered for a file's extension, constructing each grammar lazily
(only on first actual use) and reusing the instance afterward.
"""
from __future__ import annotations

import logging
from typing import Callable, Optional

from app.ingestion.parsers.base import LanguageParser

logger = logging.getLogger("codesage.ingestion.parsers.manager")


class ParserManager:
    """Registers and lazily instantiates per-language parsers by file extension."""

    def __init__(self) -> None:
        """Initialize an empty registry — no parsers are constructed yet."""
        self._factories: dict[str, Callable[[], LanguageParser]] = {}
        self._extension_to_language: dict[str, str] = {}
        self._instances: dict[str, LanguageParser] = {}

    def register(self, language_name: str, extensions: frozenset[str], factory: Callable[[], LanguageParser]) -> None:
        """Register a language parser factory without instantiating it.

        Args:
            language_name: Canonical language name (e.g. ``"python"``).
            extensions: File extensions this parser handles (e.g. ``{".py"}``).
            factory: A zero-argument callable constructing the parser —
                deferred so the Tree-sitter grammar isn't loaded until
                actually needed.
        """
        self._factories[language_name] = factory
        for extension in extensions:
            self._extension_to_language[extension] = language_name

    def supported_extensions(self) -> frozenset[str]:
        """Return every file extension with a registered parser.

        Returns:
            All registered extensions, across every language.
        """
        return frozenset(self._extension_to_language.keys())

    def supports(self, extension: str) -> bool:
        """Check whether a file extension has a registered parser.

        Args:
            extension: The lowercased file extension, including the dot.

        Returns:
            ``True`` if a parser is registered for this extension.
        """
        return extension in self._extension_to_language

    def get_parser_for_extension(self, extension: str) -> Optional[LanguageParser]:
        """Return the (lazily instantiated) parser for a file extension.

        Args:
            extension: The lowercased file extension, including the dot.

        Returns:
            The matching parser, or ``None`` if unsupported.
        """
        language_name = self._extension_to_language.get(extension)
        if language_name is None:
            return None
        return self._get_or_create(language_name)

    def _get_or_create(self, language_name: str) -> LanguageParser:
        """Instantiate and cache a parser on first use.

        Args:
            language_name: Canonical language name.

        Returns:
            The cached or newly constructed parser instance.
        """
        if language_name not in self._instances:
            logger.info("Lazily loading Tree-sitter grammar for '%s'", language_name)
            self._instances[language_name] = self._factories[language_name]()
        return self._instances[language_name]


def create_default_parser_manager() -> ParserManager:
    """Build a ParserManager with Python/JavaScript/TypeScript/Java registered.

    Returns:
        A manager with all built-in language parsers registered — none
        are instantiated yet; each loads lazily on first actual use.
    """
    from app.ingestion.parsers.java_parser import JavaParser
    from app.ingestion.parsers.javascript_parser import JavaScriptParser
    from app.ingestion.parsers.python_parser import PythonParser
    from app.ingestion.parsers.typescript_parser import TypeScriptParser

    manager = ParserManager()
    manager.register(PythonParser.language_name, PythonParser.file_extensions, PythonParser)
    manager.register(JavaScriptParser.language_name, JavaScriptParser.file_extensions, JavaScriptParser)
    manager.register(TypeScriptParser.language_name, TypeScriptParser.file_extensions, TypeScriptParser)
    manager.register(JavaParser.language_name, JavaParser.file_extensions, JavaParser)
    return manager
