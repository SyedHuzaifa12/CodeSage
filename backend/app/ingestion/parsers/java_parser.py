"""Java language parser — Tree-sitter based symbol/import extraction.

Scope, per Sprint 2A: classes, interfaces, enums, methods/constructors,
and the file's ``package`` declaration (recorded as a ``namespace``
symbol — Java's closest equivalent). Java has no file-scope variables
(everything is a class member or local), so no ``variable`` symbols are
produced. Visibility comes from the ``modifiers`` node; Java's actual
default with no modifier is *package-private*, not public.
"""
from __future__ import annotations

from typing import ClassVar, Optional

import tree_sitter_java as ts_java
from tree_sitter import Language, Node

from app.ingestion.parsers.base import (
    BaseTreeSitterParser,
    ExtractedCall,
    ExtractedImport,
    ExtractedRelationship,
    ExtractedSymbol,
    ParseOutput,
    direct_children_of_type,
    iter_nodes_of_type,
    node_text,
)

_TYPE_DECLARATION_TYPES = ("class_declaration", "interface_declaration", "enum_declaration")
_NESTED_SCOPE_TYPES = frozenset(
    {"class_declaration", "interface_declaration", "enum_declaration", "method_declaration", "constructor_declaration"}
)


class JavaParser(BaseTreeSitterParser):
    """Extracts classes, interfaces, enums, methods, and imports from Java source."""

    language_name: ClassVar[str] = "java"
    file_extensions: ClassVar[frozenset[str]] = frozenset({".java"})

    def _load_language(self) -> Language:
        """Load the tree-sitter-java grammar.

        Returns:
            The Java :class:`Language`.
        """
        return Language(ts_java.language())

    def _extract(self, root_node: Node, source_code: bytes, module_path: str) -> ParseOutput:
        """Extract symbols/imports/relationships from a parsed Java file.

        Java's own package+class naming convention already gives a fully
        qualified name (``package.ClassName``), and by convention a
        top-level public class's name matches its file name — so
        ``module_path`` (derived from the file path) would double up
        with the class name if used as a qualifying prefix. Top-level
        types are qualified by the actual ``package`` declaration
        instead (or left unqualified if there is no package).

        Args:
            root_node: The ``program`` root node.
            source_code: The file's raw bytes.
            module_path: Dotted module path derived from the file path;
                used only as a fallback import-edge source when no
                ``package`` declaration is present.

        Returns:
            Everything extracted from this file.
        """
        output = ParseOutput()
        package_name = self._extract_package(root_node, source_code, output)
        file_qualifier = package_name or module_path
        self._extract_imports(root_node, source_code, file_qualifier, output)
        for node in direct_children_of_type(root_node, *_TYPE_DECLARATION_TYPES):
            self._handle_type_declaration(node, source_code, package_name, output)
        return output

    @staticmethod
    def _visibility_from_modifiers(node: Node) -> str:
        """Infer visibility from a declaration's ``modifiers`` child.

        Args:
            node: A declaration node that may have a ``modifiers`` child.

        Returns:
            ``public``/``private``/``protected`` if that keyword is
            present, otherwise ``package-private`` (Java's real default).
        """
        modifiers = direct_children_of_type(node, "modifiers")
        if not modifiers:
            return "package-private"
        keywords = {child.type for child in modifiers[0].children}
        for level in ("public", "private", "protected"):
            if level in keywords:
                return level
        return "package-private"

    def _extract_package(self, root_node: Node, source_code: bytes, output: ParseOutput) -> Optional[str]:
        """Record the file's ``package`` declaration as a namespace symbol.

        Args:
            root_node: The ``program`` root node.
            source_code: The file's raw bytes.
            output: Accumulator for extracted symbols.

        Returns:
            The dotted package name, or ``None`` if the file declares no
            package (Java's "default package").
        """
        for node in direct_children_of_type(root_node, "package_declaration"):
            scoped = direct_children_of_type(node, "scoped_identifier", "identifier")
            if not scoped:
                continue
            name = node_text(scoped[0], source_code)
            output.symbols.append(
                ExtractedSymbol(
                    name=name,
                    qualified_name=name,
                    symbol_type="namespace",
                    visibility="public",
                    start_line=node.start_point[0] + 1,
                    end_line=node.end_point[0] + 1,
                    parent_qualified_name=None,
                )
            )
            return name
        return None

    def _extract_imports(self, root_node: Node, source_code: bytes, module_path: str, output: ParseOutput) -> None:
        """Extract every ``import`` declaration in the file.

        Args:
            root_node: The ``program`` root node.
            source_code: The file's raw bytes.
            module_path: This file's own dotted module path (import edges'
                source endpoint).
            output: Accumulator for extracted imports/relationships.
        """
        for node in direct_children_of_type(root_node, "import_declaration"):
            scoped = direct_children_of_type(node, "scoped_identifier", "identifier")
            if not scoped:
                continue
            module = node_text(scoped[0], source_code)
            is_static = any(child.type == "static" for child in node.children)
            output.imports.append(
                ExtractedImport(statement=node_text(node, source_code), module=module, kind="import" if not is_static else "static_import")
            )
            output.relationships.append(
                ExtractedRelationship(source_symbol=module_path, target_symbol=module, relationship_type="imports")
            )

    def _handle_type_declaration(
        self, node: Node, source_code: bytes, package_name: Optional[str], output: ParseOutput
    ) -> None:
        """Extract a class/interface/enum declaration and its members.

        Args:
            node: The ``class_declaration``/``interface_declaration``/``enum_declaration`` node.
            source_code: The file's raw bytes.
            package_name: The file's dotted package name, or ``None`` for
                the default package (in which case the type is left
                unqualified, matching Java's own naming rules).
            output: Accumulator for extracted symbols/relationships.
        """
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return
        name = node_text(name_node, source_code)
        qualified_name = f"{package_name}.{name}" if package_name else name
        symbol_type = {
            "class_declaration": "class",
            "interface_declaration": "interface",
            "enum_declaration": "enum",
        }[node.type]

        superclass_names, interface_names = self._extract_java_heritage(node, source_code)

        output.symbols.append(
            ExtractedSymbol(
                name=name,
                qualified_name=qualified_name,
                symbol_type=symbol_type,
                visibility=self._visibility_from_modifiers(node),
                start_line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
                parent_qualified_name=None,
            )
        )
        for base_name in superclass_names:
            output.relationships.append(
                ExtractedRelationship(source_symbol=qualified_name, target_symbol=base_name, relationship_type="extends")
            )
        for interface_name in interface_names:
            output.relationships.append(
                ExtractedRelationship(
                    source_symbol=qualified_name, target_symbol=interface_name, relationship_type="implements"
                )
            )
        if package_name:
            output.relationships.append(
                ExtractedRelationship(source_symbol=qualified_name, target_symbol=package_name, relationship_type="belongs_to")
            )

        body_node = node.child_by_field_name("body")
        if body_node is not None:
            self._handle_members(body_node, source_code, qualified_name, output)

    @staticmethod
    def _extract_java_heritage(node: Node, source_code: bytes) -> tuple[list[str], list[str]]:
        """Extract ``extends``/``implements`` type names from a type declaration.

        Args:
            node: The ``class_declaration``/``interface_declaration`` node.
            source_code: The file's raw bytes.

        Returns:
            A ``(superclass_names, interface_names)`` tuple. Interfaces
            can themselves ``extends`` one or more other interfaces,
            which is also captured under ``superclass_names``.
        """
        type_node_types = ("type_identifier", "generic_type")
        superclass_names: list[str] = []
        interface_names: list[str] = []

        superclass_node = node.child_by_field_name("superclass")
        if superclass_node is not None:
            superclass_names.extend(
                node_text(child, source_code) for child in superclass_node.children if child.type in type_node_types
            )

        # An interface's own "extends" (interfaces can extend other interfaces).
        if node.type == "interface_declaration":
            for clause in direct_children_of_type(node, "extends_interfaces"):
                for type_list in direct_children_of_type(clause, "type_list"):
                    superclass_names.extend(
                        node_text(child, source_code) for child in type_list.children if child.type in type_node_types
                    )

        interfaces_node = node.child_by_field_name("interfaces")
        if interfaces_node is not None and node.type != "interface_declaration":
            for type_list in direct_children_of_type(interfaces_node, "type_list"):
                interface_names.extend(
                    node_text(child, source_code) for child in type_list.children if child.type in type_node_types
                )

        return superclass_names, interface_names

    def _handle_members(self, body_node: Node, source_code: bytes, class_qualified_name: str, output: ParseOutput) -> None:
        """Extract methods and constructors from a class/interface/enum body.

        Args:
            body_node: The type declaration's ``body`` node.
            source_code: The file's raw bytes.
            class_qualified_name: The owning type's qualified name.
            output: Accumulator for extracted symbols/relationships.
        """
        for member in direct_children_of_type(body_node, "method_declaration", "constructor_declaration"):
            name_node = member.child_by_field_name("name")
            if name_node is None:
                continue
            name = node_text(name_node, source_code)
            qualified_name = f"{class_qualified_name}.{name}"
            params_text = node_text(member.child_by_field_name("parameters"), source_code)
            return_type_node = member.child_by_field_name("type")
            signature = f"{params_text} : {node_text(return_type_node, source_code)}" if return_type_node else params_text

            output.symbols.append(
                ExtractedSymbol(
                    name=name,
                    qualified_name=qualified_name,
                    symbol_type="method",
                    visibility=self._visibility_from_modifiers(member),
                    start_line=member.start_point[0] + 1,
                    end_line=member.end_point[0] + 1,
                    signature=signature or None,
                    parent_qualified_name=class_qualified_name,
                )
            )
            output.relationships.append(
                ExtractedRelationship(
                    source_symbol=qualified_name, target_symbol=class_qualified_name, relationship_type="belongs_to"
                )
            )

            member_body = member.child_by_field_name("body")
            if member_body is not None:
                self._extract_calls(member_body, source_code, qualified_name, output)

    def _extract_calls(
        self, body_node: Node, source_code: bytes, caller_qualified_name: str, output: ParseOutput
    ) -> None:
        """Extract method-invocation expressions directly within a method body.

        A bare call (no receiver) and an explicit ``this.x()`` call are
        both treated as calling a method on the enclosing class itself
        — Java has no free-floating functions, so an unqualified call
        always resolves to the current (or an inherited) class's own
        method. Nested type/method declarations are not descended into.

        Args:
            body_node: The method/constructor's ``block`` node.
            source_code: The file's raw bytes.
            caller_qualified_name: The enclosing method's qualified
                name, recorded as each call's caller.
            output: Accumulator for extracted calls.
        """
        for call_node in iter_nodes_of_type(body_node, "method_invocation", stop_at=_NESTED_SCOPE_TYPES):
            name_node = call_node.child_by_field_name("name")
            if name_node is None:
                continue
            object_node = call_node.child_by_field_name("object")
            if object_node is None or node_text(object_node, source_code) == "this":
                callee_name = node_text(name_node, source_code)
                output.calls.append(ExtractedCall(caller_qualified_name, callee_name, is_self_reference=True))
