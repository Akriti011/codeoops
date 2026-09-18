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
_README_CHAR_CAP = int(os.getenv("EVIDENCE_README_CHAR_CAP", "1800"))
_REPRESENTATIVE_CHAR_CAP = int(os.getenv("EVIDENCE_REPRESENTATIVE_CHAR_CAP", "2400"))
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
    # SPA / front-end entry points — so a client isn't invisible just because
    # its code lives in one big file the signal scan skips.
    "index.html", "app.jsx", "app.tsx", "main.jsx", "main.tsx", "app.js", "app.vue",
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

# Any of these in a source file means it makes outbound HTTP calls — i.e. it
# talks to something *outside* this repository. Without this, an integration
# client only ever reaches the model if its file happens to win the
# representative-file ranking and survives truncation, which is why the same
# repo's integrations show up in one run and vanish in the next.
_HTTP_CLIENT_RE = re.compile(
    r'\b(?:requests\.(?:get|post|put|patch|delete|request|Session)'
    r'|httpx\.(?:get|post|put|patch|delete|Client|AsyncClient|stream)'
    r'|aiohttp\.ClientSession|urllib\.request\.urlopen|http\.client\.HTTPS?Connection'
    r'|axios(?:\.\w+)?\(|fetch\(|OkHttpClient|WebClient\.(?:create|builder)|RestTemplate)\b'
)

# (pattern, named external system). Checked only in files that already show an
# HTTP client or an integration-shaped filename. Order matters: first match wins.
_INTEGRATION_TARGETS: List[Tuple[re.Pattern[str], str]] = [
    (re.compile(r'api\.github\.com|github\.com/(?:repos|orgs|users)/|\bfrom\s+github\b|\bGithub\(|\bPyGithub\b|\bghapi\b'), "GitHub API"),
    (re.compile(r'\.atlassian\.net|/rest/api/(?:2|3|latest)/|/rest/agile/|\bfrom\s+jira\b|\bJIRA\(|\batlassian\b', re.I), "Jira / Atlassian API"),
    (re.compile(r'\bsonar(?:qube|cloud)?\b|/api/(?:measures|issues|qualitygates|project_analyses|components)\b', re.I), "SonarQube API"),
    (re.compile(r'api\.openai\.com|/v1/(?:chat/)?completions|/v1/embeddings|\bopenai\.(?:ChatCompletion|chat|Client)\b', re.I), "OpenAI API"),
    (re.compile(r'\bollama\b|:11434\b|/api/(?:generate|chat)\b', re.I), "Ollama / local LLM runtime"),
    (re.compile(r'\bactivitywatch\b|\baw[_-]?client\b|:5600\b|/api/0/buckets', re.I), "ActivityWatch API"),
    (re.compile(r'hooks\.slack\.com|\bslack_sdk\b|\bWebhookClient\b|chat\.postMessage', re.I), "Slack API"),
    (re.compile(r'api\.telegram\.org', re.I), "Telegram API"),
    (re.compile(r'\bstripe\b|api\.stripe\.com', re.I), "Stripe API"),
    (re.compile(r'\btwilio\b|api\.twilio\.com', re.I), "Twilio API"),
    (re.compile(r's3[.-][\w-]*\.amazonaws\.com|\bboto3\.client\(\s*[\'"]s3|\bboto3\.resource\(\s*[\'"]s3', re.I), "AWS S3"),
    (re.compile(r'(?:sqs|sns|dynamodb|lambda|secretsmanager)\.[\w-]*\.amazonaws\.com|\bboto3\.client\(\s*[\'"](?:sqs|sns|dynamodb|lambda|secretsmanager)', re.I), "AWS service API"),
    (re.compile(r'googleapis\.com|\bfrom\s+google\.cloud\b', re.I), "Google Cloud API"),
    (re.compile(r'\.blob\.core\.windows\.net|\bazure\.\w+\b', re.I), "Azure API"),
    (re.compile(r'\bsmtplib\b|\baiosmtplib\b|EmailMessage\(|/v3/mail/send|api\.sendgrid\.com|api\.mailgun\.net', re.I), "Email / SMTP"),
]

# Filenames that name an external system directly ("<thing>_service.py",
# "jiraClient.ts", "github_api.py"). A strong integration hint even before
# reading the file, so a small file that got truncated still gets flagged.
_INTEGRATION_FILENAME_RE = re.compile(
    r'(?:^|[/_.-])(?:service|client|api|integration|connector|gateway|adapter|provider|webhook)s?'
    r'(?:[/_.-]|\.\w+$)', re.I
)


def _scan_integrations(rel_path: str, content: str) -> List[str]:
    """One evidence line per external system a file talks to. Deterministic:
    the same file always yields the same lines, so integrations never silently
    drop between runs the way representative-file inclusion can."""
    has_http = bool(_HTTP_CLIENT_RE.search(content))
    name_hint = bool(_INTEGRATION_FILENAME_RE.search(rel_path))
    if not (has_http or name_hint):
        return []

    hits: List[str] = []
    for pattern, target in _INTEGRATION_TARGETS:
        if pattern.search(content):
            hits.append(f"{rel_path}: outbound integration -> {target}")
    if hits:
        return hits
    if has_http:
        return [f"{rel_path}: makes outbound HTTP calls to an external service "
                f"(specific target not identified from the evidence)"]
    return []


_UI_FRAMEWORK_RE = re.compile(
    r'"(react|react-dom|vue|@angular/core|svelte|next|nuxt|preact|solid-js)"\s*:', re.I
)


def _detect_ui(repo_path: str) -> List[str]:
    """A client/UI is easy to miss when it's one oversized bundle file the
    signal scan skips, or a plain-HTML+CDN app with no manifest the model
    recognises. Detect it structurally and state it as a fact — the overview
    prompt leans hard toward "name what is NOT present", so a tentative line
    here gets rounded down to "no frontend"."""
    ui_exts = (".jsx", ".tsx", ".vue", ".svelte")
    ext_files: Dict[str, List[str]] = {}
    ui_dirs: set[str] = set()
    framework: str | None = None
    saw_index_html: List[str] = []
    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [d for d in dirs if not _is_dir_excluded(d)]
        for name in files:
            rel = os.path.relpath(os.path.join(root, name), repo_path).replace(os.sep, "/")
            ext = os.path.splitext(name)[1].lower()
            if ext in ui_exts:
                ext_files.setdefault(ext, []).append(rel)
                ui_dirs.add(rel.rsplit("/", 1)[0] if "/" in rel else "(root)")
            if name.lower() == "index.html":
                saw_index_html.append(rel)
                ui_dirs.add(rel.rsplit("/", 1)[0] if "/" in rel else "(root)")
            if name.lower() == "package.json" and framework is None:
                content, _ = _read_capped(os.path.join(root, name), 4000)
                m = _UI_FRAMEWORK_RE.search(content)
                if m:
                    framework = m.group(1)

    if not ext_files and not saw_index_html:
        return []

    total = sum(len(v) for v in ext_files.values())
    ext_summary = ", ".join(f"{len(v)} {e}" for e, v in sorted(ext_files.items()))
    sample = sorted({f for v in ext_files.values() for f in v})[:6] or saw_index_html[:3]
    fw = f" ({framework})" if framework else (" (React/JSX)" if ".jsx" in ext_files else "")
    dirs_txt = ", ".join(sorted(d for d in ui_dirs if d != "(root)")) or "(repo root)"
    return [
        f"This repository DOES contain a client / front end{fw}. It is a real, "
        f"first-class component of the system — do not describe the repo as "
        f"backend-only or say no frontend was found.",
        f"Front-end location: {dirs_txt}/  ({total} component file(s): {ext_summary}"
        + (f"; index.html present" if saw_index_html else "") + ")",
        f"Front-end files: {', '.join(sample)}",
    ]


def _is_dir_excluded(dirname: str) -> bool:
    if dirname in _EXCLUDED_DIRS or dirname.endswith(".egg-info"):
        return True
    # A dot-prefixed name (e.g. ".runtime-venv") is already caught below, but
    # a non-dotted virtualenv name (e.g. "runtime-venv", "myenv") is not —
    # "venv" as a substring, or the universal "site-packages" subdirectory
    # every real Python venv has, both catch that regardless of naming.
    lower = dirname.lower()
    if "venv" in lower or lower == "site-packages":
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


def _build_module_map(components: Dict[str, Node]) -> str:
    """One line per source directory: how many components live there and the
    files that carry them. Deterministic from the dependency graph, so every
    real subsystem is named even when its files don't fit the evidence budget
    individually — this is what stops the overview from collapsing a
    multi-package backend into a single 'Backend Service' component."""
    by_dir: Dict[str, Dict[str, object]] = {}
    for node in components.values():
        rel = (node.relative_path or "").replace(os.sep, "/")
        if not rel or rel.startswith(".."):
            continue
        d = rel.rsplit("/", 1)[0] if "/" in rel else "(root)"
        slot = by_dir.setdefault(d, {"count": 0, "files": set()})
        slot["count"] = int(slot["count"]) + 1  # type: ignore[arg-type]
        files_set = slot["files"]
        if isinstance(files_set, set) and len(files_set) < 6:
            files_set.add(rel.rsplit("/", 1)[-1])
    if not by_dir:
        return ""
    lines: List[str] = []
    for d in sorted(by_dir):
        slot = by_dir[d]
        files = ", ".join(sorted(slot["files"])) if isinstance(slot["files"], set) else ""
        lines.append(f"- {d}/ — {slot['count']} component(s); files: {files}")
    return "\n".join(lines)


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
    integration_findings: List[str] = []
    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [d for d in dirs if not _is_dir_excluded(d)]
        for filename in files:
            abs_path = os.path.join(root, filename)
            rel_path = os.path.relpath(abs_path, repo_path)
            tier = _classify(rel_path, filename)
            if tier is not None:
                tiers[tier].append((rel_path, abs_path))
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
            if len(signal_findings) < _MAX_SIGNAL_FINDINGS:
                signal_findings.extend(_scan_signals(rel_path, content))
            integration_findings.extend(_scan_integrations(rel_path, content))
    # Dedup integrations, keep first occurrence order.
    _seen_int: set[str] = set()
    integration_findings = [
        x for x in integration_findings if not (x in _seen_int or _seen_int.add(x))
    ]
    ui_findings = _detect_ui(repo_path)
    module_map = _build_module_map(components)

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

    # External integrations next, in their own block so the model treats each
    # as a first-class system to document rather than a detail buried in a
    # file body it may or may not have received.
    if integration_findings:
        try_add(
            "Detected external integrations (each is a distinct system this repo calls out to)",
            ".",
            "\n".join(f"- {line}" for line in integration_findings[:30]),
        )

    if ui_findings:
        try_add(
            "Detected client / user interface",
            ".",
            "\n".join(f"- {line}" for line in ui_findings),
        )

    # Every source package by name, so a multi-package codebase is never
    # flattened into one component for lack of per-file evidence.
    if module_map:
        try_add("Source module map (from the dependency graph)", ".", module_map)

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
