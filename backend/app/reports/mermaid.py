"""Deterministic Mermaid diagram builders (spec §15) — the graph data is the source of truth.

Both builders here only ever draw edges/nodes that exist in real
``relationships``/``repository_intelligence`` data (Sprint 2A/2B,
unmodified). The AI synthesis stage (``reports/synthesis.py``) may only
attach human-readable labels/descriptions on top of an already-built
diagram — it never constructs or edits Mermaid source itself, so it
cannot invent an edge or node (ADR-024).
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

_UNSAFE_ID_CHARS = re.compile(r"[^A-Za-z0-9_]")
_KNOWN_FILE_EXTENSIONS = frozenset(
    {
        "py", "pyi", "js", "jsx", "mjs", "cjs", "ts", "tsx", "java", "kt", "go", "rs", "rb", "php", "c", "h",
        "cpp", "cc", "cs", "json", "yaml", "yml", "toml", "md", "mdx", "txt", "cfg", "ini", "sql", "html",
        "htm", "css", "xml", "sh",
    }
)
_LABEL_ESCAPE = {
    '"': "&quot;", "[": "&#91;", "]": "&#93;", "|": "&#124;", "{": "&#123;", "}": "&#125;", "<": "&lt;", ">": "&gt;",
}


@dataclass(frozen=True)
class DependencyEdge:
    """One real ``depends_on``-style edge, at whatever granularity the caller resolved it to."""

    source: str
    target: str
    weight: int = 1


def _sanitize_node_id(raw: str, *, used_ids: dict[str, str]) -> str:
    """Slugify an arbitrary module/file path into a safe, collision-free Mermaid node id.

    Args:
        raw: The original identifier (a module path, file path, or
            symbol name) to derive an id from.
        used_ids: A mapping of ``raw -> assigned id`` already produced
            in this diagram, threaded through by the caller so repeated
            calls for the same ``raw`` value return the same id, and a
            distinct ``raw`` value that happens to slugify identically
            gets a disambiguating numeric suffix instead of silently
            colliding with (and overwriting) another node.

    Returns:
        A Mermaid-safe node id: matches ``^n_[A-Za-z0-9_]+$``.
    """
    if raw in used_ids:
        return used_ids[raw]
    slug = _UNSAFE_ID_CHARS.sub("_", raw).strip("_") or "node"
    if slug[0].isdigit():
        slug = f"n_{slug}"
    else:
        slug = f"n_{slug}"
    candidate = slug
    suffix = 1
    existing_ids = set(used_ids.values())
    while candidate in existing_ids:
        suffix += 1
        candidate = f"{slug}_{suffix}"
    used_ids[raw] = candidate
    return candidate


def _sanitize_mermaid_label(raw: str, *, max_len: int = 60) -> str:
    """Escape characters that would break Mermaid label syntax and bound label length.

    Args:
        raw: The human-readable text to display on a node/edge.
        max_len: Maximum characters kept before truncation.

    Returns:
        A label safe to place inside ``["..."]``-style Mermaid syntax —
        quotes, brackets, pipes, and angle brackets are escaped, never
        left raw.
    """
    text = raw if len(raw) <= max_len else raw[: max_len - 1] + "…"
    for char, escaped in _LABEL_ESCAPE.items():
        text = text.replace(char, escaped)
    return text


def module_of(identifier: str, *, depth: int = 2) -> str:
    """Aggregate a file/module/symbol identifier up to a coarse module label.

    Args:
        identifier: A dotted module path (e.g. ``app.models.repository``,
            Sprint 2B's ``module_path_from_relative_path`` format), a
            slash-separated file path, or a dotted qualified symbol name.
        depth: How many leading path segments to keep.

    Returns:
        The joined first ``depth`` segments, e.g. ``app.models`` — the
        "top-level directory/module granularity" spec §4 asks diagrams
        to use, computed the same way regardless of whether the
        identifier was dot- or slash-delimited.
    """
    normalized = identifier.replace("\\", "/")
    # Strip a recognized file extension from the final path segment
    # first (mirroring Sprint 2B's module_path_from_relative_path
    # convention) — otherwise a root-level file like "main.py" would
    # split into two fake segments ("main", "py") instead of one.
    # Only strip *known* extensions so a dotted qualified name like
    # "app.models.User" is never mistaken for a file (".User" is not a
    # recognized extension).
    head, _, tail = normalized.rpartition(".")
    if head and tail.lower() in _KNOWN_FILE_EXTENSIONS:
        normalized = head
    normalized = normalized.replace(".", "/")
    segments = [segment for segment in normalized.split("/") if segment]
    if not segments:
        return "root"
    return ".".join(segments[:depth]) if len(segments) > 1 else segments[0]


def build_module_diagram(
    file_paths: list[str], dependency_edges: list[tuple[str, str]], *, max_nodes: int = 25,
) -> str:
    """Build a top-level module/directory diagram from real file and dependency-edge data.

    Args:
        file_paths: Every file path in the repository (used to
            establish the module vocabulary, so a module with files but
            zero resolved dependency edges still appears as a node).
        dependency_edges: Real ``(source_module_path, target_module_path)``
            pairs from ``depends_on``-type relationships (Sprint 2B).
        max_nodes: Maximum module nodes to render — the top modules by
            total edge weight (in + out) are kept; this bounds diagram
            size for large repositories regardless of how many
            directories they contain.

    Returns:
        A valid ``flowchart TD`` Mermaid diagram string. If the
        repository has more distinct modules than ``max_nodes``, a
        trailing comment note marks the diagram as partial rather than
        silently dropping modules without saying so (spec §4).
    """
    modules = {module_of(path) for path in file_paths}
    edge_counter: Counter[tuple[str, str]] = Counter()
    for source, target in dependency_edges:
        source_module, target_module = module_of(source), module_of(target)
        if source_module == target_module:
            continue
        modules.add(source_module)
        modules.add(target_module)
        edge_counter[(source_module, target_module)] += 1

    weight_by_module: Counter[str] = Counter()
    for (source_module, target_module), weight in edge_counter.items():
        weight_by_module[source_module] += weight
        weight_by_module[target_module] += weight

    kept_modules = sorted(modules, key=lambda m: (-weight_by_module[m], m))[:max_nodes]
    kept_set = set(kept_modules)
    partial = len(modules) > len(kept_modules)

    used_ids: dict[str, str] = {}
    lines = ["flowchart TD"]
    for module in kept_modules:
        node_id = _sanitize_node_id(module, used_ids=used_ids)
        lines.append(f'    {node_id}["{_sanitize_mermaid_label(module)}"]')
    for (source_module, target_module), weight in sorted(edge_counter.items(), key=lambda kv: -kv[1]):
        if source_module not in kept_set or target_module not in kept_set:
            continue
        source_id = _sanitize_node_id(source_module, used_ids=used_ids)
        target_id = _sanitize_node_id(target_module, used_ids=used_ids)
        label = f"{weight}x" if weight > 1 else ""
        lines.append(f"    {source_id} -->|{label}| {target_id}" if label else f"    {source_id} --> {target_id}")

    if partial:
        lines.append(
            f"    %% partial: {len(modules)} modules detected, showing top {len(kept_modules)} by dependency weight"
        )
    return "\n".join(lines)


def build_dependency_flow_diagram(
    hotspots: list[dict], dependency_edges: list[tuple[str, str]], *, max_nodes: int = 15,
) -> str:
    """Build a dependency-flow diagram centered on real dependency hotspots.

    Args:
        hotspots: ``RepositoryIntelligence.dependency_hotspots`` rows —
            ``[{"module_path": str, "incoming_dependencies": int}, ...]``,
            already computed deterministically by Sprint 2B.
        dependency_edges: Real ``(source_module_path, target_module_path)``
            pairs from ``depends_on``-type relationships.
        max_nodes: Maximum nodes to render (hotspots plus their direct
            neighbors), highest incoming-dependency-count first.

    Returns:
        A valid ``flowchart TD`` Mermaid diagram string highlighting
        the top dependency hotspots and their real, resolved
        callers/dependents. Empty (header-only) if there are no
        hotspots or edges to draw — never a fabricated diagram.
    """
    lines = ["flowchart TD"]
    if not hotspots:
        lines.append("    %% no dependency hotspots available")
        return "\n".join(lines)

    top_hotspots = sorted(hotspots, key=lambda h: -h.get("incoming_dependencies", 0))[:max_nodes]
    hotspot_paths = {h["module_path"] for h in top_hotspots}

    edges_touching_hotspots = [
        (source, target) for source, target in dependency_edges if source in hotspot_paths or target in hotspot_paths
    ]

    node_set = set(hotspot_paths)
    for source, target in edges_touching_hotspots:
        node_set.add(source)
        node_set.add(target)
    if len(node_set) > max_nodes:
        # Keep every hotspot plus as many of their direct neighbors as fit.
        neighbors = sorted(node_set - hotspot_paths)
        node_set = hotspot_paths | set(neighbors[: max(0, max_nodes - len(hotspot_paths))])

    used_ids: dict[str, str] = {}
    incoming_by_path = {h["module_path"]: h.get("incoming_dependencies", 0) for h in top_hotspots}
    for path in sorted(node_set):
        node_id = _sanitize_node_id(path, used_ids=used_ids)
        label = _sanitize_mermaid_label(path)
        if path in incoming_by_path:
            label = f"{label} ({incoming_by_path[path]} deps)"
        lines.append(f'    {node_id}["{label}"]')

    for source, target in edges_touching_hotspots:
        if source not in node_set or target not in node_set:
            continue
        source_id = _sanitize_node_id(source, used_ids=used_ids)
        target_id = _sanitize_node_id(target, used_ids=used_ids)
        lines.append(f"    {source_id} --> {target_id}")

    return "\n".join(lines)
