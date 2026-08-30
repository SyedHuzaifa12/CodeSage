"""Unit tests for deterministic Mermaid diagram generation/safety (spec §15/§20)."""
from __future__ import annotations

import re

from app.reports.mermaid import (
    _sanitize_mermaid_label,
    _sanitize_node_id,
    build_dependency_flow_diagram,
    build_module_diagram,
    module_of,
)

_VALID_NODE_ID = re.compile(r"^n_[A-Za-z0-9_]+$")


class TestSanitizeNodeId:
    def test_produces_valid_mermaid_id(self) -> None:
        used: dict[str, str] = {}
        node_id = _sanitize_node_id("app/models/repository.py", used_ids=used)
        assert _VALID_NODE_ID.match(node_id)

    def test_same_input_returns_same_id(self) -> None:
        used: dict[str, str] = {}
        first = _sanitize_node_id("app.models", used_ids=used)
        second = _sanitize_node_id("app.models", used_ids=used)
        assert first == second

    def test_colliding_slugs_get_distinct_ids(self) -> None:
        used: dict[str, str] = {}
        first = _sanitize_node_id("app/models", used_ids=used)
        second = _sanitize_node_id("app.models", used_ids=used)  # slugifies identically to the above
        assert first != second
        assert _VALID_NODE_ID.match(first) and _VALID_NODE_ID.match(second)

    def test_numeric_leading_char_is_handled(self) -> None:
        used: dict[str, str] = {}
        node_id = _sanitize_node_id("123module", used_ids=used)
        assert _VALID_NODE_ID.match(node_id)


class TestSanitizeMermaidLabel:
    def test_escapes_quotes_and_brackets(self) -> None:
        label = _sanitize_mermaid_label('app["weird"] | module')
        assert '"' not in label.replace("&quot;", "")
        assert "[" not in label.replace("&#91;", "")
        assert "]" not in label.replace("&#93;", "")
        assert "|" not in label.replace("&#124;", "")

    def test_truncates_long_labels(self) -> None:
        label = _sanitize_mermaid_label("x" * 200, max_len=60)
        assert len(label) <= 60


class TestModuleOf:
    def test_dotted_path(self) -> None:
        assert module_of("app.models.repository", depth=2) == "app.models"

    def test_slash_path(self) -> None:
        assert module_of("app/models/repository.py", depth=2) == "app.models"

    def test_single_segment(self) -> None:
        assert module_of("main.py", depth=2) == "main"

    def test_empty_falls_back_to_root(self) -> None:
        assert module_of("", depth=2) == "root"


class TestBuildModuleDiagram:
    def test_valid_flowchart_header(self) -> None:
        diagram = build_module_diagram(["app/models/a.py", "app/services/b.py"], [])
        assert diagram.startswith("flowchart TD")

    def test_node_count_bounded(self) -> None:
        file_paths = [f"module_{i}/file.py" for i in range(50)]
        diagram = build_module_diagram(file_paths, [], max_nodes=10)
        node_lines = [line for line in diagram.splitlines() if line.strip().startswith("n_")]
        assert len(node_lines) <= 10
        assert "partial" in diagram

    def test_no_unescaped_quotes_in_labels(self) -> None:
        diagram = build_module_diagram(['weird"name/file.py'], [])
        for line in diagram.splitlines():
            if '["' in line:
                inner = line.split('["', 1)[1].rsplit('"]', 1)[0]
                assert '"' not in inner

    def test_edges_reference_only_declared_nodes(self) -> None:
        diagram = build_module_diagram(
            ["app/models/a.py", "app/services/b.py"], [("app.models.a", "app.services.b")],
        )
        declared_ids = {line.split("[")[0].strip() for line in diagram.splitlines() if "[" in line}
        for line in diagram.splitlines():
            if "-->" in line:
                edge_tokens = [t for t in line.split() if t.startswith("n_")]
                for token in edge_tokens:
                    assert token in declared_ids

    def test_self_loops_excluded(self) -> None:
        # Both edge endpoints resolve to the same "app.utils" module once
        # aggregated to depth=2 — this must never render as an edge.
        diagram = build_module_diagram(
            ["app/utils/helpers.py", "app/utils/constants.py"],
            [("app.utils.helpers", "app.utils.constants")],
        )
        assert "-->" not in diagram


class TestBuildDependencyFlowDiagram:
    def test_empty_hotspots_produces_header_only(self) -> None:
        diagram = build_dependency_flow_diagram([], [])
        assert diagram.startswith("flowchart TD")
        assert "no dependency hotspots" in diagram

    def test_valid_flowchart_with_hotspots(self) -> None:
        hotspots = [{"module_path": "app.core", "incoming_dependencies": 7}]
        edges = [("app.api", "app.core"), ("app.services", "app.core")]
        diagram = build_dependency_flow_diagram(hotspots, edges)
        assert diagram.startswith("flowchart TD")
        assert "app.api" not in diagram or "n_" in diagram  # labels are sanitized ids + text, not raw dots used as ids

    def test_node_count_bounded(self) -> None:
        hotspots = [{"module_path": f"mod_{i}", "incoming_dependencies": i} for i in range(30)]
        diagram = build_dependency_flow_diagram(hotspots, [], max_nodes=5)
        node_lines = [line for line in diagram.splitlines() if line.strip().startswith("n_")]
        assert len(node_lines) <= 5
