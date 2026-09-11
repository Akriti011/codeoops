"""Grounding check for a generated document against the structured Overview IR.

No LLM. It scans the finished Markdown for concrete references — file paths,
component names, environment variables, technology names — and classifies each
against the IR's deterministic fact sets:

* **FACT**       — the reference exists verbatim in the analysed project.
* **INFERRED**   — a partial/loose match (e.g. a bare filename that matches a
                   real path's basename); plausible but not exact.
* **UNSUPPORTED**— nothing in the analysed project backs it. These are the
                   candidate hallucinations.

The result is a compact report plus a ``## Verification`` block that is
appended to the document, so a reader always sees what was checked and what
could not be grounded. A larger model is a capability upgrade, not an
accuracy guarantee — this is the accuracy check that runs regardless of model.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List

from codewiki.src.be.overview_ir import ir_fact_sets

_CODE_EXT = (
    "py|pyi|ts|tsx|js|jsx|mjs|cjs|java|kt|go|rb|rs|cs|scala|sql|sh|"
    "yaml|yml|json|toml|ini|cfg|md|html|css|scss|proto|graphql|tf"
)
_FILE_RE = re.compile(rf"(?<![\w./-])([\w./-]+\.(?:{_CODE_EXT}))(?![\w.-])")
_ENV_RE = re.compile(r"(?<![\w-])([A-Z][A-Z0-9_]{3,})(?![\w-])")
_MERMAID_BLOCK_RE = re.compile(r"```mermaid.*?```", re.DOTALL)
_CODE_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)

# Common English ALL-CAPS tokens that are not env vars.
_ENV_STOPWORDS = {
    "HTTP", "HTTPS", "REST", "JSON", "YAML", "HTML", "CSS", "API", "APIS",
    "CRUD", "SQL", "URL", "URLS", "URI", "UUID", "CPU", "GPU", "RAM", "TODO",
    "NOTE", "HLD", "LLD", "CI", "CD", "AWS", "GCP", "IDE", "SDK", "CLI", "ORM",
    "DTO", "MVC", "TLS", "SSL", "JWT", "RBAC", "SLA", "SLO", "KPI", "AND", "OR",
    "NOT", "THE", "FOR", "WITH", "FROM", "THIS", "THAT",
}


def _strip_mermaid(markdown: str) -> str:
    """Drop mermaid blocks — their labels are validated elsewhere and would
    otherwise flood the env/component scan with node ids."""
    return _MERMAID_BLOCK_RE.sub("", markdown)


def validate_doc(markdown: str, ir: Dict[str, Any], *, doc_kind: str) -> Dict[str, Any]:
    facts = ir_fact_sets(ir)
    text = _strip_mermaid(markdown or "")

    real_files = facts["files"]
    real_basenames = {f.rsplit("/", 1)[-1] for f in real_files}

    file_refs = sorted(set(_FILE_RE.findall(text)))
    file_facts: List[str] = []
    file_inferred: List[str] = []
    file_unsupported: List[str] = []
    for ref in file_refs:
        norm = ref.lstrip("./")
        if norm in real_files or any(f.endswith("/" + norm) or f == norm for f in real_files):
            file_facts.append(ref)
        elif ref.rsplit("/", 1)[-1] in real_basenames:
            file_inferred.append(ref)
        else:
            file_unsupported.append(ref)

    # env vars — exclude those inside fenced code blocks (shell examples etc.)
    prose = _CODE_FENCE_RE.sub("", text)
    env_refs = {
        e for e in _ENV_RE.findall(prose) if e not in _ENV_STOPWORDS and "_" in e or e in facts["env"]
    }
    env_facts = sorted(e for e in env_refs if e in facts["env"])
    env_unsupported = sorted(e for e in env_refs if e not in facts["env"])

    # technology mentions that contradict the detected stack are only flagged
    # when they name a data store the project shows no sign of.
    db_terms = {
        "postgres": "postgresql", "postgresql": "postgresql", "mysql": "mysql",
        "mongodb": "mongodb", "mongo": "mongodb", "redis": "redis",
        "sqlite": "sqlite", "cassandra": "cassandra", "dynamodb": "dynamodb",
        "elasticsearch": "elasticsearch", "kafka": "kafka",
    }
    tech = facts["tech"]
    has_any_db_signal = any(
        any(k in t for k in db_terms) for t in tech
    ) or any(f.endswith(".sql") for f in real_files)
    db_claims = sorted(
        {canon for term, canon in db_terms.items() if re.search(rf"\b{term}\b", text, re.I)}
    )
    unsupported_db = [] if has_any_db_signal else [
        c for c in db_claims if not any(c in t for t in tech)
    ]

    checked = len(file_refs) + len(env_facts) + len(env_unsupported) + len(db_claims)
    unsupported = (
        [f"file `{f}` — not in the analysed project" for f in file_unsupported]
        + [f"env var `{e}` — not found in any config file" for e in env_unsupported]
        + [f"data store **{d}** — no schema, driver or dependency for it was detected" for d in unsupported_db]
    )

    report = {
        "doc_kind": doc_kind,
        "checked_references": checked,
        "grounded": {
            "files": file_facts,
            "env_vars": env_facts,
        },
        "inferred": {
            "files": file_inferred,
        },
        "unsupported": unsupported,
        "unsupported_count": len(unsupported),
        "verdict": "clean" if not unsupported else "review",
    }
    return report


def verification_block(report: Dict[str, Any], ir: Dict[str, Any]) -> str:
    """A ``## Verification`` section to append to the generated document."""
    proj = ir.get("project", {})
    lines = [
        "",
        "---",
        "",
        "## Verification",
        "",
        f"This {report['doc_kind'].upper()} was generated from a structured overview of "
        f"`{proj.get('name', 'the project')}` "
        f"({proj.get('component_count', 0)} components across {proj.get('module_count', 0)} "
        f"modules, {proj.get('file_count', 0)} source files).",
        "",
        f"- **{report['checked_references']}** concrete references checked against the analysed code.",
        f"- **{len(report['grounded']['files'])}** file references and "
        f"**{len(report['grounded']['env_vars'])}** environment variables matched real project facts.",
    ]
    if report["inferred"]["files"]:
        lines.append(
            f"- **{len(report['inferred']['files'])}** references were inferred (basename match "
            f"only, not an exact path): "
            + ", ".join(f"`{f}`" for f in report["inferred"]["files"][:12])
        )
    if report["unsupported"]:
        lines.append(
            f"- **{report['unsupported_count']} unsupported reference(s)** — treat as unverified:"
        )
        lines.extend(f"  - {u}" for u in report["unsupported"][:20])
    else:
        lines.append("- **No unsupported references** were found in this document.")
    lines += [
        "",
        "> Grounding is a deterministic check against the dependency graph and the "
        "detected technology stack — not a guarantee of architectural correctness. "
        "A stronger model improves reasoning quality; it does not remove the need "
        "for this check.",
        "",
    ]
    return "\n".join(lines)
