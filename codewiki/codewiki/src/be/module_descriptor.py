"""Token-budgeted module descriptor encoder for map-reduce overview generation.

Builds the per-module evidence block fed to the map-step LLM call
(overview_mapreduce.py). Per OVERVIEW_QUALITY_SPEC.md section 4.1, this is a
signature-based API surface digest — public class/method/function
signatures plus the first line of each docstring, cross-module edge
weights, and the module's own docstring — not raw file bodies, and not the
name-only "public surface" listing this file used to build.

Ranking for which symbols make the cut (spec 4.1's rule, exactly): each
module's own public symbols, ranked by (1) how many OTHER modules reference
them, (2) the line count of the file they're defined in, (3) name,
descending/descending/ascending. Capped at MAX_SYMBOLS_PER_MODULE, then
further limited by MODULE_EVIDENCE_BUDGET tokens on a per-symbol basis (not
an all-or-nothing block) — the highest-ranked symbols survive a tight
budget, a "top K of N" note reports the rest rather than silently dropping.

Known fidelity limit, not silently worked around: Node.parameters (see
dependency_analyzer/models/core.py) is a bare list of parameter NAMES —
no type annotations, no defaults, no return type — and no language
analyzer in this fork exposes an export/visibility flag. So "signature"
here means `def name(params)` / `class Name(Bases):` at name-level fidelity,
and "public" means "does not start with `_`" (the one convention that
means roughly the same thing in every language this fork parses). Real
typed signatures and real per-language visibility would need changes to
every analyzer in dependency_analyzer/analyzers/, not this file.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Set

from codewiki.src import config as _config
from codewiki.src.be import doc_harvester
from codewiki.src.be.dependency_analyzer.models.core import Node
from codewiki.src.be.repo_facts import EntryPoint, _scan_code_entry_points
from codewiki.src.be.utils import count_tokens

# Re-exported under their historical names in this file so existing callers
# and tests that read module_descriptor.MODULE_EVIDENCE_BUDGET keep working;
# the values themselves now live in config.py (see its comments — this
# replaces the old, locally-defined MODULE_DESCRIPTOR_BUDGET env var).
MODULE_EVIDENCE_BUDGET = _config.MODULE_EVIDENCE_BUDGET
MAX_SYMBOLS_PER_MODULE = _config.MAX_SYMBOLS_PER_MODULE

_SYMBOL_COMPONENT_TYPES = ("class", "function", "method")
_MAX_EDGES = 8
_MAX_HEADER_FILES = 10


# ---------------------------------------------------------------------
# Symbol-level helpers
# ---------------------------------------------------------------------


def _is_public(node: Node) -> bool:
    """Skip anything whose bare name (the segment after the last '.', so a
    method's own name rather than its class's) starts with `_`. See module
    docstring: this is the only visibility signal available across every
    language this fork parses."""
    bare = node.name.split(".")[-1]
    return not bare.startswith("_")


_SLICE_MAX_LINES = 3
_SLICE_MAX_CHARS = 200


def slice_signature(file_path: Path, start_line: int, language: Optional[str]) -> Optional[str]:
    """Return a symbol's declaration exactly as written in the source file —
    full fidelity (type hints, defaults, return annotations, base classes)
    that Node.parameters alone cannot carry, since Node.parameters is bare
    argument names only (see dependency_analyzer/analyzers/python.py).

    Reads from `start_line` (Node always exposes one — see
    dependency_analyzer/models/core.py's `start_line: int = 0` — this
    checks it rather than assuming), tracks `([{`/`)]}` depth, and stops at
    the first `:` at depth 0 for Python or the first `{`/`;` at depth 0 for
    every other language. Never raises and never guesses: capped at 3
    lines / 200 characters, and if no terminator is found inside that
    window the caller falls back to the weaker reconstructed
    `def name(params)` form — degraded fidelity for that one symbol, not a
    failure.
    """
    if not start_line or start_line < 1:
        return None
    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError:
        return None
    if start_line > len(lines):
        return None

    is_python = (language or "").lower() == "python"
    window_text = "".join(lines[start_line - 1 : start_line - 1 + _SLICE_MAX_LINES])
    window_text = window_text[: _SLICE_MAX_CHARS + 1]

    depth = 0
    terminator_pos: Optional[int] = None
    for i, ch in enumerate(window_text):
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth = max(0, depth - 1)
        elif depth == 0 and ((is_python and ch == ":") or (not is_python and ch in "{;")):
            terminator_pos = i
            break

    if terminator_pos is None or terminator_pos >= _SLICE_MAX_CHARS:
        return None

    raw = window_text[:terminator_pos]  # excludes the terminator itself
    collapsed = " ".join(raw.split())
    if not collapsed:
        return None

    if is_python and start_line >= 2:
        prev_line = lines[start_line - 2].strip()
        if prev_line.startswith("@"):
            collapsed = f"{prev_line} {collapsed}"

    return collapsed


_QUALIFIED_NAME_RE_CACHE: Dict[str, "re.Pattern[str]"] = {}


def _restore_qualified_name(sliced: str, node: Node) -> str:
    """A verbatim slice reads the bare name as written in source
    ("def greet(...)"), but this digest lists symbols in one flat ranking,
    not grouped under their class — a reader needs Node.name's dotted
    qualification ("Greeter.greet") to know which class a method belongs
    to. Substitutes only the declared name, leaving every type hint,
    default and decorator the slice captured untouched. No-ops (returns
    the slice unmodified) if the bare name can't be found, rather than
    risking a wrong substitution."""
    if "." not in node.name:
        return sliced
    bare = node.name.split(".")[-1]
    keyword = "class" if node.component_type == "class" else "def"
    pattern = _QUALIFIED_NAME_RE_CACHE.setdefault(
        f"{keyword}:{bare}", re.compile(rf"\b{keyword}\s+{re.escape(bare)}\b")
    )
    new_sliced, count = pattern.subn(f"{keyword} {node.name}", sliced, count=1)
    return new_sliced if count else sliced


def _reconstructed_signature(node: Node) -> str:
    """Name-level fallback when slice_signature can't cleanly extract a
    declaration (file unreadable, or no terminator within the 3-line/200
    char cap) — no type hints, no defaults, no return type, but never a
    missing symbol."""
    if node.component_type == "class":
        short = node.name.split(".")[-1]
        if node.base_classes:
            return f"class {short}({', '.join(node.base_classes)}):"
        return f"class {short}:"
    params = ", ".join(node.parameters or [])
    return f"def {node.name}({params})"


_PY_EXTENSIONS = (".py", ".pyi")


def _effective_language(node: Node) -> Optional[str]:
    """Node.language turned out unreliable in this pipeline: a hand-checked
    fixture came back None for every node — function, method and class
    alike — regardless of file. Whatever aggregation step assembles the
    final `components` dict (past the per-file analyzers, which do set it —
    see dependency_analyzer/analyzers/python.py's `language="python"`)
    drops the field before it reaches callers like this one. Pre-existing,
    not introduced by this file; file extension is a more reliable signal
    for the one thing slice_signature needs (Python vs everything else)
    regardless of whether or when that gap gets fixed upstream."""
    if node.language:
        return node.language
    if node.relative_path.endswith(_PY_EXTENSIONS):
        return "python"
    return None


def _signature_for(node: Node, repo_path: str) -> str:
    abs_path = os.path.join(repo_path, node.relative_path)
    sliced = slice_signature(Path(abs_path), node.start_line, _effective_language(node))
    if sliced:
        return _restore_qualified_name(sliced, node)
    return _reconstructed_signature(node)


def _docstring_first_line(node: Node) -> str:
    if not node.has_docstring or not node.docstring:
        return ""
    for line in node.docstring.strip().splitlines():
        line = line.strip()
        if line:
            return line
    return ""


def _cross_module_reference_counts(
    components: Dict[str, Node], file_to_module: Dict[str, str]
) -> Dict[str, int]:
    """How many depends_on edges point at each component id from a
    component in a DIFFERENT module. Distinct from the global `in_degree`
    the caller also passes in (used elsewhere for doc_harvester's top-class
    pick), which counts same-module references too — spec 4.1 explicitly
    wants "referenced-by-other-modules" as the primary ranking signal."""
    counts: Dict[str, int] = {}
    for node in components.values():
        source_module = file_to_module.get(node.relative_path)
        for dep_id in node.depends_on:
            dep = components.get(dep_id)
            if dep is None:
                continue
            target_module = file_to_module.get(dep.relative_path)
            if target_module is None or target_module == source_module:
                continue
            counts[dep_id] = counts.get(dep_id, 0) + 1
    return counts


def _file_line_counts(repo_path: str, relative_paths: Set[str]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for rel_path in relative_paths:
        abs_path = os.path.join(repo_path, rel_path)
        try:
            with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
                counts[rel_path] = sum(1 for _ in f)
        except OSError:
            counts[rel_path] = 0
    return counts


def _rank_public_symbols(
    module_files: List[str],
    components: Dict[str, Node],
    cross_module_refs: Dict[str, int],
    file_lines: Dict[str, int],
) -> List[Node]:
    """This module's own public classes/functions/methods, ranked per spec
    4.1: cross-module reference count desc, then defining-file size desc,
    then name asc."""
    file_set = set(module_files)
    candidates = [
        node
        for node in components.values()
        if node.relative_path in file_set
        and node.component_type in _SYMBOL_COMPONENT_TYPES
        and _is_public(node)
    ]
    candidates.sort(
        key=lambda n: (
            -cross_module_refs.get(n.id, 0),
            -file_lines.get(n.relative_path, 0),
            n.name,
        )
    )
    return candidates


def _most_referenced_function(
    module_files: List[str], components: Dict[str, Node], cross_module_refs: Dict[str, int]
) -> Optional[Node]:
    """The single most-referenced function/method in this module, for the
    "only if budget remains, append one function body" rule."""
    file_set = set(module_files)
    candidates = [
        node
        for node in components.values()
        if node.relative_path in file_set
        and node.component_type in ("function", "method")
        and _is_public(node)
        and node.source_code
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda n: (-cross_module_refs.get(n.id, 0), n.name))
    return candidates[0]


# ---------------------------------------------------------------------
# Module-level edges
# ---------------------------------------------------------------------


def _module_edge_weights(
    module_name: str,
    module_files: List[str],
    components: Dict[str, Node],
    file_to_module: Dict[str, str],
) -> Dict[str, int]:
    """Raw depends_on walk: how many links run from this module's own
    components into each other module. Shared by _format_outgoing_edges
    below (this module's "IMPORTS FROM" line) and
    overview_mapreduce.py's deterministic architecture-diagram edge
    aggregation, and repo_facts.py's module graph — the same traversal,
    not reimplemented three times. Signature and behavior unchanged from
    before this file's evidence-digest rewrite; do not change this without
    checking those two other callers."""
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


def _incoming_module_edges(
    module_name: str,
    module_files: List[str],
    components: Dict[str, Node],
    file_to_module: Dict[str, str],
) -> Dict[str, int]:
    """Mirror of _module_edge_weights, inverted: for each OTHER module, how
    many depends_on links run from its components into this module's
    files. Spec 4.1's "IMPORTED BY"."""
    file_set = set(module_files)
    weights: Dict[str, int] = {}
    for node in components.values():
        source_module = file_to_module.get(node.relative_path)
        if source_module is None or source_module == module_name:
            continue
        for dep_id in node.depends_on:
            dep = components.get(dep_id)
            if dep is None or dep.relative_path not in file_set:
                continue
            weights[source_module] = weights.get(source_module, 0) + 1
    return weights


def _format_edges(weights: Dict[str, int], heading: str) -> str:
    ranked = sorted(weights.items(), key=lambda kv: (-kv[1], kv[0]))
    shown = ranked[:_MAX_EDGES]
    label = heading if len(ranked) <= len(shown) else f"{heading} (top {len(shown)} of {len(ranked)})"
    pairs = ", ".join(f"{name} ({count})" for name, count in shown)
    return f"{label}: {pairs}" if pairs else f"{label}: (none)"


_MAX_ENTRY_POINTS = 10
_MAX_CONSTANTS_PER_MODULE = 15
_CONSTANT_RE = re.compile(r"^([A-Z][A-Z0-9_]{2,})\s*=\s*(.{0,80})")
_SECRET_NAME_MARKERS = ("KEY", "TOKEN", "SECRET", "PASSWORD")


def _format_entry_points(entry_points: List[EntryPoint]) -> str:
    """Sourced from repo_facts._scan_code_entry_points — the same
    regex/AST detector repo_facts.extract_repo_facts() itself uses, not
    the old evidence_extractor filename allowlist (main.py/app.py/...)
    this section used to read, which only ever named a file, never a real
    pattern match."""
    shown = entry_points[:_MAX_ENTRY_POINTS]
    lines = []
    for ep in shown:
        line = f"- {ep.kind}: {ep.name} ({ep.file}:{ep.line})"
        if ep.detail and ep.detail != ep.name:
            line += f" — {ep.detail}"
        lines.append(line)
    heading = "ENTRY POINTS"
    if len(entry_points) > len(shown):
        heading += f" (top {len(shown)} of {len(entry_points)})"
    return heading + "\n" + "\n".join(lines)


def _extract_constants(repo_path: str, module_files: List[str]) -> List[str]:
    """Module-level `NAME = value` constants at zero indentation — cheap
    regex, no AST, Python-shaped (works incidentally for JS/Java/Scala
    lines that happen to start with the identifier, but this is
    deliberately not a per-language parser — see OVERVIEW_QUALITY_SPEC.md
    Part 1 decision #2). A name containing KEY/TOKEN/SECRET/PASSWORD is
    reported with its value redacted — the name alone ("ATLASCLOUD_API_KEY
    = <redacted>") is still real, useful evidence."""
    found: List[str] = []
    for rel_path in module_files:
        abs_path = os.path.join(repo_path, rel_path)
        try:
            with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read(200_000)
        except OSError:
            continue
        for line in content.splitlines():
            match = _CONSTANT_RE.match(line)
            if not match:
                continue
            name, value = match.group(1), match.group(2).rstrip()
            if any(marker in name.upper() for marker in _SECRET_NAME_MARKERS):
                found.append(f"{name} = <redacted>")
            else:
                found.append(f"{name} = {value}")
    return found


def _module_docstring(repo_path: str, module_files: List[str]) -> str:
    """This module's own docstring, verbatim — not doc_harvester's
    multi-source, 120-token-capped "authored text" fallback chain (README
    paragraph / module docstring / top-class docstring / manifest
    description), which is a different, broader concept used elsewhere.
    Spec 4.1's "MODULE DOCSTRING" section is specifically the module's own
    docstring, so this calls doc_harvester's single Python-AST docstring
    harvester directly rather than the multi-source wrapper."""
    return doc_harvester._harvest_module_docstring(repo_path, module_files) or ""


# ---------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------


def build_module_descriptor(
    module_name: str,
    module_files: List[str],
    components: Dict[str, Node],
    in_degree: Dict[str, int],
    file_to_module: Dict[str, str],
    repo_path: str,
    budget: int | None = None,
) -> str:
    """Encode one module into a token-budgeted, signature-based evidence
    digest for the map step (OVERVIEW_QUALITY_SPEC.md section 4.1).

    Priority order — header is always included; everything after is added
    only while it still fits, so the highest-value content survives a
    tight budget: header -> public surface (signatures + first docstring
    line, added symbol by symbol, not as one all-or-nothing block, since
    MAX_SYMBOLS_PER_MODULE can list more symbols than MODULE_EVIDENCE_BUDGET
    tokens allow) -> constants -> module docstring -> IMPORTS FROM ->
    IMPORTED BY -> entry points -> (only if budget remains) the single
    most cross-module-referenced function's full body. Every truncated
    list reports "top N of M" rather than silently dropping the rest;
    constants is the one section still dropped as a whole block under a
    tight budget, per spec.

    `in_degree` (global, includes same-module references) is accepted for
    backward-compatible signature parity with the map-reduce caller and is
    no longer used for ranking here — see _cross_module_reference_counts,
    which computes the cross-module-only count spec 4.1 actually asks for.
    """
    if budget is None:
        budget = MODULE_EVIDENCE_BUDGET

    file_lines = _file_line_counts(repo_path, set(module_files))
    cross_module_refs = _cross_module_reference_counts(components, file_to_module)

    parts: List[str] = []
    running_tokens = 0

    def try_add(text: str) -> bool:
        nonlocal running_tokens
        block_tokens = count_tokens(text)
        if running_tokens + block_tokens > budget:
            return False
        parts.append(text)
        running_tokens += block_tokens
        return True

    shown_files = module_files[:_MAX_HEADER_FILES]
    files_desc = ", ".join(f"{f} ({file_lines.get(f, 0)} loc)" for f in shown_files)
    if len(module_files) > len(shown_files):
        files_desc += f" (top {len(shown_files)} of {len(module_files)})"
    header = f"MODULE: {module_name}\nFILES: {files_desc}"
    parts.append(header)
    running_tokens += count_tokens(header)

    ranked_symbols = _rank_public_symbols(module_files, components, cross_module_refs, file_lines)
    capped_symbols = ranked_symbols[:MAX_SYMBOLS_PER_MODULE]
    if capped_symbols:
        shown_count = 0
        surface_lines: List[str] = []
        for node in capped_symbols:
            sig = _signature_for(node, repo_path)
            doc = _docstring_first_line(node)
            line = f'    {sig}\n        """{doc}"""' if doc else f"    {sig}"
            block_tokens = count_tokens(line) + 1  # +1 for the joining newline
            if running_tokens + block_tokens > budget:
                break
            surface_lines.append(line)
            running_tokens += block_tokens
            shown_count += 1
        if surface_lines:
            heading = (
                f"\nPUBLIC SURFACE (top {shown_count} of {len(ranked_symbols)} "
                "by cross-module references)"
                if shown_count < len(ranked_symbols)
                else "\nPUBLIC SURFACE"
            )
            parts.append(heading + "\n" + "\n".join(surface_lines))

    constants = _extract_constants(repo_path, module_files)
    if constants:
        shown_constants = constants[:_MAX_CONSTANTS_PER_MODULE]
        heading = (
            f"\nCONSTANTS (top {len(shown_constants)} of {len(constants)})"
            if len(constants) > len(shown_constants)
            else "\nCONSTANTS"
        )
        try_add(heading + "\n" + "\n".join(shown_constants))

    module_doc = _module_docstring(repo_path, module_files)
    if module_doc:
        try_add(f"\nMODULE DOCSTRING\n{module_doc}")

    outgoing = _module_edge_weights(module_name, module_files, components, file_to_module)
    if outgoing:
        try_add("\n" + _format_edges(outgoing, "IMPORTS FROM"))

    incoming = _incoming_module_edges(module_name, module_files, components, file_to_module)
    if incoming:
        try_add("\n" + _format_edges(incoming, "IMPORTED BY"))

    module_entry_points = _scan_code_entry_points(repo_path, module_files)
    if module_entry_points:
        try_add("\n" + _format_entry_points(module_entry_points))

    top_function = _most_referenced_function(module_files, components, cross_module_refs)
    if top_function is not None:
        body = top_function.source_code or ""
        try_add(f"\nMOST-REFERENCED FUNCTION BODY ({top_function.name})\n{body}")

    return "\n".join(parts)
