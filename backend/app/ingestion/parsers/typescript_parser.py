"""TypeScript language parser — extends the JavaScript parser.

Adds what plain JavaScript has no grammar for: ``interface``, ``enum``,
and ``namespace``/``module`` declarations, plus accessibility-modifier
(``public``/``private``/``protected``) visibility on class members
(TypeScript's actual default when unspecified is ``public``, unlike
Java's package-private default). Reuses every class/function/import
extraction method from :class:`JavaScriptParser` — the two grammars
share almost all node types.
"""
from __future__ import annotations

from typing import ClassVar

import tree_sitter_typescript as ts_typescript
from tree_sitter import Language, Node

from app.ingestion.parsers.base import ExtractedRelationship, ExtractedSymbol, ParseOutput, direct_children_of_type, node_text
from app.ingestion.parsers.javascript_parser import JavaScriptParser

_MEMBER_NODE_TYPES = frozenset({"method_definition", "public_field_definition"})


class TypeScriptParser(JavaScriptParser):
    """Extracts classes, interfaces, enums, namespaces, and imports from TypeScript."""

    language_name: ClassVar[str] = "typescript"
    file_extensions: ClassVar[frozenset[str]] = frozenset({".ts", ".tsx"})

    def _load_language(self) -> Language:
        """Load the tree-sitter-typescript grammar (the ``.ts`` variant).

        Returns:
            The TypeScript :class:`Language`.
        """
        return Language(ts_typescript.language_typescript())

    def _compute_visibility(self, node: Node, name: str) -> str:
        """Infer visibility from a TypeScript accessibility modifier.

        Args:
            node: The declaration/definition node (checked for an
                ``accessibility_modifier`` child when it's a class member).
            name: The member's bare name.

        Returns:
            ``public``, ``private``, or ``protected`` from an explicit
            modifier; otherwise falls back to the ``#private``-field
            convention (still valid in TS) and defaults to ``public``.
        """
        if node.type in _MEMBER_NODE_TYPES:
            modifiers = direct_children_of_type(node, "accessibility_modifier")
            if modifiers and modifiers[0].children:
                return modifiers[0].children[0].type
        return super()._compute_visibility(node, name)

    def _handle_top_level_node(
        self, node: Node, source_code: bytes, parent_qualified_name: str, output: ParseOutput
    ) -> None:
        """Dispatch a top-level statement, adding TS-only constructs.

        Args:
            node: The statement node.
            source_code: The file's raw bytes.
            parent_qualified_name: Dotted qualified name of the enclosing scope.
            output: Accumulator for extracted symbols/relationships.
        """
        if node.type == "interface_declaration":
            self._handle_interface(node, source_code, parent_qualified_name, output)
        elif node.type == "enum_declaration":
            self._handle_enum(node, source_code, parent_qualified_name, output)
        elif node.type == "internal_module":
            self._handle_namespace(node, source_code, parent_qualified_name, output)
        else:
            super()._handle_top_level_node(node, source_code, parent_qualified_name, output)

    def _handle_interface(self, node: Node, source_code: bytes, module_path: str, output: ParseOutput) -> None:
        """Extract an ``interface`` declaration, including extended interfaces.

        Args:
            node: The ``interface_declaration`` node.
            source_code: The file's raw bytes.
            module_path: Dotted module path (this file's qualified-name root).
            output: Accumulator for extracted symbols/relationships.
        """
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return
        name = node_text(name_node, source_code)
        qualified_name = f"{module_path}.{name}"

        extends_names = [
            node_text(child, source_code)
            for heritage in direct_children_of_type(node, "extends_type_clause")
            for child in heritage.children
            if child.type in ("type_identifier", "generic_type")
        ]

        output.symbols.append(
            ExtractedSymbol(
                name=name,
                qualified_name=qualified_name,
                symbol_type="interface",
                visibility="public",
                start_line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
                signature=(f"extends {', '.join(extends_names)}" if extends_names else None),
                parent_qualified_name=None,
            )
        )
        for base_name in extends_names:
            output.relationships.append(
                ExtractedRelationship(source_symbol=qualified_name, target_symbol=base_name, relationship_type="extends")
            )

    def _handle_enum(self, node: Node, source_code: bytes, module_path: str, output: ParseOutput) -> None:
        """Extract an ``enum`` declaration.

        Args:
            node: The ``enum_declaration`` node.
            source_code: The file's raw bytes.
            module_path: Dotted module path (this file's qualified-name root).
            output: Accumulator for extracted symbols.
        """
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return
        name = node_text(name_node, source_code)
        output.symbols.append(
            ExtractedSymbol(
                name=name,
                qualified_name=f"{module_path}.{name}",
                symbol_type="enum",
                visibility="public",
                start_line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
                parent_qualified_name=None,
            )
        )

    def _handle_namespace(self, node: Node, source_code: bytes, module_path: str, output: ParseOutput) -> None:
        """Extract a ``namespace``/``module`` block and recurse into its members.

        Args:
            node: The ``internal_module`` node.
            source_code: The file's raw bytes.
            module_path: Dotted module path (this file's qualified-name root).
            output: Accumulator for extracted symbols/relationships.
        """
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return
        name = node_text(name_node, source_code)
        qualified_name = f"{module_path}.{name}"
        output.symbols.append(
            ExtractedSymbol(
                name=name,
                qualified_name=qualified_name,
                symbol_type="namespace",
                visibility="public",
                start_line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
                parent_qualified_name=None,
            )
        )

        body = node.child_by_field_name("body")
        if body is None:
            return
        for child in body.children:
            declaration = child.child_by_field_name("declaration") if child.type == "export_statement" else child
            if declaration is not None:
                self._handle_top_level_node(declaration, source_code, qualified_name, output)
