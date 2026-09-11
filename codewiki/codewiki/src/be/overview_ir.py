"""Structured Overview IR — the machine-readable source of truth.

The overview stage produces two artifacts side by side:

* ``overview.md``  — human narrative (one bounded LLM call).
* ``overview.json`` — this IR: a deterministic, graph-derived description of
  the analysed project that the HLD and LLD stages consume *instead of*
  re-reading the repository.

Everything under ``project`` / ``modules`` / ``components`` / ``entrypoints`` /
``integrations`` / ``frontend`` / ``tech_stack`` / ``config_env`` /
``dependency_edges`` is extracted from the dependency graph and the same
deterministic signal scan the evidence extractor uses — no model involved, so
it cannot hallucinate. ``narrative`` holds the LLM's markdown sections,
tagged ``"source": "llm"`` so a downstream stage (or a reviewer) always knows
which parts are model-written.

Keeping this as JSON means the HLD/LLD prompts are built from one structure,
not by pasting the same facts into several prompt templates by hand.
"""

from __future__ import annotations

import os
import re
from collections import Counter
from typing import Any, Dict, List

from codewiki.src.be.dependency_analyzer.models.core import Node
from codewiki.src.be import evidence_extractor as ev
from codewiki.src.be import module_grouper

SCHEMA_VERSION = "overview-ir/1"

# How many entries each capped list carries into the IR. HLD/LLD prompts are
# built from these, so the caps double as a prompt-size guard; a
# larger-context model can raise them via env without any code change.
_MAX_COMPONENTS = int(os.getenv("IR_MAX_COMPONENTS", "120"))
_MAX_MODULES = int(os.getenv("IR_MAX_MODULES", "60"))
_MAX_EDGES = int(os.getenv("IR_MAX_EDGES", "300"))

_SECTION_RE = re.compile(r"^##\s+(?P<title>.+?)\s*$", re.MULTILINE)


def _kind(node: Node) -> str:
    return (node.node_type or node.component_type or "component").lower()


def _split_markdown_sections(markdown: str) -> List[Dict[str, str]]:
    """Break the LLM overview into ``{"heading", "body"}`` entries by ``## ``."""
    if not markdown:
        return []
    matches = list(_SECTION_RE.finditer(markdown))
    if not matches:
        return [{"heading": "Overview", "body": markdown.strip(), "source": "llm"}]
    out: List[Dict[str, str]] = []
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(markdown)
        out.append(
            {
                "heading": m.group("title").strip(),
                "body": markdown[start:end].strip(),
                "source": "llm",
            }
        )
    return out


def _module_edges(groups, components: Dict[str, Node]) -> List[Dict[str, Any]]:
    file_to_module = {f: g.name for g in groups for f in g.files}
    seen: set = set()
    edges: List[Dict[str, Any]] = []
    for group in groups:
        counts: Counter = Counter()
        for node in components.values():
            if (node.relative_path or "") not in group.files:
                continue
            for dep_id in node.depends_on:
                dep = components.get(dep_id)
                if dep is None:
                    continue
                target = file_to_module.get(dep.relative_path or "")
                if target and target != group.name:
                    counts[target] += 1
        for target, weight in counts.items():
            key = (group.name, target)
            if key in seen:
                continue
            seen.add(key)
            edges.append({"from": group.name, "to": target, "weight": weight})
    edges.sort(key=lambda e: e["weight"], reverse=True)
    return edges[:_MAX_EDGES]


def build_overview_ir(
    config,
    components: Dict[str, Node],
    leaf_nodes: List[str],
    overview_markdown: str,
) -> Dict[str, Any]:
    """Assemble the structured IR. Pure function of its inputs; no LLM call."""
    repo_path = os.path.abspath(config.repo_path)
    repo_name = os.path.basename(os.path.normpath(config.repo_path))

    files = sorted({n.relative_path for n in components.values() if n.relative_path})
    languages = Counter(
        (n.language or os.path.splitext(n.relative_path or "")[1].lstrip(".") or "unknown")
        for n in components.values()
    )

    # ---- modules (directory-shaped groups from the same grouper the -------
    #      deterministic diagram uses) -------------------------------------
    groups = module_grouper.group_modules(files) if files else []
    file_to_group = {f: g.name for g in groups for f in g.files}
    group_counts: Counter = Counter()
    for n in components.values():
        g = file_to_group.get(n.relative_path or "")
        if g:
            group_counts[g] += 1
    modules = [
        {
            "name": g.name,
            "file_count": len(g.files),
            "component_count": group_counts.get(g.name, 0),
            "files": sorted(g.files)[:40],
        }
        for g in groups
    ][:_MAX_MODULES]
    dependency_edges = _module_edges(groups, components)

    # ---- components (ranked by in-degree = architectural centrality) -----
    in_degree: Counter = Counter()
    for n in components.values():
        for dep_id in n.depends_on:
            in_degree[dep_id] += 1
    ranked = sorted(
        components.values(),
        key=lambda n: (in_degree.get(n.id, 0), 1 if n.id in set(leaf_nodes) else 0),
        reverse=True,
    )
    comp_list = [
        {
            "id": n.id,
            "name": n.get_display_name(),
            "kind": _kind(n),
            "file": n.relative_path,
            "start_line": n.start_line or None,
            "end_line": n.end_line or None,
            "class_name": n.class_name,
            "language": n.language,
            "in_degree": in_degree.get(n.id, 0),
            "depends_on": sorted(
                {
                    components[d].get_display_name()
                    for d in n.depends_on
                    if d in components
                }
            )[:15],
            "has_docstring": bool(n.has_docstring),
        }
        for n in ranked[:_MAX_COMPONENTS]
    ]

    # ---- deterministic signal scan (entrypoints / integrations / UI / ---
    #      tech stack / config) — reuse the evidence extractor's detectors -
    signal_findings: List[str] = []
    integration_findings: List[str] = []
    manifests: Dict[str, List[str]] = {}
    config_env: List[str] = []
    for root, dirs, filenames in os.walk(repo_path):
        dirs[:] = [d for d in dirs if not ev._is_dir_excluded(d)]
        for filename in filenames:
            abs_path = os.path.join(root, filename)
            rel = os.path.relpath(abs_path, repo_path)
            tier = ev._classify(rel, filename)
            content, _ = ev._read_capped(abs_path, 20_000)
            if tier == "manifest":
                names = ev._extract_dependency_names(rel, content)
                if names:
                    manifests[rel] = names
            if tier == "config" or filename.lower().startswith(".env"):
                for line in content.splitlines():
                    key = line.split("=", 1)[0].strip()
                    if re.fullmatch(r"[A-Z][A-Z0-9_]{2,}", key):
                        config_env.append(key)
            ext = os.path.splitext(filename)[1].lower()
            if ext in ev._SIGNAL_SCAN_EXTENSIONS and content:
                signal_findings.extend(ev._scan_signals(rel, content))
                integration_findings.extend(ev._scan_integrations(rel, content))

    integrations: Dict[str, List[str]] = {}
    for line in integration_findings:
        # "<path>: outbound integration -> <Target>"  |  "<path>: makes outbound HTTP..."
        if " -> " in line:
            path, target = line.split(":", 1)[0].strip(), line.split(" -> ", 1)[1].strip()
        else:
            path, target = line.split(":", 1)[0].strip(), "external service (unidentified)"
        integrations.setdefault(target, [])
        if path not in integrations[target]:
            integrations[target].append(path)

    entrypoints = sorted(
        {
            line.split(":", 1)[0].strip()
            for line in signal_findings
            if "entry point" in line or "server startup" in line
        }
    )

    tech_stack = sorted({name for names in manifests.values() for name in names})

    ir: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "project": {
            "name": repo_name,
            "repo_path": config.repo_path,
            "file_count": len(files),
            "component_count": len(components),
            "leaf_node_count": len(leaf_nodes),
            "module_count": len(groups),
            "languages": dict(languages.most_common()),
            "primary_language": (languages.most_common(1) or [("unknown", 0)])[0][0],
        },
        "modules": modules,
        "dependency_edges": dependency_edges,
        "components": comp_list,
        "entrypoints": entrypoints,
        "integrations": [
            {"target": t, "files": sorted(f)} for t, f in sorted(integrations.items())
        ],
        "frontend": ev._detect_ui(repo_path),
        "tech_stack": tech_stack,
        "config_env": sorted(set(config_env))[:80],
        "architecture_signals": sorted(set(signal_findings))[:60],
        "narrative": {
            "source": "llm",
            "model": getattr(config, "main_model", None),
            "sections": _split_markdown_sections(overview_markdown),
        },
    }
    return ir


# --------------------------------------------------------------------------
# Fact sets a validator / prompt builder can check a generated doc against.
# --------------------------------------------------------------------------
def ir_fact_sets(ir: Dict[str, Any]) -> Dict[str, set]:
    files = {c["file"] for c in ir.get("components", []) if c.get("file")}
    files |= {f for m in ir.get("modules", []) for f in m.get("files", [])}
    components = {c["name"] for c in ir.get("components", [])}
    components |= {m["name"] for m in ir.get("modules", [])}
    integrations = {i["target"] for i in ir.get("integrations", [])}
    tech = {t.lower() for t in ir.get("tech_stack", [])}
    env = set(ir.get("config_env", []))
    return {
        "files": files,
        "components": components,
        "integrations": integrations,
        "tech": tech,
        "env": env,
    }
