"""Map-reduce overview generation (OVERVIEW_MODE=mapreduce).

An alternative to generate_overview_only()'s single-call design (see
documentation_generator.py) — never modifies or replaces it, that remains
the default fast path. This groups the repository into directory-shaped
modules (module_grouper.py), builds a token-budgeted descriptor per module
(module_descriptor.py), maps each through one small-context LLM call
(num_ctx=2048, measured to stay on 100% GPU on this hardware — see
llm_services.py's context-size notes), then reduces the resulting
one-sentence module purposes into a single overview.md with one
larger-context call (num_ctx=8192).

No raw source code is ever sent to the map step — module_descriptor.py
encodes only deterministically-extracted facts. A module that fails to
produce a usable <PURPOSE> is reported as failed and excluded from the
reduce step; there is no fallback content for a failed module.

The architecture diagram inserted into the final overview is built entirely
by build_module_diagram() from aggregated dependency-graph edge counts — no
LLM is involved in producing it, and it is never fed back into any prompt.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from codewiki.src import config as _config
from codewiki.src.be import module_descriptor
from codewiki.src.be.backend import LLMBackend
from codewiki.src.be.dependency_analyzer.models.core import Node
from codewiki.src.be.module_grouper import ModuleGroup, group_modules
from codewiki.src.be.prompt_template import MAP_MODULE_PROMPT, REDUCE_OVERVIEW_PROMPT

logger = logging.getLogger(__name__)

# Separate model knobs from MAIN_MODEL/FALLBACK_MODEL_1/CLUSTER_MODEL —
# unset means "use whatever complete() defaults to" (config.main_model).
MAP_MODEL = os.getenv("MAP_MODEL") or None
REDUCE_MODEL = os.getenv("REDUCE_MODEL") or None
MAX_MODULES = int(os.getenv("MAX_MODULES", "40"))

# Map-step context window now lives in config.py as MAP_NUM_CTX (raised from
# a hardcoded 2048 to 4096 — see config.py's comment for why). The reduce
# step's 8192 stays local and hardcoded: it's still the deliberate "one
# large call" operating point this design exists to hit, and this session
# only touches the map step per OVERVIEW_QUALITY_SPEC.md sections 3/4.
_MAP_MAX_TOKENS = 400
_REDUCE_NUM_CTX = 8192
_REDUCE_MAX_TOKENS = int(os.getenv("OVERVIEW_MAX_OUTPUT_TOKENS", "1500"))

_TAG_PATTERNS = {
    "PURPOSE": re.compile(r"<PURPOSE>(.*?)</PURPOSE>", re.DOTALL),
    "DETAIL": re.compile(r"<DETAIL>(.*?)</DETAIL>", re.DOTALL),
    "SOURCES": re.compile(r"<SOURCES>(.*?)</SOURCES>", re.DOTALL),
}


@dataclass(frozen=True)
class MapResult:
    module: str
    purpose: str
    detail: str
    sources: str


@dataclass(frozen=True)
class MapReduceResult:
    overview_markdown: str
    mapped: List[MapResult]
    failed_modules: List[str]


def _extract_tag(text: str, tag: str) -> str:
    match = _TAG_PATTERNS[tag].search(text)
    return match.group(1).strip() if match else ""


def _compute_in_degree(components: Dict[str, Node]) -> Dict[str, int]:
    """Global in-degree per component id — how many other components'
    depends_on sets reference it. Shared by module_descriptor.py's public
    surface ranking and doc_harvester.py's top-class selection; computed
    once here rather than per module."""
    in_degree: Dict[str, int] = {}
    for node in components.values():
        for dep_id in node.depends_on:
            if dep_id in components:
                in_degree[dep_id] = in_degree.get(dep_id, 0) + 1
    return in_degree


def _map_module(
    backend: LLMBackend, module_name: str, descriptor_text: str, model: Optional[str]
) -> Optional[MapResult]:
    """One bounded map call for one module.

    Returns None — never fallback content — if the call raises or the
    response has no usable <PURPOSE>. Reuses documentation_generator's
    fence-stripper: models wrap answers in a stray code fence here too.
    """
    from codewiki.src.be.documentation_generator import _strip_outer_code_fence

    prompt = MAP_MODULE_PROMPT.format(module_name=module_name, module_descriptor=descriptor_text)
    try:
        response = backend.complete(
            prompt, temperature=0.0, max_tokens=_MAP_MAX_TOKENS, model=model,
            num_ctx=_config.MAP_NUM_CTX,
        )
    except Exception as e:
        logger.error("Map call failed for module %s: %s", module_name, e)
        return None

    response = _strip_outer_code_fence(response.strip())
    purpose = _extract_tag(response, "PURPOSE")
    if not purpose:
        logger.warning(
            "Map call for module %s produced no usable <PURPOSE>; reporting as failed.",
            module_name,
        )
        return None

    return MapResult(
        module=module_name,
        purpose=purpose,
        detail=_extract_tag(response, "DETAIL"),
        sources=_extract_tag(response, "SOURCES"),
    )


def _format_module_purposes(mapped: List[MapResult]) -> str:
    return "\n".join(f"- {m.module}: {m.purpose}" for m in mapped)


# Diagram default: an edge below this weight is one or two stray references,
# not an architectural relationship worth drawing. Passed through as
# build_module_diagram's min_weight parameter, not hardcoded inside it, so a
# caller with different data can still override it.
_DIAGRAM_MIN_EDGE_WEIGHT = 2

_SLUG_INVALID_RE = re.compile(r"[^0-9a-zA-Z]+")

_PURPOSE_HEADING_RE = re.compile(r"^##\s+(?:\d+[.)]\s*)?Purpose\b", re.MULTILINE | re.IGNORECASE)
_H2_HEADING_RE = re.compile(r"^##\s+", re.MULTILINE)

# Deterministic belt-and-braces: the reduce prompt now forbids image links
# outright, but a model can still ignore an instruction. Strip any leftover
# ![...](...) line rather than trust the prompt alone to prevent it.
_IMAGE_LINK_LINE_RE = re.compile(r"^\s*!\[.*\]\(.*\)\s*$", re.MULTILINE)


def _strip_image_links(markdown: str) -> str:
    """Remove any standalone image-link line (e.g. a placeholder like
    ![Architecture Diagram](#) the model can't actually back with an image)
    from reduce output before it reaches the final overview."""
    return _IMAGE_LINK_LINE_RE.sub("", markdown)


def _compute_module_edges(
    groups: List[ModuleGroup], components: Dict[str, Node], file_to_module: Dict[str, str]
) -> Dict[Tuple[str, str], int]:
    """Aggregate directed module-to-module dependency weights across every
    module, reusing module_descriptor._module_edge_weights — the exact same
    depends_on walk that feeds module_descriptor.py's "Depends on" section —
    rather than re-walking components/depends_on from scratch here. No LLM
    involved; purely a graph aggregation over already-computed data."""
    edges: Dict[Tuple[str, str], int] = {}
    for group in groups:
        weights = module_descriptor._module_edge_weights(
            group.name, group.files, components, file_to_module
        )
        for target, weight in weights.items():
            edges[(group.name, target)] = weight
    return edges


def _build_slug_map(modules: List[str]) -> Dict[str, str]:
    """Deterministic, unique, mermaid-safe id per module name. First
    occurrence of a collision keeps the bare slug; later ones get a
    numeric suffix — order is the caller's module list order, so this is
    reproducible run to run for the same input."""
    used: Dict[str, int] = {}
    slugs: Dict[str, str] = {}
    for name in modules:
        base = _SLUG_INVALID_RE.sub("_", name).strip("_").lower() or "root"
        if base[0].isdigit():
            base = f"m_{base}"
        count = used.get(base, 0)
        used[base] = count + 1
        slugs[name] = base if count == 0 else f"{base}_{count}"
    return slugs


def build_module_diagram(
    modules: List[str], edges: Dict[Tuple[str, str], int], min_weight: int = 2
) -> str:
    """Deterministic Mermaid architecture diagram from aggregated
    module-to-module dependency weights. No LLM anywhere in this — pure
    rendering of already-aggregated graph data.

    One node per module, labeled with its real name (never a placeholder
    like A/B/C). One directed edge per module pair whose combined
    depends_on weight is at least min_weight. Returns "" when nothing meets
    that threshold — callers must not insert an empty diagram.
    """
    qualifying = sorted(
        pair for pair, weight in edges.items() if weight >= min_weight
    )
    if not qualifying:
        return ""

    slugs = _build_slug_map(modules)
    lines = ["```mermaid", "graph LR"]
    for name in modules:
        label = name.replace('"', "'")
        lines.append(f'    {slugs[name]}["{label}"]')
    for src, dst in qualifying:
        if src not in slugs or dst not in slugs:
            continue
        lines.append(f"    {slugs[src]} --> {slugs[dst]}")
    lines.append("```")
    return "\n".join(lines)


def _insert_architecture_section(overview_markdown: str, diagram_block: str) -> str:
    """Insert a '## Architecture' heading plus diagram_block immediately
    after the overview's first (Purpose) section — tolerant of however the
    reduce model happens to title or number that heading, since that's
    reduce-model output, not something this code controls.

    Three-tier placement, first hit wins:
      1. Match a '## Purpose' heading — optionally numbered ('## 1.
         Purpose', '## 1) Purpose'), case-insensitive — and insert right
         before the next '##' heading after it.
      2. If no Purpose heading matches: insert immediately before the
         second '##' heading in the document. Purpose is reliably the
         first section regardless of what it's called or how it's
         numbered, so this still lands the diagram right after it.
      3. If the document has fewer than two '##' headings: append at the
         end — the diagram still needs a home somewhere.

    Never invents or alters any of the LLM-authored prose; only the
    placement strategy differs per tier. Which tier fired is logged at INFO
    so a placement miss is visible instead of silent.
    """
    if not diagram_block:
        return overview_markdown

    section = f"## Architecture\n\n{diagram_block}\n\n"

    purpose_match = _PURPOSE_HEADING_RE.search(overview_markdown)
    if purpose_match is not None:
        next_match = _H2_HEADING_RE.search(overview_markdown, purpose_match.end())
        insertion_point = next_match.start() if next_match else len(overview_markdown)
        logger.info("map-reduce: architecture diagram placement tier 1 (matched a Purpose heading)")
        return overview_markdown[:insertion_point] + section + overview_markdown[insertion_point:]

    headings = list(_H2_HEADING_RE.finditer(overview_markdown))
    if len(headings) >= 2:
        insertion_point = headings[1].start()
        logger.info(
            "map-reduce: architecture diagram placement tier 2 "
            "(no Purpose heading matched; inserted before the second ## heading)"
        )
        return overview_markdown[:insertion_point] + section + overview_markdown[insertion_point:]

    logger.info(
        "map-reduce: architecture diagram placement tier 3 "
        "(fewer than two ## headings found; appended at end)"
    )
    return overview_markdown.rstrip() + "\n\n" + section.rstrip() + "\n"


def run_mapreduce(
    config,
    backend: LLMBackend,
    components: Dict[str, Node],
    leaf_nodes: List[str],
    repo_name: str,
) -> MapReduceResult:
    """Group -> map -> reduce. Synchronous — complete() itself is sync (see
    backend.py); documentation_generator.py awaits the thin async wrapper
    around this, not this function itself.

    Raises if every module fails to map, or if the reduce call produces no
    usable overview — no fallback content at either stage.
    """
    from codewiki.src.be.documentation_generator import _strip_outer_code_fence

    files = sorted({n.relative_path for n in components.values()})
    groups = group_modules(files, max_modules=MAX_MODULES)
    if not groups:
        raise ValueError("No modules found to map — repository has no analyzable source files.")

    in_degree = _compute_in_degree(components)
    file_to_module = {f: g.name for g in groups for f in g.files}
    repo_path = config.repo_path

    logger.info(
        "map-reduce: %d module(s) from %d file(s) for %s", len(groups), len(files), repo_name
    )

    mapped: List[MapResult] = []
    failed: List[str] = []
    for i, group in enumerate(groups, start=1):
        descriptor_text = module_descriptor.build_module_descriptor(
            module_name=group.name,
            module_files=group.files,
            components=components,
            in_degree=in_degree,
            file_to_module=file_to_module,
            repo_path=repo_path,
        )
        result = _map_module(backend, group.name, descriptor_text, MAP_MODEL)
        if result is None:
            failed.append(group.name)
            logger.info("map-reduce: %d/%d FAILED: %s", i, len(groups), group.name)
            continue
        mapped.append(result)
        logger.info("map-reduce: %d/%d mapped: %s -> %s", i, len(groups), group.name, result.purpose)

    if not mapped:
        raise RuntimeError(
            f"All {len(groups)} module(s) failed to map — nothing to reduce. "
            f"Failed: {', '.join(failed)}"
        )
    if failed:
        logger.warning("map-reduce: %d/%d module(s) failed and are excluded from the reduce step: %s",
                        len(failed), len(groups), ", ".join(failed))

    module_purposes = _format_module_purposes(mapped)
    reduce_prompt = REDUCE_OVERVIEW_PROMPT.format(repo_name=repo_name, module_purposes=module_purposes)
    response = backend.complete(
        reduce_prompt,
        temperature=0.0,
        max_tokens=_REDUCE_MAX_TOKENS,
        model=REDUCE_MODEL,
        num_ctx=_REDUCE_NUM_CTX,
    )

    if "<OVERVIEW>" in response and "</OVERVIEW>" in response:
        overview_content = response.split("<OVERVIEW>")[1].split("</OVERVIEW>")[0].strip()
    else:
        logger.warning("Reduce response missing <OVERVIEW> wrapper; using raw response as markdown.")
        overview_content = response.strip()
    overview_content = _strip_outer_code_fence(overview_content)

    if not overview_content:
        raise RuntimeError("Reduce call produced empty overview content.")

    overview_content = _strip_image_links(overview_content)

    edges = _compute_module_edges(groups, components, file_to_module)
    diagram = build_module_diagram(
        [g.name for g in groups], edges, min_weight=_DIAGRAM_MIN_EDGE_WEIGHT
    )
    if diagram:
        overview_content = _insert_architecture_section(overview_content, diagram)
        logger.info(
            "map-reduce: inserted deterministic architecture diagram (%d module(s), min_weight=%d)",
            len(groups), _DIAGRAM_MIN_EDGE_WEIGHT,
        )
    else:
        logger.info(
            "map-reduce: no module-to-module edge met min_weight=%d; no diagram inserted",
            _DIAGRAM_MIN_EDGE_WEIGHT,
        )

    return MapReduceResult(overview_markdown=overview_content, mapped=mapped, failed_modules=failed)
