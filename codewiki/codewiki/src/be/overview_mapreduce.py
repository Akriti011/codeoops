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
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from typing import Dict, List, Optional

from codewiki.src.be import module_descriptor
from codewiki.src.be.backend import LLMBackend
from codewiki.src.be.dependency_analyzer.models.core import Node
from codewiki.src.be.module_grouper import group_modules
from codewiki.src.be.prompt_template import MAP_MODULE_PROMPT, REDUCE_OVERVIEW_PROMPT

logger = logging.getLogger(__name__)

# Separate model knobs from MAIN_MODEL/FALLBACK_MODEL_1/CLUSTER_MODEL —
# unset means "use whatever complete() defaults to" (config.main_model).
MAP_MODEL = os.getenv("MAP_MODEL") or None
REDUCE_MODEL = os.getenv("REDUCE_MODEL") or None
MAX_MODULES = int(os.getenv("MAX_MODULES", "40"))

# Not env-configurable on purpose: these are the two measured operating
# points (100% GPU at 2048, the deliberate "one large call" at 8192) this
# whole design exists to hit. If you need different numbers, that's a sign
# the hardware or model changed enough to re-run the context sweep, not a
# knob to nudge blindly — see README.md's Docker resource notes.
_MAP_NUM_CTX = 2048
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
            prompt, temperature=0.2, max_tokens=_MAP_MAX_TOKENS, model=model, num_ctx=_MAP_NUM_CTX
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
        temperature=0.2,
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

    return MapReduceResult(overview_markdown=overview_content, mapped=mapped, failed_modules=failed)
