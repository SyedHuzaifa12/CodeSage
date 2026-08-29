"""JavaScript language parser — Tree-sitter based symbol/import extraction.

Scope, per Sprint 2A: classes, functions/methods (including
``const x = () => {}`` arrow-function assignments, idiomatic in modern
JS), and top-level variables. Plain JavaScript has no interfaces/enums/
namespaces. Supports both ES module syntax (``import``/``export``) and
CommonJS (``require``). :class:`TypeScriptParser` subclasses this to
add interfaces, enums, namespaces, and accessibility-modifier visibility.
"""
from __future__ import annotations

from typing import ClassVar

import tree_sitter_javascript as ts_javascript
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


_NESTED_SCOPE_TYPES = frozenset(
    {"function_declaration", "class_declaration", "method_definition", "arrow_function", "function_expression"}
)
_SELF_RECEIVER_TYPES = frozenset({"this"})


class JavaScriptParser(BaseTreeSitterParser):
    """Extracts classes, functions, methods, and imports from JavaScript source."""

    language_name: ClassVar[str] = "javascript"
    file_extensions: ClassVar[frozenset[str]] = frozenset({".js", ".jsx", ".mjs", ".cjs"})

    def _load_language(self) -> Language:
        """Load the tree-sitter-javascript grammar.

        Returns:
            The JavaScript :class:`Language`.
        """
        return Language(ts_javascript.language())

    def _extract(self, root_node: Node, source_code: bytes, module_path: str) -> ParseOutput:
        """Extract symbols/imports/relationships from a parsed JS file.

        Args:
            root_node: The ``program`` root node.
            source_code: The file's raw bytes.
            module_path: Dotted module path used as the qualified-name root.

        Returns:
            Everything extracted from this file.
        """
        output = ParseOutput()
        for child in root_node.children:
            declaration = child.child_by_field_name("declaration") if child.type == "export_statement" else child
            if declaration is not None:
                self._handle_top_level_node(declaration, source_code, module_path, output)
        self._extract_imports_and_exports(root_node, source_code, module_path, output)
        return output

    def _handle_top_level_node(
        self, node: Node, source_code: bytes, parent_qualified_name: str, output: ParseOutput
    ) -> None:
        """Dispatch a single top-level (or unwrapped export) statement.

        Args:
            node: The statement node.
            source_code: The file's raw bytes.
            parent_qualified_name: Dotted qualified name of the enclosing scope.
            output: Accumulator for extracted symbols/relationships.
        """
        if node.type == "class_declaration":
            self._handle_class(node, source_code, parent_qualified_name, output)
        elif node.type == "function_declaration":
            self._handle_function(node, source_code, parent_qualified_name, output, is_method=False)
        elif node.type in ("lexical_declaration", "variable_declaration"):
            self._handle_variable_declaration(node, source_code, parent_qualified_name, output)

    def _compute_visibility(self, node: Node, name: str) -> str:
        """Infer visibility from JS's ``#private`` field/method convention.

        Overridden by :class:`TypeScriptParser` to additionally check
        TypeScript's ``accessibility_modifier`` keywords.

        Args:
            node: The declaration/definition node the symbol came from
                (unused in plain JS, present so subclasses can inspect it).
            name: The member's bare name (as written, including any ``#``).

        Returns:
            ``private`` for ``#``-prefixed names, ``public`` otherwise.
        """
        return "private" if name.startswith("#") else "public"

    def _extract_heritage(self, class_heritage_node: Node, source_code: bytes) -> tuple[list[str], list[str]]:
        """Extract base-class and implemented-interface names from a class's heritage.

        Handles both the plain-JS grammar (bare ``extends`` keyword plus
        an expression) and the TypeScript grammar (``extends_clause``/
        ``implements_clause`` wrapper nodes).

        Args:
            class_heritage_node: The ``class_heritage`` node.
            source_code: The file's raw bytes.

        Returns:
            A ``(extends_names, implements_names)`` tuple.
        """
        return (
            self._extract_extends_names(class_heritage_node, source_code),
            self._extract_implements_names(class_heritage_node, source_code),
        )

    @staticmethod
    def _extract_extends_names(class_heritage_node: Node, source_code: bytes) -> list[str]:
        """Extract base-class names, whether wrapped in ``extends_clause`` or bare.

        Args:
            class_heritage_node: The ``class_heritage`` node.
            source_code: The file's raw bytes.

        Returns:
            Every base-class name found (usually zero or one).
        """
        type_node_types = ("identifier", "type_identifier", "generic_type", "member_expression")
        extends_clauses = direct_children_of_type(class_heritage_node, "extends_clause")
        if extends_clauses:
            return [
                node_text(child, source_code)
                for clause in extends_clauses
                for child in clause.children
                if child.type in type_node_types
            ]

        names: list[str] = []
        saw_extends_keyword = False
        for child in class_heritage_node.children:
            if child.type == "extends":
                saw_extends_keyword = True
                continue
            if saw_extends_keyword and child.type in ("identifier", "member_expression"):
                names.append(node_text(child, source_code))
                saw_extends_keyword = False
        return names

    @staticmethod
    def _extract_implements_names(class_heritage_node: Node, source_code: bytes) -> list[str]:
        """Extract implemented-interface names from a TypeScript ``implements_clause``.

        Args:
            class_heritage_node: The ``class_heritage`` node.
            source_code: The file's raw bytes.

        Returns:
            Every implemented interface name (empty for plain JS).
        """
        type_node_types = ("type_identifier", "generic_type")
        names: list[str] = []
        for clause in direct_children_of_type(class_heritage_node, "implements_clause"):
            # Single interface: type_identifier/generic_type is a direct child.
            # Multiple (comma-separated): wrapped in an intermediate type_list.
            type_lists = direct_children_of_type(clause, "type_list")
            if type_lists:
                names.extend(
                    node_text(child, source_code) for child in type_lists[0].children if child.type in type_node_types
                )
            else:
                names.extend(
                    node_text(child, source_code) for child in clause.children if child.type in type_node_types
                )
        return names

    def _handle_class(
        self, node: Node, source_code: bytes, parent_qualified_name: str, output: ParseOutput
    ) -> None:
        """Extract a class declaration and recurse into its methods.

        Args:
            node: The ``class_declaration`` node.
            source_code: The file's raw bytes.
            parent_qualified_name: Dotted qualified name of the enclosing scope.
            output: Accumulator for extracted symbols/relationships.
        """
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return
        name = node_text(name_node, source_code)
        qualified_name = f"{parent_qualified_name}.{name}"

        extends_names: list[str] = []
        implements_names: list[str] = []
        for heritage in direct_children_of_type(node, "class_heritage"):
            extends_names, implements_names = self._extract_heritage(heritage, source_code)

        output.symbols.append(
            ExtractedSymbol(
                name=name,
                qualified_name=qualified_name,
                symbol_type="class",
                visibility=self._compute_visibility(node, name),
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
        for interface_name in implements_names:
            output.relationships.append(
                ExtractedRelationship(
                    source_symbol=qualified_name, target_symbol=interface_name, relationship_type="implements"
                )
            )
        output.relationships.append(
            ExtractedRelationship(
                source_symbol=qualified_name, target_symbol=parent_qualified_name, relationship_type="belongs_to"
            )
        )

        class_body = node.child_by_field_name("body")
        if class_body is not None:
            for member in direct_children_of_type(class_body, "method_definition"):
                self._handle_method(member, source_code, qualified_name, output)

    def _handle_method(
        self, node: Node, source_code: bytes, parent_qualified_name: str, output: ParseOutput
    ) -> None:
        """Extract a single class method.

        Args:
            node: The ``method_definition`` node.
            source_code: The file's raw bytes.
            parent_qualified_name: Dotted qualified name of the owning class.
            output: Accumulator for extracted symbols/relationships.
        """
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return
        name = node_text(name_node, source_code)
        self._emit_function_like(
            node, name, source_code, parent_qualified_name, output, symbol_type="method", is_method=True
        )

    def _handle_function(
        self,
        node: Node,
        source_code: bytes,
        parent_qualified_name: str,
        output: ParseOutput,
        is_method: bool,
    ) -> None:
        """Extract a top-level ``function`` declaration.

        Args:
            node: The ``function_declaration`` node.
            source_code: The file's raw bytes.
            parent_qualified_name: Dotted qualified name of the enclosing scope.
            output: Accumulator for extracted symbols/relationships.
            is_method: Always ``False`` here; kept for signature symmetry
                with :meth:`_emit_function_like`.
        """
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return
        name = node_text(name_node, source_code)
        self._emit_function_like(
            node, name, source_code, parent_qualified_name, output, symbol_type="function", is_method=is_method
        )

    def _emit_function_like(
        self,
        node: Node,
        name: str,
        source_code: bytes,
        parent_qualified_name: str,
        output: ParseOutput,
        symbol_type: str,
        is_method: bool,
    ) -> None:
        """Build and append a function/method symbol (and its containment edge).

        Args:
            node: The function/method definition node.
            name: The already-extracted symbol name.
            source_code: The file's raw bytes.
            parent_qualified_name: Dotted qualified name of the enclosing scope.
            output: Accumulator for extracted symbols/relationships.
            symbol_type: ``"function"`` or ``"method"``.
            is_method: Whether this belongs to a class (adds a
                ``belongs_to`` edge to its class).
        """
        qualified_name = f"{parent_qualified_name}.{name}"
        params_node = node.child_by_field_name("parameters")
        signature = node_text(params_node, source_code) or None

        output.symbols.append(
            ExtractedSymbol(
                name=name,
                qualified_name=qualified_name,
                symbol_type=symbol_type,
                visibility=self._compute_visibility(node, name),
                start_line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
                signature=signature,
                parent_qualified_name=parent_qualified_name if is_method else None,
            )
        )
        if is_method:
            output.relationships.append(
                ExtractedRelationship(
                    source_symbol=qualified_name, target_symbol=parent_qualified_name, relationship_type="belongs_to"
                )
            )

        body_node = node.child_by_field_name("body")
        if body_node is not None and body_node.type == "statement_block":
            self._extract_calls(body_node, source_code, qualified_name, output)

    def _extract_calls(
        self, body_node: Node, source_code: bytes, caller_qualified_name: str, output: ParseOutput
    ) -> None:
        """Extract call expressions directly within a function/method body.

        Only calls in this function's own scope are captured — nested
        function/class definitions are not descended into.

        Args:
            body_node: The function/method's ``statement_block`` node.
            source_code: The file's raw bytes.
            caller_qualified_name: The enclosing function/method's
                qualified name, recorded as each call's caller.
            output: Accumulator for extracted calls.
        """
        for call_node in iter_nodes_of_type(body_node, "call_expression", stop_at=_NESTED_SCOPE_TYPES):
            function_node = call_node.child_by_field_name("function")
            if function_node is None:
                continue

            if function_node.type == "identifier":
                callee_name = node_text(function_node, source_code)
                output.calls.append(ExtractedCall(caller_qualified_name, callee_name, is_self_reference=False))
            elif function_node.type == "member_expression":
                receiver = function_node.child_by_field_name("object")
                property_node = function_node.child_by_field_name("property")
                if receiver is None or property_node is None:
                    continue
                if receiver.type in _SELF_RECEIVER_TYPES:
                    callee_name = node_text(property_node, source_code)
                    output.calls.append(ExtractedCall(caller_qualified_name, callee_name, is_self_reference=True))

    def _handle_variable_declaration(
        self, node: Node, source_code: bytes, module_path: str, output: ParseOutput
    ) -> None:
        """Extract top-level ``const``/``let``/``var`` declarations.

        An arrow function assigned to a top-level ``const`` (e.g.
        ``const helper = () => {}``) is recorded as a ``function`` symbol
        rather than a plain ``variable``, matching how it is actually used.

        Args:
            node: The ``lexical_declaration``/``variable_declaration`` node.
            source_code: The file's raw bytes.
            module_path: Dotted module path (this file's qualified-name root).
            output: Accumulator for extracted symbols.
        """
        for declarator in direct_children_of_type(node, "variable_declarator"):
            name_node = declarator.child_by_field_name("name")
            if name_node is None or name_node.type != "identifier":
                continue
            name = node_text(name_node, source_code)
            value_node = declarator.child_by_field_name("value")
            is_function_value = value_node is not None and value_node.type in ("arrow_function", "function_expression")

            output.symbols.append(
                ExtractedSymbol(
                    name=name,
                    qualified_name=f"{module_path}.{name}",
                    symbol_type="function" if is_function_value else "variable",
                    visibility=self._compute_visibility(declarator, name),
                    start_line=node.start_point[0] + 1,
                    end_line=node.end_point[0] + 1,
                    signature=node_text(value_node.child_by_field_name("parameters"), source_code)
                    if is_function_value
                    else None,
                    parent_qualified_name=None,
                )
            )

    def _extract_imports_and_exports(
        self, root_node: Node, source_code: bytes, module_path: str, output: ParseOutput
    ) -> None:
        """Extract ES module imports/exports and CommonJS ``require`` calls.

        Args:
            root_node: The ``program`` root node.
            source_code: The file's raw bytes.
            module_path: This file's own dotted module path (import edges'
                source endpoint).
            output: Accumulator for extracted imports/relationships.
        """
        stop_types = frozenset({"function_declaration", "class_declaration", "method_definition", "arrow_function"})

        for node in iter_nodes_of_type(root_node, "import_statement", stop_at=stop_types):
            self._handle_import_statement(node, source_code, module_path, output)

        for node in iter_nodes_of_type(root_node, "export_statement", stop_at=stop_types):
            self._handle_export_statement(node, source_code, output)

        for node in iter_nodes_of_type(root_node, "call_expression", stop_at=stop_types):
            self._handle_require_call(node, source_code, module_path, output)

    def _handle_import_statement(
        self, node: Node, source_code: bytes, module_path: str, output: ParseOutput
    ) -> None:
        """Extract a single ES module ``import`` statement.

        Args:
            node: The ``import_statement`` node.
            source_code: The file's raw bytes.
            module_path: This file's own dotted module path.
            output: Accumulator for extracted imports/relationships.
        """
        source_node = node.child_by_field_name("source")
        module = node_text(source_node, source_code).strip("\"'")
        is_relative = module.startswith(".")

        imported_names: list[str] = []
        clauses = direct_children_of_type(node, "import_clause")
        if clauses:
            for specifier in iter_nodes_of_type(clauses[0], "import_specifier"):
                imported_names.append(node_text(specifier, source_code))
            for namespace in iter_nodes_of_type(clauses[0], "namespace_import"):
                alias = direct_children_of_type(namespace, "identifier")
                imported_names.append(node_text(alias[0], source_code) if alias else node_text(namespace, source_code))
            default_identifiers = direct_children_of_type(clauses[0], "identifier")
            imported_names.extend(node_text(identifier, source_code) for identifier in default_identifiers)

        output.imports.append(
            ExtractedImport(
                statement=node_text(node, source_code),
                module=module,
                imported_names=imported_names,
                is_relative=is_relative,
                kind="import",
            )
        )
        output.relationships.append(
            ExtractedRelationship(source_symbol=module_path, target_symbol=module, relationship_type="imports")
        )

    def _handle_export_statement(self, node: Node, source_code: bytes, output: ParseOutput) -> None:
        """Extract named re-exports and default exports.

        Declarations exported directly (``export class X``, ``export
        function y``) are already captured as symbols and are not
        duplicated here.

        Args:
            node: The ``export_statement`` node.
            source_code: The file's raw bytes.
            output: Accumulator for extracted exports.
        """
        if node.child_by_field_name("declaration") is not None:
            return

        if any(child.type == "default" for child in node.children):
            value_nodes = [c for c in node.children if c.type not in ("export", "default", ";")]
            output.imports.append(
                ExtractedImport(
                    statement=node_text(node, source_code),
                    module="default",
                    imported_names=[node_text(v, source_code) for v in value_nodes],
                    kind="export",
                )
            )
            return

        for clause in direct_children_of_type(node, "export_clause"):
            for specifier in direct_children_of_type(clause, "export_specifier"):
                output.imports.append(
                    ExtractedImport(
                        statement=node_text(specifier, source_code),
                        module=node_text(node.child_by_field_name("source"), source_code) or "",
                        imported_names=[node_text(specifier, source_code)],
                        kind="export",
                    )
                )

    def _handle_require_call(
        self, node: Node, source_code: bytes, module_path: str, output: ParseOutput
    ) -> None:
        """Extract a CommonJS ``require("module")`` call as an import edge.

        Args:
            node: A ``call_expression`` node (checked for being a ``require`` call).
            source_code: The file's raw bytes.
            module_path: This file's own dotted module path.
            output: Accumulator for extracted imports/relationships.
        """
        function_node = node.child_by_field_name("function")
        if function_node is None or node_text(function_node, source_code) != "require":
            return
        arguments_node = node.child_by_field_name("arguments")
        string_args = direct_children_of_type(arguments_node, "string") if arguments_node else []
        if not string_args:
            return
        module = node_text(string_args[0], source_code).strip("\"'")

        output.imports.append(
            ExtractedImport(
                statement=node_text(node, source_code),
                module=module,
                is_relative=module.startswith("."),
                kind="import",
            )
        )
        output.relationships.append(
            ExtractedRelationship(source_symbol=module_path, target_symbol=module, relationship_type="imports")
        )
