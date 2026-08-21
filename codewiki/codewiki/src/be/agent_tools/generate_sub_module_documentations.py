import asyncio
import os

from pydantic_ai import RunContext, Tool, Agent

from codewiki.src.be.agent_tools.deps import CodeWikiDeps
from codewiki.src.be.module_naming import normalize_sub_module_specs, resolve_module_doc_path
from codewiki.src.be.agent_tools.read_code_components import read_code_components_tool
from codewiki.src.be.agent_tools.str_replace_editor import str_replace_editor_tool
from codewiki.src.be.llm_services import LLMRequestTimeoutError, create_fallback_models
from codewiki.src.be.prompt_template import SYSTEM_PROMPT, LEAF_SYSTEM_PROMPT, format_user_prompt
from codewiki.src.be.utils import is_complex_module, count_tokens
from codewiki.src.be.cluster_modules import format_potential_core_components
from codewiki.src.utils import file_manager

import logging
logger = logging.getLogger(__name__)


def _submodule_markdown_from_result(result: object) -> str | None:
    """Return a substantive Markdown terminal response, if the model supplied one."""
    output = getattr(result, "output", None)
    if not isinstance(output, str):
        return None
    markdown = output.strip()
    if len(markdown) < 200 or "#" not in markdown:
        return None
    return markdown + "\n"



async def generate_sub_module_documentation(
    ctx: RunContext[CodeWikiDeps],
    sub_module_specs: dict[str, list[str]]
) -> str:
    """Delegate documentation generation of sub-modules to sub-agents. Each sub-module will be documented separately.

    Args:
        sub_module_specs: A dictionary mapping sub-module names to their core component IDs.
            Example: {"authentication": ["auth_handler.py::AuthHandler", "auth_middleware.py::verify_token"], "database": ["db_client.py::DBClient", "models.py::UserModel"]}
            Each key is a descriptive sub-module name, and the value is a list of component IDs from the current module's core components that belong to that sub-module.
            Sub-module names must be unique across the whole wiki; a name that is already used by another
            module is automatically prefixed with the current module name, and the tool result reports the
            final file names actually saved.
    """

    deps = ctx.deps
    previous_module_name = deps.current_module_name

    # Create fallback models from config
    fallback_models = create_fallback_models(deps.config)

    # Resolve name collisions against the module tree and files already on disk
    # before touching the tree (issue #76): docs live in one flat directory.
    name_map = normalize_sub_module_specs(
        sub_module_specs,
        previous_module_name,
        deps.module_tree,
        deps.absolute_docs_path,
    )
    final_specs = {
        name_map[requested_name]: core_component_ids
        for requested_name, core_component_ids in sub_module_specs.items()
    }

    # add the sub-module to the module tree
    value = deps.module_tree
    for key in deps.path_to_current_module:
        value = value[key]["children"]
    for sub_module_name, core_component_ids in final_specs.items():
        value[sub_module_name] = {"components": core_component_ids, "children": {}}

    for sub_module_name, core_component_ids in final_specs.items():

        # Create visual indentation for nested modules
        indent = "  " * deps.current_depth
        arrow = "└─" if deps.current_depth > 0 else "→"

        logger.info(f"{indent}{arrow} Generating documentation for sub-module: {sub_module_name}")

        num_tokens = count_tokens(format_potential_core_components(core_component_ids, ctx.deps.components)[-1])
        
        if is_complex_module(ctx.deps.components, core_component_ids) and ctx.deps.current_depth < ctx.deps.max_depth and num_tokens >= ctx.deps.config.max_token_per_leaf_module:
            sub_agent = Agent(
                model=fallback_models,
                name=sub_module_name,
                deps_type=CodeWikiDeps,
                system_prompt=SYSTEM_PROMPT.format(module_name=sub_module_name, custom_instructions=ctx.deps.custom_instructions),
                tools=[read_code_components_tool, str_replace_editor_tool, generate_sub_module_documentation_tool],
            )
        else:
            sub_agent = Agent(
                model=fallback_models,
                name=sub_module_name,
                deps_type=CodeWikiDeps,
                system_prompt=LEAF_SYSTEM_PROMPT.format(module_name=sub_module_name, custom_instructions=ctx.deps.custom_instructions),
                tools=[read_code_components_tool, str_replace_editor_tool],
            )

        deps.current_module_name = sub_module_name
        deps.path_to_current_module.append(sub_module_name)
        deps.current_depth += 1
        # log the current module tree
        # print(f"Current module tree: {json.dumps(deps.module_tree, indent=4)}")

        try:
            logger.info(
                "Waiting for sub-module model response: module=%s timeout_seconds=%d",
                sub_module_name,
                deps.config.llm_timeout_seconds,
            )
            try:
                result = await asyncio.wait_for(
                    sub_agent.run(
                        format_user_prompt(
                            module_name=deps.current_module_name,
                            core_component_ids=core_component_ids,
                            components=ctx.deps.components,
                            module_tree=ctx.deps.module_tree,
                        ),
                        deps=ctx.deps,
                    ),
                    timeout=deps.config.llm_timeout_seconds,
                )
            except asyncio.TimeoutError as exc:
                raise LLMRequestTimeoutError(
                    f"Sub-module documentation agent timed out for {sub_module_name!r} "
                    f"after {deps.config.llm_timeout_seconds} seconds."
                ) from exc

            written_path = resolve_module_doc_path(
                deps.absolute_docs_path, sub_module_name
            )
            if written_path is None:
                markdown = _submodule_markdown_from_result(result)
                if markdown is not None:
                    written_path = os.path.join(
                        deps.absolute_docs_path, f"{sub_module_name}.md"
                    )
                    file_manager.save_text(markdown, written_path)
                    logger.warning(
                        "Sub-agent returned Markdown without a write-tool call; "
                        "materialized %s",
                        written_path,
                    )
            if written_path is None:
                output = str(getattr(result, "output", "")).strip().replace("\n", " ")
                raise RuntimeError(
                    "Sub-module documentation agent completed without writing "
                    f"{sub_module_name}.md. Output preview: {output[:240]!r}"
                )
            logger.info(
                "Sub-module documentation written: module=%s path=%s bytes=%d",
                sub_module_name,
                written_path,
                os.path.getsize(written_path),
            )
        finally:
            # Restore the parent's traversal state even when a child agent fails.
            deps.path_to_current_module.pop()
            deps.current_depth -= 1

    # restore the previous module name
    deps.current_module_name = previous_module_name

    # Report what actually landed on disk so the parent agent links real filenames.
    saved = []
    missing = []
    for requested_name, final_name in name_map.items():
        entry = f"{final_name}.md"
        if final_name != requested_name:
            entry += f" (requested '{requested_name}', renamed to avoid a collision)"
        if os.path.exists(os.path.join(deps.absolute_docs_path, f"{final_name}.md")):
            saved.append(entry)
        else:
            missing.append(entry)

    report = f"Saved documentations: {', '.join(saved) if saved else 'none'}."
    if missing:
        report += f" MISSING (generation did not produce these files): {', '.join(missing)}."
        logger.warning("Sub-module documentation missing after generation: %s", ", ".join(missing))
    return report


generate_sub_module_documentation_tool = Tool(
    function=generate_sub_module_documentation, 
    name="generate_sub_module_documentation", 
    takes_ctx=True
)
