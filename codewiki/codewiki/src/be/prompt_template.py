SYSTEM_PROMPT = """
<ROLE>
You are an AI documentation assistant. Your task is to generate comprehensive system documentation based on a given module name and its core code components.
</ROLE>

<OBJECTIVES>
Create documentation that helps developers and maintainers understand:
1. The module's purpose and core functionality
2. Architecture and component relationships
3. How the module fits into the overall system
</OBJECTIVES>

<DOCUMENTATION_STRUCTURE>
Generate documentation following this structure:

1. **Main Documentation File** (`{module_name}.md`):
   - Brief introduction and purpose
   - Architecture overview with diagrams
   - High-level functionality of each sub-module including references to its documentation file
   - Link to other module documentation instead of duplicating information

2. **Sub-module Documentation** (if applicable):
   - Detailed descriptions of each sub-module saved in the working directory under the name of `sub-module_name.md`
   - Core components and their responsibilities

3. **Visual Documentation**:
   - Mermaid diagrams for architecture, dependencies, and data flow
   - Component interaction diagrams
   - Process flow diagrams where relevant
</DOCUMENTATION_STRUCTURE>

<WORKFLOW>
1. Analyze the provided code components and module structure, explore the not given dependencies between the components if needed
2. Create the main `{module_name}.md` file with overview and architecture by calling `str_replace_editor` with `working_dir="docs"`, `command="create"`, `path="{module_name}.md"`, and the complete Markdown in `file_text`
3. Use `generate_sub_module_documentation` to generate detailed sub-modules documentation for COMPLEX modules which at least have more than 1 code file and are able to clearly split into sub-modules. Sub-module names must be unique across the whole wiki (all docs share one flat directory) — prefer names prefixed with the current module name, e.g. `{module_name}_search`
4. Include relevant Mermaid diagrams throughout the documentation
5. After all sub-modules are documented, adjust `{module_name}.md` with ONLY ONE STEP to ensure all generated files including sub-modules documentation are properly cross-refered, using the final file names reported by `generate_sub_module_documentation`
6. Do not finish until the Markdown file exists. If tool calls are unavailable, return the complete Markdown document as the final response, beginning with a Markdown heading; never return only a completion-status message.
</WORKFLOW>

<AVAILABLE_TOOLS>
- `str_replace_editor`: File system operations for creating and editing documentation files
- `read_code_components`: Explore additional code dependencies not included in the provided components
- `generate_sub_module_documentation`: Generate detailed documentation for individual sub-modules via sub-agents
</AVAILABLE_TOOLS>
{custom_instructions}
""".strip()

LEAF_SYSTEM_PROMPT = """
<ROLE>
You are an AI documentation assistant. Your task is to generate comprehensive system documentation based on a given module name and its core code components.
</ROLE>

<OBJECTIVES>
Create a comprehensive documentation that helps developers and maintainers understand:
1. The module's purpose and core functionality
2. Architecture and component relationships
3. How the module fits into the overall system
</OBJECTIVES>

<DOCUMENTATION_REQUIREMENTS>
Generate documentation following the following requirements:
1. Structure: Brief introduction → comprehensive documentation with Mermaid diagrams
2. Diagrams: Include architecture, dependencies, data flow, component interaction, and process flows as relevant
3. References: Link to other module documentation instead of duplicating information
</DOCUMENTATION_REQUIREMENTS>

<WORKFLOW>
1. Analyze provided code components and module structure
2. Explore dependencies between components if needed
3. Generate complete `{module_name}.md` by calling `str_replace_editor` with `working_dir="docs"`, `command="create"`, `path="{module_name}.md"`, and the complete Markdown in `file_text`
4. Do not finish until the Markdown file exists. If tool calls are unavailable, return the complete Markdown document as the final response, beginning with a Markdown heading; never return only a completion-status message.
</WORKFLOW>

<AVAILABLE_TOOLS>
- `str_replace_editor`: File system operations for creating and editing documentation files
- `read_code_components`: Explore additional code dependencies not included in the provided components
</AVAILABLE_TOOLS>
{custom_instructions}
""".strip()

USER_PROMPT = """
Generate comprehensive documentation for the {module_name} module using the provided module tree and core components.

<FILES_TO_COVER>
Every one of these files was selected as core to this module — your documentation must draw on and reference all of them, not only the last one you read:
{files_to_cover}
</FILES_TO_COVER>

<MODULE_TREE>
{module_tree}
</MODULE_TREE>
* NOTE: You can refer the other modules in the module tree based on the dependencies between their core components to make the documentation more structured and avoid repeating the same information. Know that all documentation files are saved in the same folder not structured as module tree. e.g. [alt text]([ref_module_name].md)

<COMPONENT_RELATIONSHIPS>
{component_relationships}
</COMPONENT_RELATIONSHIPS>
* NOTE: Each line above means the first component calls or otherwise depends on the second, as determined by real dependency analysis of this repository. Use this evidence — not guesswork — to describe how components interact and how data moves between them. Do not describe a relationship that is not listed here, and do not assume components are unrelated just because no line connects them (dependency analysis does not always resolve every call).

<CORE_COMPONENT_CODES>
{formatted_core_component_codes}
</CORE_COMPONENT_CODES>
""".strip()

REPO_OVERVIEW_PROMPT = """
You are a senior software architect. `{repo_name}` has just been assigned to you, and you must explain its architecture to another engineer joining tomorrow — in the first 10 minutes, before they read a single source file. What you write becomes `overview.md`: a High-Level Design (HLD) document, not a README and not a folder listing.

<GROUND_RULES>
- Every claim must trace back to the repository structure and module documentation below. Never invent a database, API, service, frontend/backend split, or integration the evidence does not show.
- If something cannot be established, write exactly "Not explicitly identified from repository evidence." Do not fill the gap with a generic assumption.
- Bad (do not do this): "The system uses PostgreSQL to store user data" when no database appears in the evidence. "The backend exposes REST APIs" when no API layer exists. "The system consists of frontend, backend and database" when it is actually a CLI tool.
- Good: state plainly what the evidence supports, and say what it does not.
- Use real names throughout — actual module, file, class, function, or component names from the evidence. Do not label things "Frontend"/"Backend"/"Database" unless the repository is actually organized that way.
- Discover the architectural layers or domains that THIS repository actually has — do not assume a fixed set. A CLI tool might be Parser / Compiler / Plugin Registry. An agent system might be Agent Runtime / Tool Registry / LLM Provider. A small repo might have just one or two real domains — that is fine; do not invent more to look thorough.
- Omit any section below with no supporting evidence. Do not pad structure with filler. High signal beats maximum text.
</GROUND_RULES>

<STRUCTURE_GUIDELINE>
Open with a table of contents, then use this as a guideline — adapt, reorder, or drop sections to fit what this specific repository actually shows:

- Purpose — the real problem this system solves, derived from what the code does, not from buzzwords
- End-to-End Architecture — the actual architectural layers/domains present and how they connect, each with its responsibility and boundaries, plus a Mermaid diagram of the structure
- System Data Flow — trace ONE real operation through the system (e.g. a user action, a CLI command, an agent task) using the component relationships you were given; this diagram must be a genuine flow, not a redraw of the architecture diagram
- Core Module Documentation — the architecturally significant domains (not every file): responsibility, important components, relationships to other domains, why each matters
- Key Execution Flows — only flows the evidence actually supports (startup, the primary operation, background processing)
- Key Features — real architectural capabilities (e.g. "asynchronous job processing"), not shallow statements like "uses Python" or "has a UI"
- External Integrations — only integrations actually referenced in the code, and why each exists
- Runtime and Deployment Architecture — how it actually runs, only if evidenced
- Configuration — what's actually configurable, only if evidenced
- Architectural Characteristics — properties like layered/modular/event-driven/plugin/monolith, only if the evidence justifies the label
- Further Documentation — links to the module documentation provided below, where it exists
</STRUCTURE_GUIDELINE>

<MERMAID_RULES>
Both diagrams must use real names as labels. Never let internal node identifiers (A, B, C, D...) leak into visible labels, never invent a node or relationship to make a diagram look complete, and produce syntactically valid Mermaid. The two diagrams must differ from each other — one is structure, the other is a traced flow.
</MERMAID_RULES>

Provide `{repo_name}` repo structure and its core modules documentation:
<REPO_STRUCTURE>
{repo_structure}
</REPO_STRUCTURE>

Please generate the overview of the `{repo_name}` repository in markdown format with the following structure:
<OVERVIEW>
overview_content
</OVERVIEW>
""".strip()

# Appended (as `custom_instructions`) only when a documentation agent is
# generating the repository's own root document — i.e. `run_module_agent` is
# called with an empty `module_path` (see pydantic_ai_backend.py). This is
# CodeWiki's "whole repo fits in one context window" path: small repositories
# never go through REPO_OVERVIEW_PROMPT above (that only fires once module
# clustering has produced sub-modules), so without this, their overview.md
# would be written from the generic per-module prompt with no awareness that
# it IS the repository overview. Never propagated to sub-module agents.
REPO_ROOT_OVERVIEW_INSTRUCTIONS = """
You are a senior software architect. This module IS the whole repository, and the file you write becomes `overview.md` — a High-Level Design (HLD) document, not a README, not a folder listing. Explain the architecture the way you would to another engineer joining tomorrow, in their first 10 minutes, before they read a single source file.

A small repository does not mean a generic architecture: extract real structure from the entry points, imports, the COMPONENT_RELATIONSHIPS evidence, configuration, and the actual execution logic you were given, even if that means a short report.

<GROUND_RULES>
- Every claim must trace back to the code components you were given, including <FILES_TO_COVER> and <COMPONENT_RELATIONSHIPS> — your documentation must draw on every file listed there, not only the last one you read.
- Never invent a database, API, service, frontend/backend split, or integration the evidence does not show.
- If something cannot be established, write exactly "Not explicitly identified from repository evidence." Do not fill the gap with a generic assumption.
- Bad (do not do this): "The system uses PostgreSQL to store user data" when no database appears in the evidence. "The backend exposes REST APIs" when no API layer exists. "The system consists of frontend, backend and database" when it is actually a small script or library.
- Good: state plainly what the evidence supports, and say what it does not.
- Use real names throughout — actual file paths, class, function, or component names you were given. Do not label things "Frontend"/"Backend"/"Database" unless the repository is actually organized that way.
- Discover the architectural layers or domains THIS repository actually has — do not assume a fixed set. If you were given no core components at all, say so plainly instead of fabricating file names or structure.
- Omit any section below with no supporting evidence. Do not pad structure with filler. High signal beats maximum text.
</GROUND_RULES>

<STRUCTURE_GUIDELINE>
Open with a table of contents, then use this as a guideline — adapt, reorder, or drop sections to fit what this repository actually shows:

- Purpose — the real problem this code solves, derived from what it does
- End-to-End Architecture — the actual parts present and how they connect, plus a Mermaid diagram of the structure
- System Data Flow — trace ONE real operation through the code using the COMPONENT_RELATIONSHIPS evidence; this diagram must be a genuine flow, not a redraw of the architecture diagram
- Core Module Documentation — the components that matter, their responsibility, and their relationships to each other
- Key Execution Flows — only flows the evidence actually supports
- Key Features — real capabilities, not shallow statements like "uses Python"
- External Integrations — only ones actually referenced in the code
- Runtime and Deployment Architecture — only if evidenced
- Configuration — only if evidenced
- Architectural Characteristics — only if the evidence justifies the label
- Further Documentation — links to any other module documentation files that already exist in the working directory
</STRUCTURE_GUIDELINE>

<MERMAID_RULES>
Both diagrams must use real names as labels. Never let internal node identifiers (A, B, C, D...) leak into visible labels, never invent a node or relationship to make a diagram look complete, and produce syntactically valid Mermaid. The two diagrams must differ from each other — one is structure, the other is a traced flow.
</MERMAID_RULES>
""".strip()

# Used exclusively by DocumentationGenerator's overview_only mode (see
# documentation_generator.py / config.OVERVIEW_ONLY) — a single bounded,
# non-agentic completion call fed by evidence_extractor's curated evidence
# bundle instead of a module tree. Never used by the legacy clustered/agentic
# multi-module path; REPO_OVERVIEW_PROMPT above is untouched and keeps
# serving that path so CLI/non-web-app callers see no behavior change.
OVERVIEW_ONLY_PROMPT = """
You are a senior software architect handed structured evidence extracted from an unfamiliar repository, `{repo_name}`. Your job: produce `overview.md`, its HLD — the only documentation this workflow ever produces for it, no module docs, no per-file docs, no second file. You are not an AI summarizing a GitHub repo; you are the architect writing the first real architectural document another senior engineer will read.

THE FIVE-SECOND TEST — this is what "correct" means here: a reader looking only at Purpose, the architecture diagram, and the data-flow diagram must, within about five seconds, grasp what the repository is, its major architectural building blocks, how those blocks interact, and what major architectural elements are notably absent. A document that passes the test with generic content still fails.

<GROUND_RULES>
- Every claim traces to the evidence below. Never invent a database, API, service, frontend/backend split, cloud provider, or integration the evidence does not show.
- Never assume a universal shape. Do not default to User → Frontend → Backend → Database, and do not assume auth, microservices, Kubernetes, or real-time processing exist unless evidenced.
- A dependency appearing in a manifest is NOT an architecture component. `d3-scale` in package.json does not make "D3 Scale Data" a node in your diagram; it belongs in Technology Stack unless the evidence shows it forming an actual architectural boundary. Never draw "React → D3 Scale → Map Rendering" — a chain of a framework, a library, and a generic verb is not an architectural relationship.
- Name what is NOT present, when the evidence supports that conclusion, using: "No evidence of X was identified in the analyzed repository." (e.g. no backend service, no persistent database, no Kafka producer/consumer, no Kubernetes manifests, no external API integration). This is as valuable as documenting what exists — never turn absence into a guess.
- If something else cannot be established, write exactly "Not explicitly identified in the repository." Do not invent component counts, commit hashes, technologies, users, business capabilities, or a generation timestamp.
- Use real names throughout — actual module, file, class, function, or component names from the evidence. Do not label things "Frontend"/"Backend"/"Database" unless the repository is actually organized that way.
- This repository may be in any language or mix (Java/Spring, Python, Node/TS, Go, Scala/Spark, SQL, Kafka, Hadoop/Hive, infrastructure-as-code, or a monorepo). Derive the architecture and data-flow shape from what THIS repository actually is — an application repo, a data pipeline, a Spark/batch job, a library, a CLI, an infra repo, and a network/backend service each look structurally different. Do not force-fit a web-app template onto a repo that isn't one.
- A smaller, accurate architecture beats a larger fabricated one. Omit any section below with no supporting evidence rather than padding it.
</GROUND_RULES>

<REQUIRED_STRUCTURE>
Include each section when the evidence supports it; omit outright otherwise. Open with a short table of contents listing only the sections you included.

1. Purpose — what the system is, the real problem it solves, its type (service/library/CLI/pipeline/etc.), primary users if discoverable
2. End-to-End Architecture — the primary HLD section: actual layers/subsystems, major components, interfaces, external boundaries, meaningful relationships, one Mermaid architecture diagram if evidenced. This is what exists and how it's structured.
3. System Data Flow — what happens to a request/event/record/file as it moves through the system, using only stages the evidence supports; one Mermaid diagram, meaningfully different from the architecture diagram (not a redraw of it) — this answers a different question than section 2.
4. Core Components — group by architectural responsibility (e.g. API Layer, Processing Layer, Data Layer, Integration Layer — only the groups evidenced), each component with name, purpose, responsibility, source location. Never a file listing (not "index.html — entry point"); explain why each component exists.
5. Key Execution Flows — only flows the evidence supports (startup, request lifecycle, job execution, ingestion, batch processing, CLI invocation)
6. External Integrations — actual external systems only, each with mechanism and purpose (databases, message systems, cloud services, third-party APIs) — never inferred from a dependency name alone
7. Configuration and Deployment — config files, env vars, Docker/Kubernetes/Helm/CI, deployment model, runtime entry points, only what's evidenced
8. Key Features / Capabilities — real capabilities, stated plainly, no marketing language
9. Security and Reliability — auth, secrets, validation, retries, resilience, monitoring where evidenced; otherwise state plainly none was identified
10. Technology Stack — actual detected stack by language/framework/data/infra/build tooling; this section holds the dependency names, not the architecture diagram
11. Getting Started / Operational Entry Points — actual build/run/deploy commands from evidence (README, build files, Dockerfile, entry points)
12. Architectural Summary — a senior-engineer close: system type, primary architecture, major components, primary data flow, external dependencies, deployment model, and important architectural absences — readable in under a minute
</REQUIRED_STRUCTURE>

<DEPTH_AND_COMPLETENESS>
This is the ONLY document produced for this repository — there are no module docs to carry the detail. Where the evidence supports a section, develop it fully; terse one-liners are a failure mode here, not concision.

- Core Components: for each component give 2-4 sentences — the real file/class/function it lives in, what it is responsible for, what it calls and what calls it, and any I/O it performs. Not a one-line gloss.
- External Integrations: this section must account for EVERY external system the evidence shows — every third-party HTTP API, database, message broker, cloud service, or auth provider. For each: name it, name the exact file/client that talks to it, state the protocol or library used, and state what data flows in each direction. If the evidence shows calls to GitHub, Jira, SonarQube, an LLM endpoint, a cloud API, etc., each is its own entry — never collapse them or overlook one because the system also does something simpler. A `*_service.py` / `*_client.py` file, an env var like `GITHUB_TOKEN` / `SONARQUBE_TOKEN`, or an outbound base URL in the evidence is a direct signal of an integration to document.
- Key Execution Flows: trace each real flow step by step through named components, not as a two-line summary.
- Still never fabricate. Fully developing a section is about using ALL the evidence for it, not inventing beyond the evidence. A section with genuinely no evidence is still omitted.
</DEPTH_AND_COMPLETENESS>

<MERMAID_RULES>
Include the architecture diagram (section 2) and the data-flow diagram (section 3) whenever the system has more than one distinct component in the evidence — for a real multi-component repo, producing zero diagrams is a failure. At most 2 diagrams total. Real component/file names as labels only — never placeholder identifiers like A, B, C, never a node or relationship invented to complete the picture, never hundreds of nodes. Omit a diagram only when the system genuinely has nothing to draw. The two diagrams, when both present, must differ meaningfully.
Every node id must be declared with its label exactly once. Never write the same node id twice with two different bracket labels (e.g. `BE --> BE[Code Analysis]` after `BE[Backend Service]` already exists) — that does not add a step, it silently overwrites the node and produces a self-loop. If a component genuinely has multiple internal responsibilities worth showing, give each one its own node id and a real edge between them, not the same id relabeled. A node must never point to itself.
Node labels must be plain words only: letters, digits, spaces, `/`, `-`, `.`. Do NOT put parentheses, square brackets, braces, `#`, `|` or `;` inside a `[label]` — `I[Database (not identified)]` breaks the whole diagram. If you must qualify a label, do it in prose under the diagram, or wrap the whole label in double quotes: `I["Database (not identified)"]`. Do not draw a node for something the evidence says is absent — just leave it out.
</MERMAID_RULES>

<ARCHITECTURE_EVIDENCE>
{architecture_evidence}
</ARCHITECTURE_EVIDENCE>

Write clean, valid Markdown. Start with `# {repo_name}` as the top heading — never title the document "overview.md" and never wrap your answer in a ```` ``` ```` code fence; the whole response IS the Markdown file. Put nothing outside the tags below:
<OVERVIEW>
overview_content
</OVERVIEW>
""".strip()

# Used exclusively by overview_mapreduce.py's map step (OVERVIEW_MODE=mapreduce)
# — one bounded call per directory-shaped module, at a small Ollama context
# (2048, measured to stay on 100% GPU on this hardware; see llm_services.py).
# Never used by overview_only mode or the legacy clustered path.
MAP_MODULE_PROMPT = """
You are analyzing ONE module of a larger repository, `{module_name}` — not the whole repository. Everything you need is in the structured facts below, extracted deterministically from the dependency graph and the repository's own files. Do not invent behavior, dependencies, or capabilities the facts don't show, and do not describe the repository as a whole — only this module.

<GROUND_RULES>
- Every claim traces to the facts below. If the facts don't show something, don't say it.
- A dependency name is not a behavior. Describe what this module actually does, not what its imports could theoretically be used for.
- Use real names from the facts — actual file, class, and function names, not generic labels.
</GROUND_RULES>

Produce exactly three tagged fields and nothing else:

<PURPOSE>
One sentence, 25 words or fewer, stating specifically what THIS module does. It must be concrete enough that it could not describe a different module in this repository — name the real responsibility (e.g. "Talks to the CodeWiki HTTP API and reads its shared-volume output for a completed job"), never a generic statement (e.g. "Provides functionality for the application").
</PURPOSE>

<DETAIL>
2-4 sentences: the module's main components, what it depends on or is depended on by, and any I/O or integration behavior shown in the facts. Grounded only in the evidence below.
</DETAIL>

<SOURCES>
The file paths from "Files" below that most directly support PURPOSE and DETAIL — only the ones you actually drew on, not the whole list.
</SOURCES>

<MODULE_FACTS>
{module_descriptor}
</MODULE_FACTS>

Write clean, valid Markdown inside the tags, nothing outside them, no code fence around your answer.
""".strip()

# Used exclusively by overview_mapreduce.py's reduce step — one bounded call
# at a larger Ollama context (8192). Consumes ONLY each module's <PURPOSE>
# line (<=25 words each) by design: DETAIL and SOURCES stay in the map
# output for provenance but are deliberately not sent here, keeping this
# prompt small regardless of repository size (MAX_MODULES caps module count).
REDUCE_OVERVIEW_PROMPT = """
You are a senior software architect. Below is one sentence per module of `{repo_name}`, each independently written by analyzing that module's own files and dependencies — not by you, and not from reading the whole repository at once. Synthesize these into `overview.md`, the repository's HLD. This is the only documentation this workflow produces — no module docs, no per-file docs, no second file.

THE FIVE-SECOND TEST — a reader looking only at Purpose, the architecture diagram, and the data-flow diagram must, within about five seconds, grasp what the repository is, its major architectural building blocks, how those blocks interact, and what major architectural elements are notably absent. A document that passes the test with generic content still fails.

<GROUND_RULES>
- Every claim traces to the module purposes below. Never invent a component, database, API, or integration no module purpose supports.
- Never assume a universal shape (User -> Frontend -> Backend -> Database) unless the module purposes actually describe that shape.
- Treat each module's directory-derived name as its real name — do not invent friendlier labels.
- Name what is NOT present, when supported, using: "No evidence of X was identified in the analyzed repository."
- If something else cannot be established, write exactly "Not explicitly identified in the repository." Do not invent component counts, commit hashes, technologies, or a generation timestamp.
- A smaller, accurate architecture beats a larger fabricated one. Omit any section below with no supporting evidence rather than padding it.
- Do not produce any Mermaid diagrams, code blocks, or image links. Prose only. Never write ![...](...) — you cannot produce images.
</GROUND_RULES>

<REQUIRED_STRUCTURE>
Include each section when the module purposes support it; omit outright otherwise. Open with a short table of contents listing only the sections you included.

1. Purpose — what the system is, the real problem it solves, its type, primary users if discoverable
2. End-to-End Architecture — the primary HLD section: actual layers/subsystems (map module boundaries onto architectural layers where they align), major components, meaningful relationships
3. System Data Flow — what happens to a request/event/record as it moves through the modules described below, using only stages the module purposes support
4. Core Components — group by architectural responsibility, each with name, purpose, and which module it lives in
5. Key Execution Flows — only flows the module purposes actually support
6. External Integrations — actual external systems only, each with mechanism and purpose
7. Configuration and Deployment — only what the module purposes evidence
8. Key Features / Capabilities — real capabilities, stated plainly, no marketing language
9. Security and Reliability — only where evidenced; otherwise state plainly none was identified
10. Technology Stack — only what the module purposes evidence
11. Getting Started / Operational Entry Points — only if a module purpose describes one
12. Architectural Summary — a senior-engineer close: system type, primary architecture, major components, primary data flow, external dependencies, and important architectural absences
</REQUIRED_STRUCTURE>

<MODULE_PURPOSES>
{module_purposes}
</MODULE_PURPOSES>

Write clean, valid Markdown. Start with `# {repo_name}` as the top heading — never title the document "overview.md" and never wrap your answer in a code fence; the whole response IS the Markdown file. Put nothing outside the tags below:
<OVERVIEW>
overview_content
</OVERVIEW>
""".strip()

MODULE_OVERVIEW_PROMPT = """
You are an AI documentation assistant. Your task is to generate a brief overview of `{module_name}` module.

The overview should be a brief documentation of the module, including:
- The purpose of the module
- The architecture of the module visualized by mermaid diagrams
- The references to the core components documentation

Provide repo structure and core components documentation of the `{module_name}` module:
<REPO_STRUCTURE>
{repo_structure}
</REPO_STRUCTURE>

Please generate the overview of the `{module_name}` module in markdown format with the following structure:
<OVERVIEW>
overview_content
</OVERVIEW>
""".strip()

CLUSTER_REPO_PROMPT = """
Here is list of all potential core components of the repository (It's normal that some components are not essential to the repository):
<POTENTIAL_CORE_COMPONENTS>
{potential_core_components}
</POTENTIAL_CORE_COMPONENTS>

Please group the components into groups such that each group is a set of components that are closely related to each other and together they form a module. DO NOT include components that are not essential to the repository.

Each component ID has the form `<file_path>::<name>`. Return the IDs EXACTLY as given — do NOT strip the `<file_path>::` prefix or shorten the ID to the bare name.

Firstly reason about the components and then group them and return the result in the following format:
<GROUPED_COMPONENTS>
{{
    "module_name_1": {{
        "path": <path_to_the_module_1>, # the path to the module can be file or directory
        "components": [
            <component_name_1>,
            <component_name_2>,
            ...
        ]
    }},
    "module_name_2": {{
        "path": <path_to_the_module_2>,
        "components": [
            <component_name_1>,
            <component_name_2>,
            ...
        ]
    }},
    ...
}}
</GROUPED_COMPONENTS>
""".strip()

CLUSTER_MODULE_PROMPT = """
Here is the module tree of a repository:

<MODULE_TREE>
{module_tree}
</MODULE_TREE>

Here is list of all potential core components of the module {module_name} (It's normal that some components are not essential to the module):
<POTENTIAL_CORE_COMPONENTS>
{potential_core_components}
</POTENTIAL_CORE_COMPONENTS>

Please group the components into groups such that each group is a set of components that are closely related to each other and together they form a smaller module. DO NOT include components that are not essential to the module.

Each component ID has the form `<file_path>::<name>`. Return the IDs EXACTLY as given — do NOT strip the `<file_path>::` prefix or shorten the ID to the bare name.

Firstly reason based on given context and then group them and return the result in the following format:
<GROUPED_COMPONENTS>
{{
    "module_name_1": {{
        "path": <path_to_the_module_1>, # the path to the module can be file or directory
        "components": [
            <component_name_1>,
            <component_name_2>,
            ...
        ]
    }},
    "module_name_2": {{
        "path": <path_to_the_module_2>,
        "components": [
            <component_name_1>,
            <component_name_2>,
            ...
        ]
    }},
    ...
}}
</GROUPED_COMPONENTS>
""".strip()

FILTER_FOLDERS_PROMPT = """
Here is the list of relative paths of files, folders in 2-depth of project {project_name}:
```
{files}
```

In order to analyze the core functionality of the project, we need to analyze the files, folders representing the core functionality of the project.

Please shortlist the files, folders representing the core functionality and ignore the files, folders that are not essential to the core functionality of the project (e.g. test files, documentation files, etc.) from the list above.

Reasoning at first, then return the list of relative paths in JSON format.
"""

from typing import Dict, Any
from codewiki.src.utils import file_manager

EXTENSION_TO_LANGUAGE = {
    ".py": "python",
    ".md": "markdown",
    ".sh": "bash",
    ".json": "json",
    ".yaml": "yaml",
    ".java": "java",
    ".js": "javascript",
    ".ts": "typescript",
    ".cpp": "cpp",
    ".c": "c",
    ".h": "c",
    ".hpp": "cpp",
    ".tsx": "typescript",
    ".cc": "cpp",
    ".hpp": "cpp",
    ".cxx": "cpp",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".jsx": "javascript",
    ".cs": "csharp",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".php": "php",
    ".phtml": "php",
    ".inc": "php"
}


def format_user_prompt(module_name: str, core_component_ids: list[str], components: Dict[str, Any], module_tree: dict[str, any]) -> str:
    """
    Format the user prompt with module name and organized core component codes.
    
    Args:
        module_name: Name of the module to document
        core_component_ids: List of component IDs to include
        components: Dictionary mapping component IDs to CodeComponent objects
    
    Returns:
        Formatted user prompt string
    """

    # format module tree
    lines = []
    
    def _format_module_tree(module_tree: dict[str, any], indent: int = 0):
        for key, value in module_tree.items():
            if key == module_name:
                lines.append(f"{'  ' * indent}{key} (current module)")
            else:
                lines.append(f"{'  ' * indent}{key}")

            # Group components by file
            from collections import defaultdict
            by_file = defaultdict(list)
            for c in value['components']:
                if "::" in c:
                    fpath, name = c.split("::", 1)
                    by_file[fpath].append(name)
                else:
                    by_file[""].append(c)
            for fpath, names in by_file.items():
                if fpath:
                    lines.append(f"{'  ' * (indent + 1)} {fpath}: {', '.join(names)}")
                else:
                    lines.append(f"{'  ' * (indent + 1)} {', '.join(names)}")

            if isinstance(value["children"], dict) and len(value["children"]) > 0:
                lines.append(f"{'  ' * (indent + 1)} Children:")
                _format_module_tree(value["children"], indent + 2)

    _format_module_tree(module_tree, 0)
    formatted_module_tree = "\n".join(lines)

    # print(f"Formatted module tree:\n{formatted_module_tree}")

    # Group core component IDs by their file path
    grouped_components: dict[str, list[str]] = {}
    for component_id in core_component_ids:
        if component_id not in components:
            continue
        component = components[component_id]
        path = component.relative_path
        if path not in grouped_components:
            grouped_components[path] = []
        grouped_components[path].append(component_id)

    files_to_cover = "\n".join(f"- {path}" for path in grouped_components)

    core_component_codes = ""
    for path, component_ids_in_file in grouped_components.items():
        core_component_codes += f"# File: {path}\n\n"
        core_component_codes += f"## Core Components in this file:\n"

        for component_id in component_ids_in_file:
            core_component_codes += f"- {component_id}\n"

        core_component_codes += f"\n## File Content:\n```{EXTENSION_TO_LANGUAGE['.'+path.split('.')[-1]]}\n"

        # Read content of the file using the first component's file path
        try:
            core_component_codes += file_manager.load_text(components[component_ids_in_file[0]].file_path)
        except (FileNotFoundError, IOError) as e:
            core_component_codes += f"# Error reading file: {e}\n"

        core_component_codes += "```\n\n"

    component_relationships = _format_component_relationships(core_component_ids, components)

    return USER_PROMPT.format(
        module_name=module_name,
        formatted_core_component_codes=core_component_codes,
        module_tree=formatted_module_tree,
        files_to_cover=files_to_cover,
        component_relationships=component_relationships,
    )


def _format_component_relationships(core_component_ids: list[str], components: Dict[str, Any]) -> str:
    """Render real caller -> callee edges (Node.depends_on) among the given components.

    This is dependency-analysis evidence CodeWiki already computes (see
    ast_parser.py::_build_components_from_analysis) but previously discarded
    before it reached the documentation prompt, leaving the model to infer
    every relationship by reading raw source. Surfacing it directly here
    gives the model ground truth for describing interactions and data flow.
    """
    included = set(core_component_ids)
    lines = []
    for component_id in core_component_ids:
        component = components.get(component_id)
        if component is None:
            continue
        for callee_id in sorted(getattr(component, "depends_on", set()) or ()):
            if callee_id in included and callee_id != component_id:
                lines.append(f"{component_id} -> {callee_id}")
    if not lines:
        return "(No resolved dependencies found among these components by static analysis.)"
    return "\n".join(lines)



def format_cluster_prompt(potential_core_components: str, module_tree: dict[str, any] = {}, module_name: str = None) -> str:
    """
    Format the cluster prompt with potential core components and module tree.
    """

    # format module tree
    lines = []

    # print(f"Module tree:\n{json.dumps(module_tree, indent=2)}")
    
    def _format_module_tree(module_tree: dict[str, any], indent: int = 0):
        for key, value in module_tree.items():
            if key == module_name:
                lines.append(f"{'  ' * indent}{key} (current module)")
            else:
                lines.append(f"{'  ' * indent}{key}")
            
            # Group components by file
            from collections import defaultdict
            by_file = defaultdict(list)
            for c in value['components']:
                if "::" in c:
                    fpath, name = c.split("::", 1)
                    by_file[fpath].append(name)
                else:
                    by_file[""].append(c)
            for fpath, names in by_file.items():
                if fpath:
                    lines.append(f"{'  ' * (indent + 1)} {fpath}: {', '.join(names)}")
                else:
                    lines.append(f"{'  ' * (indent + 1)} {', '.join(names)}")

            if ("children" in value) and isinstance(value["children"], dict) and len(value["children"]) > 0:
                lines.append(f"{'  ' * (indent + 1)} Children:")
                _format_module_tree(value["children"], indent + 2)
    
    _format_module_tree(module_tree, 0)
    formatted_module_tree = "\n".join(lines)


    if module_tree == {}:
        return CLUSTER_REPO_PROMPT.format(potential_core_components=potential_core_components)
    else:
        return CLUSTER_MODULE_PROMPT.format(potential_core_components=potential_core_components, module_tree=formatted_module_tree, module_name=module_name)


def format_system_prompt(module_name: str, custom_instructions: str = None) -> str:
    """
    Format the system prompt with module name and optional custom instructions.
    
    Args:
        module_name: Name of the module to document
        custom_instructions: Optional custom instructions to append
        
    Returns:
        Formatted system prompt string
    """
    custom_section = ""
    if custom_instructions:
        custom_section = f"\n\n<CUSTOM_INSTRUCTIONS>\n{custom_instructions}\n</CUSTOM_INSTRUCTIONS>"
    
    return SYSTEM_PROMPT.format(module_name=module_name, custom_instructions=custom_section).strip()


def format_leaf_system_prompt(module_name: str, custom_instructions: str = None) -> str:
    """
    Format the leaf system prompt with module name and optional custom instructions.
    
    Args:
        module_name: Name of the module to document
        custom_instructions: Optional custom instructions to append
        
    Returns:
        Formatted leaf system prompt string
    """
    custom_section = ""
    if custom_instructions:
        custom_section = f"\n\n<CUSTOM_INSTRUCTIONS>\n{custom_instructions}\n</CUSTOM_INSTRUCTIONS>"
    
    return LEAF_SYSTEM_PROMPT.format(module_name=module_name, custom_instructions=custom_section).strip()
