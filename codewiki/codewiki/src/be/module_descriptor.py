"""Token-budgeted module descriptor encoder for map-reduce overview generation.

Builds the per-module text fed to a single map-step LLM call. Follows
evidence_extractor.py's try_add() budget-tracking pattern exactly (a running
token count checked against a cap before each section is committed), and
reuses its signal-scanning and entry-point detection rather than
reimplementing them — same technique, scoped to one module's files instead
of the whole repository.
"""

from __future__ import annotations

import os
from typing import Dict, List, Tuple

from codewiki.src.be import doc_harvester
from codewiki.src.be.dependency_analyzer.models.core import Node
from codewiki.src.be.evidence_extractor import _ENTRYPOINT_NAMES, _read_capped, _scan_signals
from codewiki.src.be.utils import count_tokens

MODULE_DESCRIPTOR_BUDGET = int(os.getenv("MODULE_DESCRIPTOR_BUDGET", "1000"))
_MAX_PUBLIC_SURFACE = 15
_MAX_EDGES = 8
_MAX_IO_FACTS = 10
_MAX_HEADER_FILES = 10
_IO_SCAN_FILE_SIZE_CAP = 200_000


def _public_surface(
    module_files: List[str], components: Dict[str, Node], in_degree: Dict[str, int]
) -> Tuple[List[str], int]:
    """Classes/functions defined in this module, ranked by global in-degree
    (how much the rest of the repository depends on them) — the module's
    actual public surface, not just a dump of everything in these files."""
    file_set = set(module_files)
    candidates = [
        node
        for node in components.values()
        if node.relative_path in file_set and node.component_type in ("class", "function")
    ]
    candidates.sort(key=lambda n: in_degree.get(n.id, 0), reverse=True)
    # get_display_name() already includes the component_type prefix
    # ("function foo", "class Bar") — do not prepend it again.
    lines = [
        f"{node.get_display_name()} ({node.relative_path}) "
        f"— {in_degree.get(node.id, 0)} reference(s)"
        for node in candidates[:_MAX_PUBLIC_SURFACE]
    ]
    return lines, len(candidates)


def _module_edge_weights(
    module_name: str,
    module_files: List[str],
    components: Dict[str, Node],
    file_to_module: Dict[str, str],
) -> Dict[str, int]:
    """Raw depends_on walk: how many links run from this module's own
    components into each other module. Shared by _weighted_edges below (the
    "Depends on" section fed to the map step) and
    overview_mapreduce.py's deterministic architecture-diagram edge
    aggregation — the same traversal, not reimplemented twice."""
    file_set = set(module_files)
    weights: Dict[str, int] = {}
    for node in components.values():
        if node.relative_path not in file_set:
            continue
        for dep_id in node.depends_on:
            dep = components.get(dep_id)
            if dep is None:
                continue
            target_module = file_to_module.get(dep.relative_path)
            if target_module is None or target_module == module_name:
                continue
            weights[target_module] = weights.get(target_module, 0) + 1
    return weights


def _weighted_edges(
    module_name: str,
    module_files: List[str],
    components: Dict[str, Node],
    file_to_module: Dict[str, str],
) -> Tuple[List[str], int]:
    """Cross-module dependency weights: how many depends_on links run from
    this module's own components into each other module."""
    weights = _module_edge_weights(module_name, module_files, components, file_to_module)
    ranked = sorted(weights.items(), key=lambda kv: kv[1], reverse=True)
    lines = [f"-> {name} ({count} reference(s))" for name, count in ranked[:_MAX_EDGES]]
    return lines, len(ranked)


def _io_facts(repo_path: str, module_files: List[str]) -> Tuple[List[str], int]:
    findings: List[str] = []
    for rel_path in module_files:
        abs_path = os.path.join(repo_path, rel_path)
        try:
            if os.path.getsize(abs_path) > _IO_SCAN_FILE_SIZE_CAP:
                continue
        except OSError:
            continue
        content, _ = _read_capped(abs_path, cap_chars=20_000)
        findings.extend(_scan_signals(rel_path, content))
    return findings[:_MAX_IO_FACTS], len(findings)


def _entrypoints(module_files: List[str]) -> List[str]:
    return [f for f in module_files if os.path.basename(f).lower() in _ENTRYPOINT_NAMES]


def build_module_descriptor(
    module_name: str,
    module_files: List[str],
    components: Dict[str, Node],
    in_degree: Dict[str, int],
    file_to_module: Dict[str, str],
    repo_path: str,
    budget: int | None = None,
) -> str:
    """Encode one module into a token-budgeted descriptor for the map step.

    Priority order — header is always included; everything after is added
    only while it still fits, so the highest-value content survives a tight
    budget: header -> authored text -> public surface (by in-degree) ->
    weighted cross-module edges -> I/O facts -> entry points. Every
    truncated list reports "top N of M" rather than silently dropping the
    rest.
    """
    if budget is None:
        budget = MODULE_DESCRIPTOR_BUDGET

    parts: List[str] = []
    running_tokens = 0

    def try_add(text: str) -> None:
        nonlocal running_tokens
        block_tokens = count_tokens(text)
        if running_tokens + block_tokens > budget:
            return
        parts.append(text)
        running_tokens += block_tokens

    shown_files = module_files[:_MAX_HEADER_FILES]
    header = f"## Module: {module_name}\nFiles ({len(module_files)}): " + ", ".join(shown_files)
    if len(module_files) > len(shown_files):
        header += f" (top {len(shown_files)} of {len(module_files)})"
    parts.append(header)
    running_tokens += count_tokens(header)

    authored = doc_harvester.harvest_authored_text(repo_path, module_files, components, in_degree)
    if authored:
        try_add(f"\n### Authored description\n{authored}")

    surface_lines, surface_total = _public_surface(module_files, components, in_degree)
    if surface_lines:
        shown = len(surface_lines)
        heading = (
            f"\n### Public surface (top {shown} of {surface_total} by in-degree)"
            if surface_total > shown
            else "\n### Public surface"
        )
        try_add(heading + "\n" + "\n".join(f"- {line}" for line in surface_lines))

    edge_lines, edge_total = _weighted_edges(module_name, module_files, components, file_to_module)
    if edge_lines:
        shown = len(edge_lines)
        heading = (
            f"\n### Depends on (top {shown} of {edge_total} modules)"
            if edge_total > shown
            else "\n### Depends on"
        )
        try_add(heading + "\n" + "\n".join(edge_lines))

    io_lines, io_total = _io_facts(repo_path, module_files)
    if io_lines:
        shown = len(io_lines)
        heading = (
            f"\n### I/O and integration signals (top {shown} of {io_total})"
            if io_total > shown
            else "\n### I/O and integration signals"
        )
        try_add(heading + "\n" + "\n".join(f"- {line}" for line in io_lines))

    entry_lines = _entrypoints(module_files)
    if entry_lines:
        try_add("\n### Entry points\n" + "\n".join(f"- {line}" for line in entry_lines))

    return "\n".join(parts)
