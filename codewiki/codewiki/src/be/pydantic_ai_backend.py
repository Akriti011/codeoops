"""PydanticAIBackend — the existing API-key based path.

This backend is a thin adapter over :func:`call_llm` and the pydantic-ai
``Agent`` machinery.  Behaviour is preserved exactly; this file only
repackages it behind the :class:`LLMBackend` interface so the rest of
CodeWiki can be backend-agnostic.
"""

from __future__ import annotations

import logging
import os
import traceback
from typing import Any, Dict, List

from pydantic_ai import Agent

from codewiki.src.be.agent_tools.deps import CodeWikiDeps
from codewiki.src.be.agent_tools.read_code_components import read_code_components_tool
from codewiki.src.be.agent_tools.str_replace_editor import str_replace_editor_tool
from codewiki.src.be.backend import LLMBackend
from codewiki.src.be.dependency_analyzer.models.core import Node
from codewiki.src.be.llm_services import call_llm, create_fallback_models
from codewiki.src.be.prompt_template import (
    REPO_ROOT_OVERVIEW_INSTRUCTIONS,
    format_leaf_system_prompt,
    format_system_prompt,
    format_user_prompt,
)
from codewiki.src.be.module_naming import resolve_module_doc_path
from codewiki.src.be.utils import is_complex_module
from codewiki.src.config import MODULE_TREE_FILENAME, OVERVIEW_FILENAME, Config
from codewiki.src.utils import file_manager

logger = logging.getLogger(__name__)


class ModuleDocumentationNotWrittenError(RuntimeError):
    """Raised when an agent finishes without creating its required Markdown file."""

    def __init__(
        self,
        module_name: str,
        expected_path: str,
        tool_calls: list[str],
        output_preview: str,
    ) -> None:
        self.module_name = module_name
        self.expected_path = expected_path
        self.tool_calls = tool_calls
        super().__init__(
            "Documentation agent completed without writing "
            f"{expected_path} for module {module_name!r}. "
            f"Tool calls: {', '.join(tool_calls) if tool_calls else 'none'}. "
            f"Output preview: {output_preview!r}"
        )


def _tool_call_names(result: Any) -> list[str]:
    """Return tool calls from a PydanticAI result without relying on internals."""
    names: list[str] = []
    try:
        messages = result.new_messages()
    except (AttributeError, TypeError):
        return names
    for message in messages:
        for part in getattr(message, "parts", []):
            name = getattr(part, "tool_name", None)
            if isinstance(name, str) and name:
                names.append(name)
    return names


def _markdown_from_agent_output(result: Any) -> str | None:
    """Accept a substantive Markdown final response when a model skipped tools.

    Tool calling remains the preferred path. This compatibility path exists for
    OpenAI-compatible models that return the requested documentation as their
    terminal response instead of issuing the instructed write-tool call.
    """
    output = getattr(result, "output", None)
    if not isinstance(output, str):
        return None
    text = output.strip()
    if "<OVERVIEW>" in text and "</OVERVIEW>" in text:
        text = text.split("<OVERVIEW>", 1)[1].split("</OVERVIEW>", 1)[0].strip()
    if len(text) < 200 or "#" not in text:
        return None
    return text + "\n"


class PydanticAIBackend(LLMBackend):
    """API-key based backend using pydantic-ai + openai/litellm clients."""

    def __init__(self, config: Config) -> None:
        self._config = config
        self._fallback_models = create_fallback_models(config)
        self._custom_instructions = config.get_prompt_addition()

    def complete(
        self,
        prompt: str,
        *,
        model: str | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
        num_ctx: int | None = None,
    ) -> str:
        return call_llm(
            prompt, self._config, model=model, temperature=temperature, max_tokens=max_tokens,
            num_ctx=num_ctx,
        )

    async def run_module_agent(
        self,
        module_name: str,
        components: Dict[str, Node],
        core_component_ids: List[str],
        module_path: List[str],
        working_dir: str,
    ) -> Dict[str, Any]:
        config = self._config
        module_tree_path = os.path.join(working_dir, MODULE_TREE_FILENAME)
        module_tree = file_manager.load_json(module_tree_path)

        overview_docs_path = os.path.join(working_dir, OVERVIEW_FILENAME)
        if os.path.exists(overview_docs_path):
            logger.info("✓ Overview docs already exists at %s", overview_docs_path)
            return module_tree
        docs_path = os.path.join(working_dir, f"{module_name}.md")
        existing_docs_path = resolve_module_doc_path(working_dir, module_name)
        if existing_docs_path is not None:
            logger.info("✓ Module docs already exists at %s", existing_docs_path)
            return module_tree

        logger.info(
            "Documentation agent start: backend=%s provider=%s model=%s module=%s "
            "output=%s components=%d",
            type(self).__name__,
            config.provider,
            config.main_model,
            module_name,
            docs_path,
            len(core_component_ids),
        )

        # An empty module_path means this agent's output IS overview.md (the
        # "whole repo fits in one context window" path — see
        # documentation_generator.py). That case never goes through
        # REPO_OVERVIEW_PROMPT, so make this agent's own system prompt
        # overview-aware here. Deliberately not stored on `deps` below: a
        # complex root module can spawn sub-module agents via
        # generate_sub_module_documentation_tool, which read
        # deps.custom_instructions verbatim, and those sub-modules are not
        # the repository root.
        own_instructions = self._custom_instructions
        if not module_path:
            own_instructions = (
                f"{own_instructions}\n\n{REPO_ROOT_OVERVIEW_INSTRUCTIONS}"
                if own_instructions
                else REPO_ROOT_OVERVIEW_INSTRUCTIONS
            )

        if is_complex_module(components, core_component_ids):
            # Deferred: only this (legacy agentic, non-overview_only) branch
            # needs this tool. Importing it at module level made every
            # DocumentationGenerator construction — including overview_only
            # mode, which never reaches this branch — fail immediately with
            # ImportError, since generate_sub_module_documentations.py's own
            # `from ...llm_services import LLMRequestTimeoutError` references
            # a class that does not exist in this codebase's llm_services.py.
            from codewiki.src.be.agent_tools.generate_sub_module_documentations import (
                generate_sub_module_documentation_tool,
            )

            agent = Agent(
                self._fallback_models,
                name=module_name,
                deps_type=CodeWikiDeps,
                tools=[
                    read_code_components_tool,
                    str_replace_editor_tool,
                    generate_sub_module_documentation_tool,
                ],
                system_prompt=format_system_prompt(module_name, own_instructions),
            )
        else:
            agent = Agent(
                self._fallback_models,
                name=module_name,
                deps_type=CodeWikiDeps,
                tools=[read_code_components_tool, str_replace_editor_tool],
                system_prompt=format_leaf_system_prompt(module_name, own_instructions),
            )

        deps = CodeWikiDeps(
            absolute_docs_path=working_dir,
            absolute_repo_path=str(os.path.abspath(config.repo_path)),
            registry={},
            components=components,
            path_to_current_module=module_path,
            current_module_name=module_name,
            module_tree=module_tree,
            max_depth=config.max_depth,
            current_depth=1,
            config=config,
            custom_instructions=self._custom_instructions,
        )

        try:
            result = await agent.run(
                format_user_prompt(
                    module_name=module_name,
                    core_component_ids=core_component_ids,
                    components=components,
                    module_tree=deps.module_tree,
                ),
                deps=deps,
            )
            tool_calls = _tool_call_names(result)
            logger.info(
                "Documentation agent completed: module=%s tool_calls=%s",
                module_name,
                ",".join(tool_calls) if tool_calls else "none",
            )

            written_path = resolve_module_doc_path(working_dir, module_name)
            if written_path is None:
                markdown = _markdown_from_agent_output(result)
                if markdown is not None:
                    file_manager.save_text(markdown, docs_path)
                    written_path = docs_path
                    logger.warning(
                        "Documentation agent returned Markdown without a write-tool "
                        "call; materialized %s for module=%s",
                        docs_path,
                        module_name,
                    )
            if written_path is None:
                output = getattr(result, "output", "")
                preview = str(output).strip().replace("\n", " ")[:240]
                raise ModuleDocumentationNotWrittenError(
                    module_name,
                    docs_path,
                    tool_calls,
                    preview,
                )
            logger.info(
                "Documentation Markdown written: module=%s path=%s bytes=%d",
                module_name,
                written_path,
                os.path.getsize(written_path),
            )
            file_manager.save_json(deps.module_tree, module_tree_path)
            return deps.module_tree
        except Exception as e:
            logger.error("Error processing module %s: %s", module_name, e)
            logger.error("Traceback: %s", traceback.format_exc())
            raise
