"""Deterministic, non-LLM curation of architectural evidence for single-shot
repository overview generation (see documentation_generator.py's overview_only
path). No LLM calls; purely filesystem- and dependency-graph-driven.

The token budget for this evidence is small (see EVIDENCE_TOKEN_BUDGET —
tuned down hard on an 8GB Ollama host, see llm_services.py's context-size
notes), so this prioritizes density over volume: compact, one-line
*architectural signals* (detected entry points, interface boundaries such as
REST/Kafka/gRPC/CLI, dependency names) ahead of raw file dumps. A dependency
name or a "REST endpoints found in X" line costs a handful of tokens and
tells the model more about architecture than the same tokens spent on raw
manifest JSON or config YAML ever would.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Dict, List, Tuple

from codewiki.src.be.dependency_analyzer.models.core import Node
from codewiki.src.be.utils import count_tokens
from codewiki.src.config import Config

logger = logging.getLogger(__name__)

EVIDENCE_TOKEN_BUDGET = int(os.getenv("EVIDENCE_TOKEN_BUDGET", "3500"))
_MAX_REPRESENTATIVE_FILES = int(os.getenv("EVIDENCE_MAX_REPRESENTATIVE_FILES", "8"))
_MAX_SIGNAL_FINDINGS = int(os.getenv("EVIDENCE_MAX_SIGNAL_FINDINGS", "18"))
_README_CHAR_CAP = 1200
_REPRESENTATIVE_CHAR_CAP = 1200
_SIGNAL_SCAN_FILE_SIZE_CAP = 200_000  # skip pathologically large source files

_EXCLUDED_DIRS = frozenset(
    {
        ".git", "node_modules", "vendor", "dist", "build", "target", ".venv",
        "venv", "__pycache__", ".tox", ".pytest_cache", ".next", ".nuxt",
        "coverage", ".mypy_cache", ".idea", ".vscode",
    }
)

_MANIFEST_NAMES = {
    "package.json", "pyproject.toml", "requirements.txt", "requirements-dev.txt",
    "pom.xml", "build.gradle", "build.gradle.kts", "go.mod", "cargo.toml",
    "gemfile", "composer.json", "setup.py", "setup.cfg",
}
_CONFIG_NAMES = {
    "dockerfile", "chart.yaml", "values.yaml", ".env.example",
}
_ENTRYPOINT_NAMES = {
    "main.py", "__main__.py", "manage.py", "app.py", "index.ts", "index.js",
    "main.go", "main.java", "program.cs",
}
_SIGNAL_SCAN_EXTENSIONS = {
    ".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".go", ".rb", ".rs", ".cs",
}

_TIER_ORDER: List[Tuple[str, str]] = [
    ("readme", "README"),
    ("manifest", "Dependency manifest"),
    ("config", "Deployment/config"),
    ("api", "API/interface definition"),
    ("entrypoint", "Entry point"),
]

# (pattern, description). Matched once per file; each hit becomes one compact
# "path: description" evidence line instead of a raw file dump. Deliberately
# a bounded, common-case set (not a general-purpose static analyzer) — good
# enough recall on mainstream stacks beats a slow, incomplete general parser.
_SIGNAL_PATTERNS: List[Tuple[re.Pattern[str], str]] = [
    (re.compile(r'@?\b(app|router)\.(get|post|put|delete|patch)\('), "REST endpoint (app/router route definition)"),
    (re.compile(r'@(Get|Post|Put|Delete|Patch)Mapping\('), "REST endpoint (Spring MVC)"),
    (re.compile(r'@RestController\b'), "REST controller (Spring)"),
    (re.compile(r'@SpringBootApplication\b'), "application entry point (Spring Boot)"),
    (re.compile(r'if\s+__name__\s*==\s*[\'"]__main__[\'"]'), "script entry point"),
    (re.compile(r'public\s+static\s+void\s+main\s*\('), "main entry point (Java)"),
    (re.compile(r'func\s+main\s*\(\s*\)'), "main entry point (Go)"),
    (re.compile(r'\buvicorn\.run\('), "ASGI server startup (uvicorn)"),
    (re.compile(r'\bapp\.listen\('), "HTTP server startup (Node/Express)"),
    (re.compile(r'\bKafkaProducer\b'), "Kafka producer"),
    (re.compile(r'\bKafkaConsumer\b'), "Kafka consumer"),
    (re.compile(r'@KafkaListener\b'), "Kafka consumer (Spring Kafka)"),
    (re.compile(r'\bSparkSession\b'), "Spark job"),
    (re.compile(r'\bhive\.'), "Hive interaction", ),
    (re.compile(r'\bboto3\.'), "AWS SDK usage (boto3)"),
    (re.compile(r'argparse\.ArgumentParser\('), "CLI entry point (argparse)"),
    (re.compile(r'@click\.command\b'), "CLI entry point (click)"),
    (re.compile(r'\bWebSocket\b'), "WebSocket interface"),
    (re.compile(r'\bgrpc\.'), "gRPC usage"),
    (re.compile(r'\bredis\.(Redis|StrictRedis)\('), "Redis cache client"),
    (re.compile(r'\b(create_engine|SQLAlchemy)\('), "SQL database ORM (SQLAlchemy)"),
    (re.compile(r'@Entity\b'), "JPA entity (data layer)"),
    (re.compile(r'\bmongoose\.(model|Schema)\('), "MongoDB model (Mongoose)"),
]


def _is_dir_excluded(dirname: str) -> bool:
    if dirname in _EXCLUDED_DIRS or dirname.endswith(".egg-info"):
        return True
    return dirname.startswith(".") and dirname != ".github"


def _classify(rel_path: str, filename: str) -> str | None:
    lower = filename.lower()
    normalized = rel_path.replace(os.sep, "/").lower()

    if lower.startswith("readme."):
        return "readme"
    if lower in _MANIFEST_NAMES:
        return "manifest"
    if lower in _CONFIG_NAMES or lower.startswith("docker-compose."):
        return "config"
    if lower.endswith((".yml", ".yaml")) and (
        "/.github/workflows/" in normalized or "/k8s/" in normalized
    ):
        return "config"
    if lower.startswith(("openapi.", "swagger.")):
        return "api"
    if lower.endswith((".proto", ".graphql")):
        return "api"
    if lower in _ENTRYPOINT_NAMES:
        return "entrypoint"
    return None


def _read_capped(path: str, cap_chars: int = 4000) -> Tuple[str, bool]:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            text = f.read(cap_chars + 1)
    except OSError:
        return "", False
    truncated = len(text) > cap_chars
    return text[:cap_chars], truncated


def _extract_dependency_names(rel_path: str, content: str) -> List[str] | None:
    """Compact tech-stack signal: dependency *names* only, not the whole
    manifest. A raw package.json/pom.xml can cost hundreds of tokens for the
    same information a 10-token name list already conveys. Returns None for
    manifest formats not worth special-casing (falls back to a raw, capped
    dump for those)."""
    lower = rel_path.lower()
    names: List[str] = []
    try:
        if lower.endswith("package.json"):
            data = json.loads(content)
            for key in ("dependencies", "devDependencies"):
                names.extend(data.get(key, {}).keys())
        elif lower.endswith(("requirements.txt", "requirements-dev.txt")):
            for line in content.splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    name = re.split(r"[<>=!~\[; ]", line, 1)[0].strip()
                    if name:
                        names.append(name)
        elif lower.endswith("pom.xml"):
            names = re.findall(r"<artifactId>([^<]+)</artifactId>", content)
        elif lower.endswith(("build.gradle", "build.gradle.kts")):
            names = re.findall(r"""['"]([\w.\-]+:[\w.\-]+):[\w.\-]+['"]""", content)
        elif lower.endswith("go.mod"):
            names = re.findall(r"^\s*([\w.\-/]+)\s+v[\d.]", content, re.MULTILINE)
        else:
            return None
    except Exception:
        return None
    # Dedup, preserve order, cap.
    seen: set[str] = set()
    unique = [n for n in names if not (n in seen or seen.add(n))]
    return unique[:40] if unique else None


def _extract_config_key_lines(rel_path: str, content: str) -> str | None:
    """Compact deployment signal for Dockerfile/docker-compose — only the
    lines that establish runtime shape (base image, exposed ports, the
    startup command), not the full build recipe."""
    lower = rel_path.lower()
    if "dockerfile" in lower:
        keep = [
            line for line in content.splitlines()
            if re.match(r'^\s*(FROM|EXPOSE|CMD|ENTRYPOINT)\b', line, re.IGNORECASE)
        ]
        return "\n".join(keep) if keep else None
    if "docker-compose" in lower:
        keep = [
            line for line in content.splitlines()
            if re.match(r'^\s*(services|image|ports|environment)\s*:', line)
            or re.match(r'^\s{2,4}[\w\-]+:\s*$', line)
        ]
        return "\n".join(keep[:30]) if keep else None
    return None


def _scan_signals(rel_path: str, content: str) -> List[str]:
    hits: List[str] = []
    descriptions_seen: set[str] = set()
    for pattern, description in _SIGNAL_PATTERNS:
        if description in descriptions_seen:
            continue
        if pattern.search(content):
            hits.append(f"{rel_path}: {description}")
            descriptions_seen.add(description)
    return hits


def _rank_representative_files(
    components: Dict[str, Node], leaf_nodes: List[str], limit: int
) -> List[str]:
    """Rank files by in-degree (how often other components depend on them) —
    a proxy for architectural centrality, computed from the already-built
    dependency graph rather than a fresh LLM call."""
    in_degree: Dict[str, int] = {}
    for node in components.values():
        for dep_id in node.depends_on:
            dep = components.get(dep_id)
            if dep is not None:
                in_degree[dep.relative_path] = in_degree.get(dep.relative_path, 0) + 1
    for leaf_id in leaf_nodes:
        node = components.get(leaf_id)
        if node is not None:
            in_degree.setdefault(node.relative_path, 0)
    ranked = sorted(in_degree.items(), key=lambda kv: kv[1], reverse=True)
    return [path for path, _ in ranked[:limit]]


def build_architecture_evidence(
    config: Config, components: Dict[str, Node], leaf_nodes: List[str]
) -> str:
    repo_path = os.path.abspath(config.repo_path)
    budget = EVIDENCE_TOKEN_BUDGET

    tiers: Dict[str, List[Tuple[str, str]]] = {name: [] for name, _ in _TIER_ORDER}
    signal_findings: List[str] = []
    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [d for d in dirs if not _is_dir_excluded(d)]
        for filename in files:
            abs_path = os.path.join(root, filename)
            rel_path = os.path.relpath(abs_path, repo_path)
            tier = _classify(rel_path, filename)
            if tier is not None:
                tiers[tier].append((rel_path, abs_path))
                continue
            if len(signal_findings) >= _MAX_SIGNAL_FINDINGS:
                continue
            ext = os.path.splitext(filename)[1].lower()
            if ext not in _SIGNAL_SCAN_EXTENSIONS:
                continue
            try:
                if os.path.getsize(abs_path) > _SIGNAL_SCAN_FILE_SIZE_CAP:
                    continue
            except OSError:
                continue
            content, _ = _read_capped(abs_path, cap_chars=20_000)
            signal_findings.extend(_scan_signals(rel_path, content))

    sections: List[str] = []
    included: List[str] = []
    dropped: List[str] = []
    running_tokens = 0

    def try_add(label: str, rel_path: str, content: str) -> None:
        nonlocal running_tokens
        block = f"## {label}: {rel_path}\n\n```\n{content}\n```\n"
        block_tokens = count_tokens(block)
        if running_tokens + block_tokens > budget:
            dropped.append(rel_path)
            return
        sections.append(block)
        running_tokens += block_tokens
        included.append(rel_path)

    if os.path.isdir(repo_path):
        top_level = sorted(
            name for name in os.listdir(repo_path)
            if name not in _EXCLUDED_DIRS and not name.startswith(".git")
        )
        try_add("Top-level structure", ".", "\n".join(top_level))

    # Detected architectural signals go first (after structure): highest
    # information density per token of anything gathered here.
    if signal_findings[:_MAX_SIGNAL_FINDINGS]:
        try_add(
            "Detected architectural signals (entry points, interfaces, data layer)",
            ".",
            "\n".join(f"- {line}" for line in signal_findings[:_MAX_SIGNAL_FINDINGS]),
        )

    readme_tier, manifest_tier, config_tier, api_tier, entrypoint_tier = (
        tiers[name] for name, _ in _TIER_ORDER
    )

    for rel_path, abs_path in sorted(readme_tier):
        content, truncated = _read_capped(abs_path, cap_chars=_README_CHAR_CAP)
        if truncated:
            content += "\n... (truncated)"
        try_add("README", rel_path, content)

    for rel_path, abs_path in sorted(manifest_tier):
        raw, truncated = _read_capped(abs_path, cap_chars=3000)
        names = _extract_dependency_names(rel_path, raw)
        if names:
            try_add("Dependencies declared in", rel_path, ", ".join(names))
        else:
            if truncated:
                raw += "\n... (truncated)"
            try_add("Dependency manifest", rel_path, raw)

    for rel_path, abs_path in sorted(config_tier):
        raw, truncated = _read_capped(abs_path, cap_chars=3000)
        key_lines = _extract_config_key_lines(rel_path, raw)
        if key_lines:
            try_add("Deployment/config (key lines)", rel_path, key_lines)
        else:
            if truncated:
                raw += "\n... (truncated)"
            try_add("Deployment/config", rel_path, raw)

    for rel_path, abs_path in sorted(api_tier):
        content, truncated = _read_capped(abs_path, cap_chars=2000)
        if truncated:
            content += "\n... (truncated)"
        try_add("API/interface definition", rel_path, content)

    for rel_path, abs_path in sorted(entrypoint_tier):
        content, truncated = _read_capped(abs_path, cap_chars=1500)
        if truncated:
            content += "\n... (truncated)"
        try_add("Entry point", rel_path, content)

    for rel_path in _rank_representative_files(components, leaf_nodes, _MAX_REPRESENTATIVE_FILES):
        abs_path = os.path.join(repo_path, rel_path)
        content, truncated = _read_capped(abs_path, cap_chars=_REPRESENTATIVE_CHAR_CAP)
        if truncated:
            content += "\n... (truncated)"
        try_add("Representative component", rel_path, content)

    if dropped:
        preview = ", ".join(dropped[:20]) + ("..." if len(dropped) > 20 else "")
        logger.info(
            "Architecture evidence budget (%d tokens) reached; included %d file(s), "
            "dropped %d: %s",
            budget, len(included), len(dropped), preview,
        )
    else:
        logger.info(
            "Architecture evidence assembled from %d file(s), %d tokens (budget %d), "
            "%d detected signal(s).",
            len(included), running_tokens, budget, len(signal_findings),
        )

    if not sections:
        logger.warning(
            "No architecture evidence files found under %s; overview will rely on "
            "the repository name alone.",
            repo_path,
        )
        return (
            "(No README, dependency manifest, configuration, or entry-point files "
            "were found in this repository.)"
        )

    return "\n".join(sections)
