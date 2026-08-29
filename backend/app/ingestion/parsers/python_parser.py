"""Python language parser — Tree-sitter based symbol/import extraction.

Scope, per Sprint 2A: classes, functions/methods, enum classes
(``class X(Enum)``), and top-level (module-scope) variables only —
nested/local functions and class-body fields are not extracted as
symbols. Visibility is inferred from naming convention (Python has no
enforced visibility keywords): dunder names are public, ``__name``
(no trailing dunder) is private, single-underscore is protected.
"""
from __future__ import annotations

from typing import ClassVar, Optional

import tree_sitter_python as ts_python
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

_ENUM_BASE_NAMES = frozenset({"Enum", "IntEnum", "Flag", "IntFlag", "StrEnum"})
_NESTED_SCOPE_TYPES = frozenset({"function_definition", "class_definition"})
_SELF_RECEIVER_NAMES = frozenset({"self", "cls"})


class PythonParser(BaseTreeSitterParser):
    """Extracts classes, functions, methods, enums, and imports from Python source."""

    language_name: ClassVar[str] = "python"
    file_extensions: ClassVar[frozenset[str]] = frozenset({".py", ".pyi"})

    def _load_language(self) -> Language:
        """Load the tree-sitter-python grammar.

        Returns:
            The Python :class:`Language`.
        """
        return Language(ts_python.language())

    def _extract(self, root_node: Node, source_code: bytes, module_path: str) -> ParseOutput:
        """Extract symbols/imports/relationships from a parsed Python file.

        Args:
            root_node: The ``module`` root node.
            source_code: The file's raw bytes.
            module_path: Dotted module path used as the qualified-name root.

        Returns:
            Everything extracted from this file.
        """
        output = ParseOutput()
        self._walk_body(root_node, source_code, module_path, output, is_class_body=False)
        self._extract_imports(root_node, source_code, module_path, output)
        return output

    @staticmethod
    def _unwrap_decorated(node: Node) -> Node:
        """Return the inner class/function node, unwrapping a decorator wrapper.

        Args:
            node: A direct child of a body block, possibly a
                ``decorated_definition`` wrapper.

        Returns:
            The wrapped ``class_definition``/``function_definition``, or
            the original node if it wasn't decorated.
        """
        if node.type == "decorated_definition":
            inner = node.child_by_field_name("definition")
            return inner if inner is not None else node
        return node

    @staticmethod
    def _visibility_from_name(name: str) -> str:
        """Infer visibility from Python's naming convention.

        Args:
            name: The symbol's bare name.

        Returns:
            ``public`` for dunder names and unprefixed names, ``private``
            for name-mangled ``__name``, ``protected`` for ``_name``.
        """
        if name.startswith("__") and name.endswith("__"):
            return "public"
        if name.startswith("__"):
            return "private"
        if name.startswith("_"):
            return "protected"
        return "public"

    def _walk_body(
        self,
        body_node: Node,
        source_code: bytes,
        parent_qualified_name: str,
        output: ParseOutput,
        is_class_body: bool,
    ) -> None:
        """Extract symbols directly inside one block (module or class body).

        Args:
            body_node: The ``module`` or class ``block`` node.
            source_code: The file's raw bytes.
            parent_qualified_name: Dotted qualified name of the enclosing scope.
            output: Accumulator for extracted symbols/relationships.
            is_class_body: Whether this block is a class body (methods)
                or the module body (top-level functions/variables).
        """
        for raw_child in body_node.children:
            child = self._unwrap_decorated(raw_child)

            if child.type == "class_definition":
                self._handle_class(child, source_code, parent_qualified_name, output, is_nested=is_class_body)
            elif child.type == "function_definition":
                self._handle_function(child, source_code, parent_qualified_name, output, is_class_body)
            elif child.type == "expression_statement" and not is_class_body:
                self._handle_top_level_assignment(child, source_code, parent_qualified_name, output)

    def _handle_class(
        self, node: Node, source_code: bytes, parent_qualified_name: str, output: ParseOutput, is_nested: bool
    ) -> None:
        """Extract a class (or enum class) and recurse into its methods.

        Args:
            node: The ``class_definition`` node.
            source_code: The file's raw bytes.
            parent_qualified_name: Dotted qualified name of the enclosing scope
                (used to build this class's own qualified name either way).
            output: Accumulator for extracted symbols/relationships.
            is_nested: Whether this class is itself nested inside another
                class (``True``) or at module level (``False``) — controls
                whether the emitted symbol's ``parent_qualified_name`` is
                set (immediate enclosing *symbol*) or left ``None``
                (module-level; module containment is still recorded via
                the separate ``belongs_to`` relationship).
        """
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return
        name = node_text(name_node, source_code)
        qualified_name = f"{parent_qualified_name}.{name}"
        symbol_parent = parent_qualified_name if is_nested else None

        superclasses_node = node.child_by_field_name("superclasses")
        base_names: list[str] = []
        is_enum = False
        if superclasses_node is not None:
            for arg in superclasses_node.children:
                if arg.type in ("identifier", "attribute"):
                    base_text = node_text(arg, source_code)
                    base_names.append(base_text)
                    if base_text in _ENUM_BASE_NAMES:
                        is_enum = True

        output.symbols.append(
            ExtractedSymbol(
                name=name,
                qualified_name=qualified_name,
                symbol_type="enum" if is_enum else "class",
                visibility=self._visibility_from_name(name),
                start_line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
                signature=node_text(superclasses_node, source_code) or None,
                parent_qualified_name=symbol_parent,
            )
        )

        for base_name in base_names:
            output.relationships.append(
                ExtractedRelationship(source_symbol=qualified_name, target_symbol=base_name, relationship_type="extends")
            )
        output.relationships.append(
            ExtractedRelationship(
                source_symbol=qualified_name, target_symbol=parent_qualified_name, relationship_type="belongs_to"
            )
        )

        body_node = node.child_by_field_name("body")
        if body_node is not None and not is_enum:
            self._walk_body(body_node, source_code, qualified_name, output, is_class_body=True)

    def _handle_function(
        self,
        node: Node,
        source_code: bytes,
        parent_qualified_name: str,
        output: ParseOutput,
        is_class_body: bool,
    ) -> None:
        """Extract a top-level function or a class method.

        Args:
            node: The ``function_definition`` node.
            source_code: The file's raw bytes.
            parent_qualified_name: Dotted qualified name of the enclosing scope.
            output: Accumulator for extracted symbols/relationships.
            is_class_body: ``True`` if this function is a method (its
                parent block is a class body).
        """
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return
        name = node_text(name_node, source_code)
        qualified_name = f"{parent_qualified_name}.{name}"

        params_text = node_text(node.child_by_field_name("parameters"), source_code)
        return_type_node = node.child_by_field_name("return_type")
        signature = f"{params_text} -> {node_text(return_type_node, source_code)}" if return_type_node else params_text

        output.symbols.append(
            ExtractedSymbol(
                name=name,
                qualified_name=qualified_name,
                symbol_type="method" if is_class_body else "function",
                visibility=self._visibility_from_name(name),
                start_line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
                signature=signature or None,
                parent_qualified_name=parent_qualified_name if is_class_body else None,
            )
        )
        output.relationships.append(
            ExtractedRelationship(
                source_symbol=qualified_name, target_symbol=parent_qualified_name, relationship_type="belongs_to"
            )
        )

        body_node = node.child_by_field_name("body")
        if body_node is not None:
            self._extract_calls(body_node, source_code, qualified_name, output)

    def _extract_calls(
        self, body_node: Node, source_code: bytes, caller_qualified_name: str, output: ParseOutput
    ) -> None:
        """Extract call expressions directly within a function/method body.

        Only calls in this function's own scope are captured — nested
        function/class definitions are not descended into, so their
        calls are attributed to themselves, not this outer function
        (they simply aren't extracted at all, since Sprint 2A doesn't
        treat nested functions as symbols in the first place).

        Args:
            body_node: The function/method's ``block`` node.
            source_code: The file's raw bytes.
            caller_qualified_name: The enclosing function/method's
                qualified name, recorded as each call's caller.
            output: Accumulator for extracted calls.
        """
        for call_node in iter_nodes_of_type(body_node, "call", stop_at=_NESTED_SCOPE_TYPES):
            function_node = call_node.child_by_field_name("function")
            if function_node is None:
                continue

            if function_node.type == "identifier":
                callee_name = node_text(function_node, source_code)
                output.calls.append(ExtractedCall(caller_qualified_name, callee_name, is_self_reference=False))
            elif function_node.type == "attribute":
                receiver = function_node.child_by_field_name("object")
                attribute = function_node.child_by_field_name("attribute")
                if receiver is None or attribute is None or receiver.type != "identifier":
                    continue
                if node_text(receiver, source_code) in _SELF_RECEIVER_NAMES:
                    callee_name = node_text(attribute, source_code)
                    output.calls.append(ExtractedCall(caller_qualified_name, callee_name, is_self_reference=True))

    def _handle_top_level_assignment(
        self, expr_statement_node: Node, source_code: bytes, module_path: str, output: ParseOutput
    ) -> None:
        """Extract a simple module-level variable assignment.

        Args:
            expr_statement_node: The ``expression_statement`` node.
            source_code: The file's raw bytes.
            module_path: Dotted module path (this file's own qualified-name root).
            output: Accumulator for extracted symbols.
        """
        assignments = direct_children_of_type(expr_statement_node, "assignment")
        if not assignments:
            return
        target = assignments[0].child_by_field_name("left")
        if target is None or target.type != "identifier":
            return
        name = node_text(target, source_code)
        output.symbols.append(
            ExtractedSymbol(
                name=name,
                qualified_name=f"{module_path}.{name}",
                symbol_type="variable",
                visibility=self._visibility_from_name(name),
                start_line=expr_statement_node.start_point[0] + 1,
                end_line=expr_statement_node.end_point[0] + 1,
                parent_qualified_name=None,
            )
        )

    def _extract_imports(
        self, root_node: Node, source_code: bytes, module_path: str, output: ParseOutput
    ) -> None:
        """Extract every import statement at any depth in the file.

        Args:
            root_node: The ``module`` root node.
            source_code: The file's raw bytes.
            module_path: This file's own dotted module path (import edges'
                source endpoint).
            output: Accumulator for extracted imports/relationships.
        """
        import_nodes = iter_nodes_of_type(
            root_node,
            "import_statement",
            "import_from_statement",
            stop_at=frozenset({"function_definition", "class_definition"}),
        )
        for node in import_nodes:
            statement_text = node_text(node, source_code)

            if node.type == "import_statement":
                for target in direct_children_of_type(node, "dotted_name", "aliased_import"):
                    module = node_text(target, source_code)
                    output.imports.append(ExtractedImport(statement=statement_text, module=module, kind="import"))
                    output.relationships.append(
                        ExtractedRelationship(source_symbol=module_path, target_symbol=module, relationship_type="imports")
                    )
                continue

            module_node = node.child_by_field_name("module_name")
            module = node_text(module_node, source_code)
            is_relative = module_node is not None and module_node.type == "relative_import"
            imported_names = [
                node_text(child, source_code)
                for child in node.children
                if child.type in ("dotted_name", "aliased_import")
                and (module_node is None or child.start_byte != module_node.start_byte)
            ]
            output.imports.append(
                ExtractedImport(
                    statement=statement_text,
                    module=module,
                    imported_names=imported_names,
                    is_relative=is_relative,
                    kind="import",
                )
            )
            output.relationships.append(
                ExtractedRelationship(source_symbol=module_path, target_symbol=module, relationship_type="imports")
            )
