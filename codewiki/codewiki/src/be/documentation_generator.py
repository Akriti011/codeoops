import logging
import os
import json
import re
from typing import Dict, List, Any
from copy import deepcopy
import traceback

# Configure logging and monitoring
logger = logging.getLogger(__name__)

# Local imports
from codewiki.src.be.dependency_analyzer import DependencyGraphBuilder
from codewiki.src.be.backend import LLMBackend, get_backend
from codewiki.src.be import evidence_extractor
from codewiki.src.be import overview_mapreduce
from codewiki.src.be import module_descriptor
from codewiki.src.be import module_grouper
from codewiki.src.be import overview_ir as overview_ir_mod
from codewiki.src.be import doc_validator
from codewiki.src.be.prompt_template import (
    REPO_OVERVIEW_PROMPT,
    MODULE_OVERVIEW_PROMPT,
    OVERVIEW_ONLY_PROMPT,
    HLD_PROMPT,
    LLD_PROMPT,
)
from codewiki.src.be.cluster_modules import (
    cluster_modules,
    get_clustering_input_token_count,
)
from codewiki.src.config import (
    Config,
    FIRST_MODULE_TREE_FILENAME,
    MODULE_TREE_FILENAME,
    OVERVIEW_FILENAME
)
from codewiki.src.be.module_naming import (
    dedupe_module_tree_names,
    find_missing_module_docs,
    resolve_module_doc_path,
)
from codewiki.src.utils import file_manager

# Output token cap for the single overview_only completion call. Deliberately
# small relative to config.max_tokens (used elsewhere) — the target is a
# concise 2,000-3,000 token HLD, not a long report, per OVERVIEW_ONLY_PROMPT.
OVERVIEW_ONLY_MAX_OUTPUT_TOKENS = int(os.getenv("OVERVIEW_MAX_OUTPUT_TOKENS", "3000"))

# Ollama context window for the single overview_only completion call. Must be
# passed explicitly: llm_services.call_llm() only routes to Ollama's native
# /api/chat endpoint (the one that actually honors a context override — see
# its docstring) when a caller passes num_ctx itself. Before this, this call
# passed nothing, so every real generation silently loaded the model at its
# Modelfile-baked 16384 default instead of this value — confirmed via
# `ollama ps` reporting context_length=16384 and a partial CPU/GPU split
# instead of 100% GPU residency, during a real ZIP-upload run of a 3-file
# repository that was still "GENERATING" past 5 minutes. overview_mapreduce.py
# already does this correctly for its own two calls; this brings the
# single-call production path (OVERVIEW_ONLY_MODE=true) in line with it.
OVERVIEW_ONLY_NUM_CTX = int(os.getenv("OLLAMA_NUM_CTX", "4096"))


def _stage_enabled(stage: str) -> bool:
    """Whether the HLD ("hld") / LLD ("lld") pipeline stage should run.
    Read at call time so tests / a redeploy can flip it without reimport."""
    from codewiki.src import config as _cfg
    return {"hld": _cfg.HLD_ENABLED, "lld": _cfg.LLD_ENABLED}.get(stage, False)


def _validator_enabled() -> bool:
    from codewiki.src import config as _cfg
    return _cfg.DOC_VALIDATOR_ENABLED


def _strip_outer_code_fence(text: str) -> str:
    """Models sometimes wrap an entire Markdown answer in its own code fence
    (```markdown ... ```) despite already being asked for raw Markdown output
    — observed directly from codewiki-qwen2.5-16k. Left in place, every
    downstream consumer (web viewer, PDF export, CSV section-splitter) would
    treat the whole document as one preformatted block instead of parsing
    real headings/lists/diagrams. Strip exactly one such outer fence if the
    first and last non-blank lines are bare fence markers.
    """
    lines = text.strip().splitlines()
    if len(lines) >= 2 and lines[0].strip().startswith("```") and lines[-1].strip() == "```":
        return "\n".join(lines[1:-1]).strip()
    # Half-wrapped: a bare opening ```lang line right before a heading, with an
    # odd number of fences overall (so no matching close). Drop the stray line.
    if (
        len(lines) >= 2
        and re.fullmatch(r"```[\w-]*", lines[0].strip())
        and lines[1].lstrip().startswith("#")
        and text.count("```") % 2 == 1
    ):
        return "\n".join(lines[1:]).strip()
    return text.strip()


_MERMAID_BLOCK_RE = re.compile(r"```mermaid\n(.*?)```", re.DOTALL)
_MERMAID_EDGE_RE = re.compile(r"^\s*([A-Za-z0-9_]+)(?:\[[^\]]*\])?\s*-->\s*([A-Za-z0-9_]+)", re.MULTILINE)
_MERMAID_LABELED_NODE_RE = re.compile(r"\b([A-Za-z0-9_]+)\[([^\]]*)\]")

# A rectangle label ``id[...]`` (not ``id[[...]]`` / ``id[(...)]`` / already
# quoted) — captured so risky characters inside it can be neutralised.
_MERMAID_RECT_LABEL_RE = re.compile(r"([A-Za-z0-9_]+)\[(?!\[|\()\s*(?!\")([^\]\"]*?)\s*\]")
# An edge label ``-->|...|`` / ``-.->|...|`` / ``==>|...|`` that isn't quoted.
_MERMAID_EDGE_LABEL_RE = re.compile(r"(--+>|-\.-+>|==+>)\|\s*(?!\")([^|]*?)\s*\|")
# Characters that make the Mermaid flowchart parser choke inside a bracket
# label: the shape-delimiters and a few structural tokens.
_MERMAID_LABEL_BAD_CHARS = re.compile(r"[()\[\]{}<>#|;]")


def _sanitize_mermaid_labels(markdown: str) -> str:
    """Quote Mermaid node/edge labels that contain characters the flowchart
    parser treats as syntax.

    Seen directly on a real repo: the model wrote
    ``I[Database (Not explicitly identified in the repository)]`` — the ``(``
    inside ``[...]`` starts a shape token as far as Mermaid is concerned, so
    the whole diagram fails to parse and renders as a tiny error box (no
    nodes, no edges). Wrapping such a label in double quotes
    (``I["Database (...)"]``) is valid Mermaid and keeps the label text
    intact. Non-destructive: labels without risky characters are left byte
    for byte as they were.
    """

    def _fix_block(match: "re.Match[str]") -> str:
        body = match.group(1)

        def _rect(m: "re.Match[str]") -> str:
            node_id, label = m.group(1), m.group(2)
            if not _MERMAID_LABEL_BAD_CHARS.search(label):
                return m.group(0)
            return f'{node_id}["{label.replace(chr(34), chr(39))}"]'

        def _edge(m: "re.Match[str]") -> str:
            arrow, label = m.group(1), m.group(2)
            if not label or not _MERMAID_LABEL_BAD_CHARS.search(label):
                return m.group(0)
            return f'{arrow}|"{label.replace(chr(34), chr(39))}"|'

        body = _MERMAID_RECT_LABEL_RE.sub(_rect, body)
        body = _MERMAID_EDGE_LABEL_RE.sub(_edge, body)
        return f"```mermaid\n{body}```"

    return _MERMAID_BLOCK_RE.sub(_fix_block, markdown)


def _strip_degenerate_mermaid_diagrams(markdown: str) -> str:
    """Remove a Mermaid block with no real edges, or that redefines the same
    node id with two different bracket labels.

    Observed directly on a real 103-file repository: the model "relabeled"
    a node with a repeated `BE --> BE[Code Analysis]` / `BE --> BE[...]`
    line instead of drawing an edge to a genuinely new node. That parses as
    valid Mermaid — no error anywhere — but renders as an empty or visually
    collapsed diagram in the browser (confirmed: a real self-loop-only edge
    list passes fine; this exact conflicting-relabel pattern is what
    produced the blank box). A pure edge check alone doesn't catch it,
    since the same diagram usually still has one or two genuine edges mixed
    in with the relabeling noise — the label conflict itself is the actual
    signal. Also now forbidden directly in MERMAID_RULES
    (prompt_template.py), but a 7B model following a rule "mostly" isn't
    the same as it never happening — this is the deterministic backstop,
    matching the same principle the prompt already states: omit a diagram
    rather than mislead.
    """

    def _replace(match: "re.Match[str]") -> str:
        body = match.group(1)
        edges = _MERMAID_EDGE_RE.findall(body)
        if not edges or all(source == target for source, target in edges):
            return ""
        seen_labels: dict[str, str] = {}
        for node_id, label in _MERMAID_LABELED_NODE_RE.findall(body):
            label = label.strip()
            if node_id in seen_labels and seen_labels[node_id] != label:
                return ""
            seen_labels.setdefault(node_id, label)
        return match.group(0)

    return _MERMAID_BLOCK_RE.sub(_replace, markdown)


# A heading line immediately followed — after only blank lines — by another
# heading or end-of-document. This is exactly the shape
# _strip_degenerate_mermaid_diagrams leaves behind: it correctly removes a
# broken diagram block, but has no visibility into the heading the model
# wrote to introduce it, so the heading survives with nothing under it —
# reading as a jarring gap rather than a deliberate, honest omission. The
# heading text itself is matched separately (not folded into this regex) to
# avoid the backtracking cost of a keyword search sandwiched between two
# wildcards on every heading line in the document.
# A single literal space (not a quantifier) between the hashes and the
# heading text avoids overlapping-quantifier ambiguity with the [^\n]* that
# follows (both would otherwise happily consume the same run of spaces).
_EMPTY_SECTION_RE = re.compile(r"^(#{2,4} [^\n]*)\n+(?=#{1,6}[ \t]|\Z)", re.MULTILINE)
_DIAGRAM_HEADING_RE = re.compile(r"\b(?:diagram|mermaid)\b", re.IGNORECASE)


def _fill_orphaned_diagram_headings(markdown: str) -> str:
    """Give a diagram heading left empty by stripping an honest one-liner,
    matching the same "state the absence" convention the prompts already use
    ("Not evidenced by the analysed codebase.", "Not visible in the analysed
    excerpts.") rather than leaving an unexplained blank gap. Scoped to
    diagram/mermaid headings specifically — a short-but-legitimate section on
    any other topic is left untouched."""

    def _replace(match: "re.Match[str]") -> str:
        heading = match.group(1)
        if not _DIAGRAM_HEADING_RE.search(heading):
            return match.group(0)
        return f"{heading}\nNo reliable diagram could be generated for this section.\n\n"

    return _EMPTY_SECTION_RE.sub(_replace, markdown)


class IncompleteDocumentationError(Exception):
    """Raised when generation finishes but some modules have no doc file on disk."""

    def __init__(self, missing_modules: List[str]):
        self.missing_modules = missing_modules
        super().__init__(
            f"Documentation generation finished but {len(missing_modules)} module doc(s) "
            f"are missing: {', '.join(missing_modules)}"
        )


class DocumentationGenerator:
    """Main documentation generation orchestrator."""

    def __init__(self, config: Config, commit_id: str = None, backend: LLMBackend = None):
        self.config = config
        self.commit_id = commit_id
        self.graph_builder = DependencyGraphBuilder(config)
        self.backend: LLMBackend = backend or get_backend(config)
    
    def create_documentation_metadata(self, working_dir: str, components: Dict[str, Any], num_leaf_nodes: int):
        """Create a metadata file with documentation generation information."""
        from datetime import datetime
        
        metadata = {
            "generation_info": {
                "timestamp": datetime.now().isoformat(),
                "main_model": self.config.main_model,
                "generator_version": "1.0.1",
                "repo_path": self.config.repo_path,
                "commit_id": self.commit_id
            },
            "statistics": {
                "total_components": len(components),
                "leaf_nodes": num_leaf_nodes,
                "max_depth": self.config.max_depth
            },
            "files_generated": [
                "overview.md",
                "module_tree.json",
                "first_module_tree.json"
            ]
        }
        
        # Add generated markdown files to the metadata
        try:
            for file_path in os.listdir(working_dir):
                if file_path.endswith('.md') and file_path not in metadata["files_generated"]:
                    metadata["files_generated"].append(file_path)
        except Exception as e:
            logger.warning(f"Could not list generated files: {e}")
        
        metadata_path = os.path.join(working_dir, "metadata.json")
        file_manager.save_json(metadata, metadata_path)

    
    def get_processing_order(self, module_tree: Dict[str, Any], parent_path: List[str] = []) -> List[tuple[List[str], str]]:
        """Get the processing order using topological sort (leaf modules first)."""
        processing_order = []
        
        def collect_modules(tree: Dict[str, Any], path: List[str]):
            for module_name, module_info in tree.items():
                current_path = path + [module_name]
                
                # If this module has children, process them first
                if module_info.get("children") and isinstance(module_info["children"], dict) and module_info["children"]:
                    collect_modules(module_info["children"], current_path)
                    # Add this parent module after its children
                    processing_order.append((current_path, module_name))
                else:
                    # This is a leaf module, add it immediately
                    processing_order.append((current_path, module_name))
        
        collect_modules(module_tree, parent_path)
        return processing_order

    def is_leaf_module(self, module_info: Dict[str, Any]) -> bool:
        """Check if a module is a leaf module (has no children or empty children)."""
        children = module_info.get("children", {})
        return not children or (isinstance(children, dict) and len(children) == 0)

    def build_overview_structure(self, module_tree: Dict[str, Any], module_path: List[str],
                                 working_dir: str) -> Dict[str, Any]:
        """Build structure for overview generation with 1-depth children docs and target indicator."""
        
        processed_module_tree = deepcopy(module_tree)
        module_info = processed_module_tree
        for path_part in module_path:
            module_info = module_info[path_part]
            if path_part != module_path[-1]:
                module_info = module_info.get("children", {})
            else:
                module_info["is_target_for_overview_generation"] = True

        if "children" in module_info:
            module_info = module_info["children"]

        for child_name, child_info in module_info.items():
            child_docs_path = self._resolve_child_docs_path(working_dir, child_name)
            if child_docs_path is not None:
                child_info["docs"] = file_manager.load_text(child_docs_path)
            else:
                logger.warning(f"Module docs not found at {os.path.join(working_dir, f'{child_name}.md')}")
                child_info["docs"] = ""

        return processed_module_tree

    @staticmethod
    def _resolve_child_docs_path(working_dir: str, child_name: str) -> str | None:
        """Resolve the on-disk path for a child module's .md doc.

        Sub-agents sometimes save files under a sanitized variant of the
        module name (spaces → underscores, lowercased, etc.) rather than the
        exact key in the module tree. Try a small set of common variants
        before giving up so the overview prompt still gets the children's
        content as context.
        """
        return resolve_module_doc_path(working_dir, child_name)

    def validate_generated_docs(self, working_dir: str) -> List[str]:
        """Check the final module tree against the docs on disk.

        Returns the names of modules whose .md file is missing (plus
        "overview" if overview.md was never written).
        """
        module_tree_path = os.path.join(working_dir, MODULE_TREE_FILENAME)
        if not os.path.exists(module_tree_path):
            return []
        module_tree = file_manager.load_json(module_tree_path)
        return find_missing_module_docs(module_tree, working_dir)

    async def generate_module_documentation(self, components: Dict[str, Any], leaf_nodes: List[str]) -> str:
        """Generate documentation for all modules using dynamic programming approach."""
        # Prepare output directory
        working_dir = os.path.abspath(self.config.docs_dir)
        file_manager.ensure_directory(working_dir)

        module_tree_path = os.path.join(working_dir, MODULE_TREE_FILENAME)
        first_module_tree_path = os.path.join(working_dir, FIRST_MODULE_TREE_FILENAME)
        module_tree = file_manager.load_json(module_tree_path)
        first_module_tree = file_manager.load_json(first_module_tree_path)
        
        # Get processing order (leaf modules first)
        processing_order = self.get_processing_order(first_module_tree)

        
        # Process modules in dependency order
        final_module_tree = module_tree
        processed_modules = set()

        if len(module_tree) > 0:
            for module_path, module_name in processing_order:
                try:
                    # Reload module tree to get latest hierarchical structure from sub-agent modifications
                    module_tree = file_manager.load_json(module_tree_path)
                    
                    # Get the module info from the tree
                    module_info = module_tree
                    for path_part in module_path:
                        module_info = module_info[path_part]
                        if path_part != module_path[-1]:  # Not the last part
                            module_info = module_info.get("children", {})
                    
                    # Skip if already processed
                    module_key = "/".join(module_path)
                    if module_key in processed_modules:
                        continue
                    
                    # Process the module
                    if self.is_leaf_module(module_info):
                        logger.info(f"📄 Processing leaf module: {module_key}")
                        final_module_tree = await self.backend.run_module_agent(
                            module_name=module_name,
                            components=components,
                            core_component_ids=module_info["components"],
                            module_path=module_path,
                            working_dir=working_dir,
                        )
                    else:
                        logger.info(f"📁 Processing parent module: {module_key}")
                        final_module_tree = await self.generate_parent_module_docs(
                            module_path, working_dir
                        )
                    
                    processed_modules.add(module_key)
                    
                except Exception as e:
                    logger.error(f"Failed to process module {module_key}: {str(e)}")
                    logger.error(f"Traceback: {traceback.format_exc()}")
                    # A module without its Markdown artifact makes every parent
                    # overview incomplete.  Propagate the failure instead of
                    # producing a nominally successful but empty documentation run.
                    raise

            # Generate repo overview
            logger.info(f"📚 Generating repository overview")
            final_module_tree = await self.generate_parent_module_docs(
                [], working_dir
            )
        else:
            logger.info(f"Processing whole repo because repo can fit in the context window")
            repo_name = os.path.basename(os.path.normpath(self.config.repo_path))
            final_module_tree = await self.backend.run_module_agent(
                module_name=repo_name,
                components=components,
                core_component_ids=leaf_nodes,
                module_path=[],
                working_dir=working_dir,
            )

            # save final_module_tree to module_tree.json
            file_manager.save_json(final_module_tree, os.path.join(working_dir, MODULE_TREE_FILENAME))

            # Whole-repository mode has no module-tree entries to validate, so
            # enforce the overview artifact as an explicit postcondition.
            repo_overview_path = resolve_module_doc_path(working_dir, repo_name)
            overview_path = os.path.join(working_dir, OVERVIEW_FILENAME)
            if repo_overview_path is None:
                raise IncompleteDocumentationError(["overview"])
            if os.path.abspath(repo_overview_path) != os.path.abspath(overview_path):
                os.replace(repo_overview_path, overview_path)
            if not os.path.isfile(overview_path) or os.path.getsize(overview_path) == 0:
                raise IncompleteDocumentationError(["overview"])
            logger.info(
                "Whole-repository overview written: path=%s bytes=%d",
                overview_path,
                os.path.getsize(overview_path),
            )
        
        return working_dir

    async def generate_overview_via_mapreduce(
        self, components: Dict[str, Any], leaf_nodes: List[str]
    ) -> str:
        """Generate overview.md via overview_mapreduce.py's group -> map ->
        reduce pipeline (OVERVIEW_MODE=mapreduce). A separate strategy from
        generate_overview_only() below, which this never calls into or
        modifies — that stays the default single-call fast path.
        """
        working_dir = os.path.abspath(self.config.docs_dir)
        file_manager.ensure_directory(working_dir)

        overview_path = os.path.join(working_dir, OVERVIEW_FILENAME)
        if os.path.exists(overview_path):
            logger.info(f"✓ Overview already exists at {overview_path}")
            return working_dir

        repo_name = os.path.basename(os.path.normpath(self.config.repo_path))
        logger.info(
            "Generating overview via map-reduce (overview_mode=mapreduce) for %s: "
            "%d component(s), %d leaf node(s)",
            repo_name, len(components), len(leaf_nodes),
        )

        try:
            result = overview_mapreduce.run_mapreduce(
                self.config, self.backend, components, leaf_nodes, repo_name
            )
        except Exception as e:
            logger.error(f"Error generating map-reduce overview for {repo_name}: {str(e)}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            raise

        file_manager.save_text(result.overview_markdown, overview_path)
        logger.info(
            "Map-reduce overview written: path=%s bytes=%d mapped=%d failed=%d",
            overview_path, os.path.getsize(overview_path),
            len(result.mapped), len(result.failed_modules),
        )
        if result.failed_modules:
            logger.warning(
                "Map-reduce: %d module(s) failed and were excluded: %s",
                len(result.failed_modules), ", ".join(result.failed_modules),
            )
        return working_dir

    @staticmethod
    def _insert_deterministic_diagram(overview_content: str, components: Dict[str, Any]) -> str:
        """Fall back to a real, graph-derived architecture diagram when the
        model's own attempt produced nothing usable (never generated one, or
        it was stripped as degenerate above).

        "Make sure diagrams actually appear" doesn't stop being true just
        because a 7B model's diagram attempt didn't work out this run — and
        the pipeline already has a diagram builder that can never be wrong
        in the way an LLM one can, because it draws directly from
        depends_on edges instead of composing a picture from a prompt:
        overview_mapreduce.py's map-reduce path uses it for exactly this.
        Reused as-is here (group_modules, _module_edge_weights,
        build_module_diagram, _insert_architecture_section are all already
        covered by their own tests) rather than duplicated. Returns
        overview_content unchanged if the repository has too few
        cross-module edges to draw one honestly — that's the same "omit
        rather than mislead" rule, not a bug.
        """
        files = sorted({node.relative_path for node in components.values()})
        groups = module_grouper.group_modules(files)
        if len(groups) < 2:
            return overview_content

        file_to_module = {f: group.name for group in groups for f in group.files}
        edges: Dict[tuple, int] = {}
        for group in groups:
            weights = module_descriptor._module_edge_weights(
                group.name, group.files, components, file_to_module
            )
            for target, weight in weights.items():
                edges[(group.name, target)] = weight

        diagram = overview_mapreduce.build_module_diagram([g.name for g in groups], edges)
        if not diagram:
            return overview_content

        logger.info(
            "Single-shot overview: model produced no usable diagram; inserted a "
            "deterministic one from %d module(s) instead.", len(groups),
        )
        return overview_mapreduce._insert_architecture_section(overview_content, diagram)

    async def generate_overview_only(self, components: Dict[str, Any], leaf_nodes: List[str]) -> str:
        """Generate exactly one overview.md via a single bounded, non-agentic
        completion call.

        No clustering, no per-module docs, no agent tools — so there is no
        code path by which this can recurse into sub-module generation the
        way the agentic whole-repo path (run_module_agent with
        generate_sub_module_documentation_tool) can. See config.overview_only.
        """
        working_dir = os.path.abspath(self.config.docs_dir)
        file_manager.ensure_directory(working_dir)

        overview_path = os.path.join(working_dir, OVERVIEW_FILENAME)
        if os.path.exists(overview_path):
            logger.info(f"✓ Overview already exists at {overview_path}")
            return working_dir

        repo_name = os.path.basename(os.path.normpath(self.config.repo_path))
        logger.info(
            "Generating single-shot overview (overview_only mode) for %s: "
            "repo_path=%s %d component(s), %d leaf node(s)",
            repo_name, self.config.repo_path, len(components), len(leaf_nodes),
        )

        architecture_evidence = evidence_extractor.build_architecture_evidence(
            self.config, components, leaf_nodes
        )
        prompt = OVERVIEW_ONLY_PROMPT.format(
            repo_name=repo_name,
            architecture_evidence=architecture_evidence,
        )

        from codewiki.src.config import task_model as _task_model
        _ov = _task_model("overview")
        logger.info(
            "Stage 2 (overview): model=%s num_ctx=%d max_tokens=%d endpoint=%s",
            _ov.model, _ov.num_ctx, _ov.max_tokens, _ov.base_url,
        )
        try:
            response = self.backend.complete(
                prompt,
                model=_ov.model or None,
                temperature=_ov.temperature,
                max_tokens=_ov.max_tokens,
                num_ctx=_ov.num_ctx,
                base_url=_ov.base_url or None,
                api_key=_ov.api_key or None,
            )
        except Exception as e:
            logger.error(f"Error generating single-shot overview for {repo_name}: {str(e)}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            raise

        if "<OVERVIEW>" in response and "</OVERVIEW>" in response:
            overview_content = response.split("<OVERVIEW>")[1].split("</OVERVIEW>")[0].strip()
        else:
            logger.warning(
                "Overview response missing <OVERVIEW> wrapper; using raw response as markdown."
            )
            overview_content = response.strip()

        overview_content = _strip_outer_code_fence(overview_content)
        # Same belt-and-braces strip overview_mapreduce.py's reduce step
        # already applies to its own output (see its docstring) — observed
        # here too, on a real 103-file repository: a stray
        # ![Architecture Diagram](#architecture-diagram) line the model
        # can't actually back with an image, left in front of the real
        # ```mermaid block. The prompt asking for real diagrams doesn't
        # stop it also reaching for this placeholder-image habit; strip it
        # deterministically rather than rely on the prompt alone.
        overview_content = overview_mapreduce._strip_image_links(overview_content)
        overview_content = _sanitize_mermaid_labels(overview_content)
        overview_content = _strip_degenerate_mermaid_diagrams(overview_content)

        if "```mermaid" not in overview_content:
            logger.info(
                "Single-shot overview: no usable Mermaid diagram in the model's "
                "response; attempting a deterministic, edge-derived fallback."
            )
            overview_content = self._insert_deterministic_diagram(overview_content, components)

        # The fallback above only covers the primary architecture diagram —
        # a secondary one (e.g. "Mermaid Data-Flow Diagram") that gets
        # stripped as degenerate while the primary survives leaves its own
        # heading orphaned, since the "no mermaid at all" check above never
        # fires in that case.
        overview_content = _fill_orphaned_diagram_headings(overview_content)

        if not overview_content:
            raise IncompleteDocumentationError(["overview"])

        file_manager.save_text(overview_content, overview_path)
        logger.info(
            "Single-shot overview written: path=%s bytes=%d",
            overview_path, os.path.getsize(overview_path),
        )

        # --- Structured Overview IR (machine-readable source of truth) -----
        try:
            ir = overview_ir_mod.build_overview_ir(
                self.config, components, leaf_nodes, overview_content
            )
            file_manager.save_json(ir, os.path.join(working_dir, "overview.json"))
            logger.info(
                "Overview IR written: %d components, %d modules, %d integrations",
                len(ir.get("components", [])), len(ir.get("modules", [])),
                len(ir.get("integrations", [])),
            )
        except Exception:
            logger.exception("Failed to build overview IR (overview.md is unaffected)")
            ir = None

        # --- Stage 3: HLD, Stage 4: LLD (model-agnostic, own configs) -----
        if ir is not None and _stage_enabled("hld"):
            try:
                hld_md = await self.generate_hld(ir, overview_content, working_dir)
                if hld_md is not None and _stage_enabled("lld"):
                    await self.generate_lld(ir, hld_md, components, working_dir)
            except Exception:
                logger.exception("HLD/LLD stage failed (overview.md + overview.json are unaffected)")

        return working_dir

    # ------------------------------------------------------------------
    # HLD / LLD generation stages
    # ------------------------------------------------------------------
    @staticmethod
    def _render_ir_for_prompt(ir: Dict[str, Any]) -> str:
        """Compact text digest of the Overview IR for prompt injection. Built
        once and reused by both HLD and LLD so facts are never re-typed."""
        p = ir.get("project", {})
        lines: List[str] = []
        lines.append(f"PROJECT: {p.get('name')} — {p.get('file_count')} source files, "
                     f"{p.get('component_count')} components, {p.get('module_count')} modules; "
                     f"languages: {', '.join(f'{k} ({v})' for k, v in list(p.get('languages', {}).items())[:6])}")
        lines.append("")
        lines.append("MODULES (name | files | components):")
        for m in ir.get("modules", [])[:40]:
            lines.append(f"  - {m['name']} | {m['file_count']} files | {m['component_count']} components")
        lines.append("")
        if ir.get("dependency_edges"):
            lines.append("MODULE DEPENDENCY EDGES (from -> to, weight):")
            for e in ir["dependency_edges"][:40]:
                lines.append(f"  - {e['from']} -> {e['to']}  ({e['weight']})")
            lines.append("")
        lines.append("MOST CENTRAL COMPONENTS (name | kind | file:line | in-degree | depends on):")
        for c in ir.get("components", [])[:60]:
            deps = ", ".join(c.get("depends_on", [])[:6])
            loc = f"{c.get('file')}:{c.get('start_line') or '?'}"
            lines.append(f"  - {c['name']} | {c['kind']} | {loc} | {c.get('in_degree', 0)} | {deps}")
        lines.append("")
        if ir.get("entrypoints"):
            lines.append("ENTRY POINTS: " + ", ".join(ir["entrypoints"][:20]))
        if ir.get("integrations"):
            lines.append("EXTERNAL INTEGRATIONS:")
            for i in ir["integrations"]:
                lines.append(f"  - {i['target']} <- {', '.join(i['files'][:5])}")
        if ir.get("frontend"):
            lines.append("FRONTEND: " + " | ".join(ir["frontend"]))
        if ir.get("tech_stack"):
            lines.append("TECH STACK (declared dependencies): " + ", ".join(ir["tech_stack"][:60]))
        if ir.get("config_env"):
            lines.append("CONFIG / ENV VARS: " + ", ".join(ir["config_env"][:60]))
        if ir.get("architecture_signals"):
            lines.append("ARCHITECTURE SIGNALS:")
            for s in ir["architecture_signals"][:30]:
                lines.append(f"  - {s}")
        return "\n".join(lines)

    def _finalize_generated_doc(self, raw: str, tag: str, ir: Dict[str, Any],
                                kind: str, out_path: str) -> str | None:
        """Unwrap the <TAG> body, sanitize mermaid, run the grounding
        validator, append the Verification block, and write the file."""
        if f"<{tag}>" in raw and f"</{tag}>" in raw:
            body = raw.split(f"<{tag}>")[1].split(f"</{tag}>")[0].strip()
        else:
            logger.warning("%s response missing <%s> wrapper; using raw response.", kind.upper(), tag)
            body = raw.strip()
        body = _strip_outer_code_fence(body)
        body = overview_mapreduce._strip_image_links(body)
        body = _sanitize_mermaid_labels(body)
        body = _strip_degenerate_mermaid_diagrams(body)
        # Unlike the overview (which falls back to a deterministic,
        # edge-derived diagram when none survives), HLD/LLD have no
        # equivalent fallback — a stripped diagram here previously left its
        # introducing heading orphaned with nothing underneath.
        body = _fill_orphaned_diagram_headings(body)
        if not body:
            logger.error("%s generation produced an empty document", kind.upper())
            return None

        if _validator_enabled():
            try:
                report = doc_validator.validate_doc(body, ir, doc_kind=kind)
                body = body.rstrip() + "\n" + doc_validator.verification_block(report, ir)
                file_manager.save_json(report, out_path.replace(".md", ".validation.json"))
                logger.info(
                    "%s grounding check: %d refs, %d unsupported (verdict=%s)",
                    kind.upper(), report["checked_references"],
                    report["unsupported_count"], report["verdict"],
                )
            except Exception:
                logger.exception("%s grounding check failed; document kept as-is", kind.upper())

        file_manager.save_text(body, out_path)
        logger.info("%s written: path=%s bytes=%d", kind.upper(), out_path, os.path.getsize(out_path))
        return body

    async def generate_hld(self, ir: Dict[str, Any], overview_markdown: str,
                           working_dir: str) -> str | None:
        from codewiki.src.config import task_model
        tm = task_model("hld")
        repo_name = ir.get("project", {}).get("name", "project")
        logger.info("Stage 3 (HLD): model=%s num_ctx=%d max_tokens=%d", tm.model, tm.num_ctx, tm.max_tokens)

        # keep the narrative bounded — the IR digest carries the facts
        narrative = (overview_markdown or "").strip()[:8000]
        prompt = HLD_PROMPT.format(
            repo_name=repo_name,
            structured_context=self._render_ir_for_prompt(ir),
            overview_narrative=narrative,
        )
        try:
            raw = self.backend.complete(
                prompt, model=tm.model or None, temperature=tm.temperature,
                max_tokens=tm.max_tokens, num_ctx=tm.num_ctx,
                base_url=tm.base_url or None, api_key=tm.api_key or None,
            )
        except Exception:
            logger.exception("HLD LLM call failed")
            return None
        return self._finalize_generated_doc(
            raw, "HLD", ir, "hld", os.path.join(working_dir, "hld.md")
        )

    async def generate_lld(self, ir: Dict[str, Any], hld_markdown: str,
                           components: Dict[str, Any], working_dir: str) -> str | None:
        from codewiki.src.config import task_model, LLD_CODE_CONTEXT_FILES, LLD_CODE_CONTEXT_CHARS
        tm = task_model("lld")
        repo_name = ir.get("project", {}).get("name", "project")
        logger.info("Stage 4 (LLD): model=%s num_ctx=%d max_tokens=%d", tm.model, tm.num_ctx, tm.max_tokens)

        # code-level context: source of the most central components, deduped by file
        excerpts: List[str] = []
        seen_files: set = set()
        for c in ir.get("components", []):
            if len(seen_files) >= LLD_CODE_CONTEXT_FILES:
                break
            fpath = c.get("file")
            if not fpath or fpath in seen_files:
                continue
            node = components.get(c["id"])
            src = getattr(node, "source_code", None) if node is not None else None
            if not src:
                continue
            seen_files.add(fpath)
            excerpts.append(f"### {fpath} — {c['name']} ({c['kind']})\n```\n{src[:LLD_CODE_CONTEXT_CHARS]}\n```")
        code_excerpts = "\n\n".join(excerpts) if excerpts else "No source excerpts were available."

        prompt = LLD_PROMPT.format(
            repo_name=repo_name,
            structured_context=self._render_ir_for_prompt(ir),
            hld_content=(hld_markdown or "")[:9000],
            code_excerpts=code_excerpts,
        )
        try:
            raw = self.backend.complete(
                prompt, model=tm.model or None, temperature=tm.temperature,
                max_tokens=tm.max_tokens, num_ctx=tm.num_ctx,
                base_url=tm.base_url or None, api_key=tm.api_key or None,
            )
        except Exception:
            logger.exception("LLD LLM call failed")
            return None
        return self._finalize_generated_doc(
            raw, "LLD", ir, "lld", os.path.join(working_dir, "lld.md")
        )

    async def generate_parent_module_docs(self, module_path: List[str],
                                        working_dir: str) -> Dict[str, Any]:
        """Generate documentation for a parent module based on its children's documentation."""
        module_name = module_path[-1] if len(module_path) >= 1 else os.path.basename(os.path.normpath(self.config.repo_path))

        logger.info(f"Generating parent documentation for: {module_name}")
        
        # Load module tree
        module_tree_path = os.path.join(working_dir, MODULE_TREE_FILENAME)
        module_tree = file_manager.load_json(module_tree_path)

        # check if overview docs already exists
        overview_docs_path = os.path.join(working_dir, OVERVIEW_FILENAME)
        if os.path.exists(overview_docs_path):
            logger.info(f"✓ Overview docs already exists at {overview_docs_path}")
            return module_tree

        # check if parent docs already exists
        parent_docs_path = os.path.join(working_dir, f"{module_name if len(module_path) >= 1 else OVERVIEW_FILENAME.replace('.md', '')}.md")
        if os.path.exists(parent_docs_path):
            logger.info(f"✓ Parent docs already exists at {parent_docs_path}")
            return module_tree

        # Create repo structure with 1-depth children docs and target indicator
        repo_structure = self.build_overview_structure(module_tree, module_path, working_dir)

        prompt = MODULE_OVERVIEW_PROMPT.format(
            module_name=module_name,
            repo_structure=json.dumps(repo_structure, indent=4)
        ) if len(module_path) >= 1 else REPO_OVERVIEW_PROMPT.format(
            repo_name=module_name,
            repo_structure=json.dumps(repo_structure, indent=4)
        )
        
        try:
            parent_docs = self.backend.complete(prompt)

            # Parse and save parent documentation. Subscription-CLI backends
            # (claude-code / codex) sometimes ignore the <OVERVIEW> wrapper and
            # return raw markdown; fall back to the response as-is in that case
            # rather than crashing with an index error.
            if "<OVERVIEW>" in parent_docs and "</OVERVIEW>" in parent_docs:
                parent_content = parent_docs.split("<OVERVIEW>")[1].split("</OVERVIEW>")[0].strip()
            else:
                logger.warning(
                    f"Overview response for {module_name} missing <OVERVIEW> wrapper; "
                    f"using raw response as markdown."
                )
                parent_content = parent_docs.strip()
            file_manager.save_text(parent_content, parent_docs_path)
            
            logger.debug(f"Successfully generated parent documentation for: {module_name}")
            return module_tree
            
        except Exception as e:
            logger.error(f"Error generating parent documentation for {module_name}: {str(e)}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            raise
    
    async def run(self) -> None:
        """Run the complete documentation generation process using dynamic programming."""
        try:
            # Build dependency graph
            components, leaf_nodes = self.graph_builder.build_dependency_graph()

            logger.debug(f"Found {len(leaf_nodes)} leaf nodes")
            # logger.debug(f"Leaf nodes:\n{'\n'.join(sorted(leaf_nodes)[:200])}")
            # exit()

            if self.config.overview_mode == "mapreduce":
                working_dir = await self.generate_overview_via_mapreduce(components, leaf_nodes)
                self.create_documentation_metadata(working_dir, components, len(leaf_nodes))
                markdown_count = sum(
                    1 for name in os.listdir(working_dir) if name.endswith(".md")
                )
                logger.info(
                    "Documentation generation completed (overview_mode=mapreduce): backend=%s "
                    "provider=%s model=%s output=%s markdown_count=%d",
                    type(self.backend).__name__,
                    self.config.provider,
                    self.config.main_model,
                    working_dir,
                    markdown_count,
                )
                return

            if self.config.overview_only:
                working_dir = await self.generate_overview_only(components, leaf_nodes)
                self.create_documentation_metadata(working_dir, components, len(leaf_nodes))
                markdown_count = sum(
                    1 for name in os.listdir(working_dir) if name.endswith(".md")
                )
                logger.info(
                    "Documentation generation completed (overview_only): backend=%s "
                    "provider=%s model=%s output=%s markdown_count=%d",
                    type(self.backend).__name__,
                    self.config.provider,
                    self.config.main_model,
                    working_dir,
                    markdown_count,
                )
                return

            # Cluster modules
            working_dir = os.path.abspath(self.config.docs_dir)
            file_manager.ensure_directory(working_dir)
            first_module_tree_path = os.path.join(working_dir, FIRST_MODULE_TREE_FILENAME)
            module_tree_path = os.path.join(working_dir, MODULE_TREE_FILENAME)
            
            # Check if module tree exists
            if os.path.exists(first_module_tree_path):
                logger.debug(f"Module tree found at {first_module_tree_path}")
                module_tree = file_manager.load_json(first_module_tree_path)
            else:
                logger.debug(f"Module tree not found at {module_tree_path}, clustering modules")
                clustering_tokens = get_clustering_input_token_count(
                    leaf_nodes, components
                )
                logger.info(
                    "Preparing %d leaf nodes for module clustering (%d tokens, threshold %d)",
                    len(leaf_nodes),
                    clustering_tokens,
                    self.config.max_token_per_module,
                )
                # Bind cluster_model into the completer so the backend uses the
                # configured clustering model (separate from main_model) when
                # one is set.  Caw mode's cluster_model is typically empty —
                # complete() falls back to its own _model in that case.
                cluster_model = self.config.cluster_model or None
                module_tree = cluster_modules(
                    leaf_nodes,
                    components,
                    self.config,
                    completer=lambda p: self.backend.complete(p, model=cluster_model),
                )
                # Only freshly clustered trees are deduped: renaming a cached
                # key whose .md already exists would orphan the doc.
                module_tree = dedupe_module_tree_names(module_tree)
                file_manager.save_json(module_tree, first_module_tree_path)
            
            file_manager.save_json(module_tree, module_tree_path)
            
            if len(module_tree) == 0:
                logger.info(
                    "Module clustering produced no top-level modules; continuing in "
                    "whole-repository documentation mode"
                )
            else:
                logger.info(
                    "Grouped components into %d top-level modules",
                    len(module_tree),
                )
            
            # Generate module documentation using dynamic programming approach
            # This processes leaf modules first, then parent modules
            working_dir = await self.generate_module_documentation(components, leaf_nodes)
            
            # Create documentation metadata
            self.create_documentation_metadata(working_dir, components, len(leaf_nodes))

            # Reconcile the final module tree against the docs on disk so
            # name collisions or failed sub-agents can't pass silently (issue #76)
            missing_docs = self.validate_generated_docs(working_dir)
            if missing_docs:
                for module_name in missing_docs:
                    logger.error(f"Module doc missing after generation: {module_name}.md")
                raise IncompleteDocumentationError(missing_docs)

            markdown_count = sum(
                1 for name in os.listdir(working_dir) if name.endswith(".md")
            )
            logger.info(
                "Documentation generation completed: backend=%s provider=%s model=%s "
                "output=%s markdown_count=%d",
                type(self.backend).__name__,
                self.config.provider,
                self.config.main_model,
                working_dir,
                markdown_count,
            )
            
        except Exception as e:
            logger.error(f"Documentation generation failed: {str(e)}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            raise
