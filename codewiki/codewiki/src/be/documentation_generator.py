import logging
import os
import json
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
from codewiki.src.be.prompt_template import (
    REPO_OVERVIEW_PROMPT,
    MODULE_OVERVIEW_PROMPT,
    OVERVIEW_ONLY_PROMPT,
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
    return text.strip()


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
            "%d component(s), %d leaf node(s)",
            repo_name, len(components), len(leaf_nodes),
        )

        architecture_evidence = evidence_extractor.build_architecture_evidence(
            self.config, components, leaf_nodes
        )
        prompt = OVERVIEW_ONLY_PROMPT.format(
            repo_name=repo_name,
            architecture_evidence=architecture_evidence,
        )

        try:
            response = self.backend.complete(
                prompt,
                temperature=0.2,
                max_tokens=OVERVIEW_ONLY_MAX_OUTPUT_TOKENS,
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

        if not overview_content:
            raise IncompleteDocumentationError(["overview"])

        file_manager.save_text(overview_content, overview_path)
        logger.info(
            "Single-shot overview written: path=%s bytes=%d",
            overview_path, os.path.getsize(overview_path),
        )
        return working_dir

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
