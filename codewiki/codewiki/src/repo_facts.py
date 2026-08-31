"""Stage 1 — deterministic Repository Fact Sheet (OVERVIEW_QUALITY_SPEC.md
section 3).

No LLM call anywhere in this file. Every field on :class:`RepoFacts` is
extracted by parsing files on disk and by walking the dependency graph the
analyzer already builds (``codewiki.src.be.dependency_analyzer``) — nothing
here is invented, and nothing here is inferred from prose.

This is the layer the spec calls "unhallucinatable": a dependency name, an
entry-point file:line, a config key either exist in the repository or they
do not. Stage 2+ (module descriptors, section generation) consume this as
ground truth; they do not re-derive it.

Debug entry point (writes a JSON dump of RepoFacts for a real repository)::

    python -m codewiki.src.repo_facts --repo <path> --out facts.json
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import tomllib
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import yaml

from codewiki.src.be.dependency_analyzer.models.core import Node
from codewiki.src.be.evidence_extractor import _EXCLUDED_DIRS, _read_capped
from codewiki.src.be.module_grouper import ModuleGroup

# --------------------------------------------------------------------------
# Dataclasses — verbatim per spec section 3.
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Dependency:
    name: str
    version: Optional[str]
    manifest: str  # which file it came from


@dataclass(frozen=True)
class EntryPoint:
    kind: str  # "main" | "console_script" | "http_route" | "docker_cmd"
    #           | "npm_script" | "spark_submit" (plus two pragmatic
    #           extensions this implementation adds — see module docstring
    #           note below on "kind is a plain str, not a closed enum").
    name: str
    file: str
    line: int
    detail: Optional[str]  # route path, command string, ...


@dataclass(frozen=True)
class ConfigItem:
    name: str  # env var or settings field
    source: str  # file where referenced
    default: Optional[str]
    required: bool


@dataclass(frozen=True)
class LanguageStat:
    language: str
    files: int
    lines: int


@dataclass(frozen=True)
class ModuleEdge:
    source: str
    target: str
    weight: int  # number of distinct imports


@dataclass(frozen=True)
class RepoFacts:
    name: str
    commit_sha: Optional[str]
    total_files: int
    total_lines: int
    languages: List[LanguageStat]
    directory_tree: str  # 3 levels, rendered
    dependencies: List[Dependency]
    manifests_found: List[str]
    entry_points: List[EntryPoint]
    config_items: List[ConfigItem]
    module_edges: List[ModuleEdge]
    hub_modules: List[str]  # highest in-degree, ranked
    leaf_modules: List[str]
    cycles: List[List[str]]
    readme_text: Optional[str]  # verbatim, truncated to 4000 chars
    other_docs: Dict[str, str]  # ARCHITECTURE.md, CONTRIBUTING.md, ...
    test_files: int
    test_framework: Optional[str]
    has_dockerfile: bool
    has_ci: bool
    ci_files: List[str]


# --------------------------------------------------------------------------
# Shared constants
# --------------------------------------------------------------------------

_README_CHAR_CAP = 4000
_MAX_DEPENDENCIES = 40
_DIRECTORY_TREE_DEPTH = 3
_OTHER_DOC_NAMES = {
    "architecture.md", "contributing.md", "design.md", "adr.md",
    "changelog.md", "security.md",
}
_OTHER_DOC_CHAR_CAP = 4000

_LANGUAGE_BY_EXT: Dict[str, str] = {
    ".py": "Python", ".pyi": "Python",
    ".js": "JavaScript", ".jsx": "JavaScript", ".mjs": "JavaScript", ".cjs": "JavaScript",
    ".ts": "TypeScript", ".tsx": "TypeScript",
    ".java": "Java",
    ".kt": "Kotlin", ".kts": "Kotlin",
    ".scala": "Scala",
    ".go": "Go",
    ".rs": "Rust",
    ".rb": "Ruby",
    ".php": "PHP",
    ".c": "C", ".h": "C",
    ".cpp": "C++", ".cc": "C++", ".cxx": "C++", ".hpp": "C++",
    ".cs": "C#",
    ".sh": "Shell", ".bash": "Shell",
    ".sql": "SQL",
    ".html": "HTML", ".htm": "HTML",
    ".css": "CSS", ".scss": "CSS", ".sass": "CSS",
    ".yml": "YAML", ".yaml": "YAML",
    ".json": "JSON",
    ".md": "Markdown",
    ".proto": "Protocol Buffers",
    ".graphql": "GraphQL",
}

_TEST_FILE_RE = re.compile(r"(^|/)(test_[\w\-]+|[\w\-]+_test|[\w\-]+\.test|[\w\-]+\.spec)\.\w+$")
_TEST_FRAMEWORK_MANIFEST_HINTS: List[Tuple[str, str]] = [
    ("pytest", "pytest"),
    ("unittest", "unittest"),
    ("jest", "jest"),
    ("mocha", "mocha"),
    ("vitest", "vitest"),
    ("junit", "JUnit"),
    ("rspec", "RSpec"),
    ("go test", "go test"),
]


def _walk_repo_files(repo_path: str) -> List[str]:
    """Every non-excluded file, relative path, forward-slash separated.
    Reused by every extractor below instead of each re-walking the tree."""
    out: List[str] = []
    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [d for d in dirs if not _is_excluded_dir(d)]
        for filename in files:
            abs_path = os.path.join(root, filename)
            rel_path = os.path.relpath(abs_path, repo_path).replace(os.sep, "/")
            out.append(rel_path)
    return out


def _is_excluded_dir(dirname: str) -> bool:
    if dirname in _EXCLUDED_DIRS or dirname.endswith(".egg-info"):
        return True
    return dirname.startswith(".") and dirname != ".github"


# --------------------------------------------------------------------------
# 3.1 — Manifests
# --------------------------------------------------------------------------


def _parse_requirements_txt(rel_path: str, content: str) -> List[Dependency]:
    deps: List[Dependency] = []
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith(("-e ", "-r ", "--")):
            continue
        match = re.match(r"^([A-Za-z0-9_.\-\[\]]+)\s*(==|>=|<=|~=|!=|>|<)?\s*([\w.\-]*)", line)
        if not match:
            continue
        name = match.group(1).split("[")[0].strip()
        version = match.group(3).strip() or None
        if name:
            deps.append(Dependency(name=name, version=version, manifest=rel_path))
    return deps


def _parse_pyproject_toml(rel_path: str, abs_path: str) -> Tuple[List[Dependency], List[EntryPoint]]:
    deps: List[Dependency] = []
    entry_points: List[EntryPoint] = []
    try:
        with open(abs_path, "rb") as f:
            data = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError):
        return deps, entry_points

    project = data.get("project", {})
    for raw in project.get("dependencies", []) or []:
        match = re.match(r"^([A-Za-z0-9_.\-]+)\s*(==|>=|<=|~=|!=|>|<)?\s*([\w.\-]*)", raw.strip())
        if match:
            name = match.group(1)
            version = match.group(3).strip() or None
            deps.append(Dependency(name=name, version=version, manifest=rel_path))

    for name, target in (project.get("scripts") or {}).items():
        entry_points.append(
            EntryPoint(kind="console_script", name=name, file=rel_path, line=0, detail=str(target))
        )
    return deps, entry_points


def _parse_setup_py(rel_path: str, content: str) -> Tuple[List[Dependency], List[EntryPoint]]:
    deps: List[Dependency] = []
    entry_points: List[EntryPoint] = []

    block_match = re.search(r"install_requires\s*=\s*\[(.*?)\]", content, re.DOTALL)
    if block_match:
        for raw in re.findall(r"""['"]([^'"]+)['"]""", block_match.group(1)):
            match = re.match(r"^([A-Za-z0-9_.\-]+)\s*(==|>=|<=|~=|!=|>|<)?\s*([\w.\-]*)", raw.strip())
            if match:
                name = match.group(1)
                version = match.group(3).strip() or None
                deps.append(Dependency(name=name, version=version, manifest=rel_path))

    scripts_match = re.search(r"console_scripts['\"]\s*:\s*\[(.*?)\]", content, re.DOTALL)
    if scripts_match:
        for raw in re.findall(r"""['"]([^'"]+)['"]""", scripts_match.group(1)):
            if "=" in raw:
                name, target = raw.split("=", 1)
                entry_points.append(
                    EntryPoint(
                        kind="console_script", name=name.strip(), file=rel_path, line=0,
                        detail=target.strip(),
                    )
                )
    return deps, entry_points


def _parse_package_json(rel_path: str, content: str) -> Tuple[List[Dependency], List[EntryPoint]]:
    deps: List[Dependency] = []
    entry_points: List[EntryPoint] = []
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return deps, entry_points

    for key in ("dependencies", "devDependencies"):
        for name, version in (data.get(key) or {}).items():
            deps.append(Dependency(name=name, version=str(version) or None, manifest=rel_path))

    for name, command in (data.get("scripts") or {}).items():
        entry_points.append(
            EntryPoint(kind="npm_script", name=name, file=rel_path, line=0, detail=str(command))
        )
    return deps, entry_points


def _parse_pom_xml(rel_path: str, content: str) -> List[Dependency]:
    deps: List[Dependency] = []
    for block in re.findall(r"<dependency>(.*?)</dependency>", content, re.DOTALL):
        group = re.search(r"<groupId>([^<]+)</groupId>", block)
        artifact = re.search(r"<artifactId>([^<]+)</artifactId>", block)
        version = re.search(r"<version>([^<]+)</version>", block)
        if artifact:
            name = f"{group.group(1)}:{artifact.group(1)}" if group else artifact.group(1)
            deps.append(
                Dependency(name=name, version=version.group(1) if version else None, manifest=rel_path)
            )
    return deps


def _parse_gradle(rel_path: str, content: str) -> List[Dependency]:
    deps: List[Dependency] = []
    for group, artifact, version in re.findall(
        r"""['"]([\w.\-]+):([\w.\-]+):([\w.\-]+)['"]""", content
    ):
        deps.append(Dependency(name=f"{group}:{artifact}", version=version, manifest=rel_path))
    return deps


def _parse_build_sbt(rel_path: str, content: str) -> List[Dependency]:
    deps: List[Dependency] = []
    # "org" %% "name" % "version" (or %%%, or single %). Cross-build operator
    # doubling (%%/%%%) doesn't change what we record — org:name at a version.
    pattern = re.compile(
        r"""['"]([\w.\-]+)['"]\s*%{1,3}\s*['"]([\w.\-]+)['"]\s*%\s*['"]([\w.\-]+)['"]"""
    )
    for org, name, version in pattern.findall(content):
        deps.append(Dependency(name=f"{org}:{name}", version=version, manifest=rel_path))
    return deps


def _parse_go_mod(rel_path: str, content: str) -> List[Dependency]:
    deps: List[Dependency] = []
    for name, version in re.findall(r"^\s*([\w.\-/]+)\s+(v[\d][\w.\-+]*)", content, re.MULTILINE):
        if name in ("go", "module"):
            continue
        deps.append(Dependency(name=name, version=version, manifest=rel_path))
    return deps


def _parse_cargo_toml(rel_path: str, abs_path: str) -> List[Dependency]:
    deps: List[Dependency] = []
    try:
        with open(abs_path, "rb") as f:
            data = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError):
        return deps
    for name, value in (data.get("dependencies") or {}).items():
        if isinstance(value, str):
            version = value
        elif isinstance(value, dict):
            version = value.get("version")
        else:
            version = None
        deps.append(Dependency(name=name, version=version, manifest=rel_path))
    return deps


def _parse_dockerfile(rel_path: str, content: str) -> Tuple[Optional[Dependency], List[EntryPoint]]:
    base_dep: Optional[Dependency] = None
    entry_points: List[EntryPoint] = []
    for i, line in enumerate(content.splitlines(), start=1):
        from_match = re.match(r"^\s*FROM\s+([^\s]+)", line, re.IGNORECASE)
        if from_match and base_dep is None:
            image = from_match.group(1)
            name, _, tag = image.partition(":")
            base_dep = Dependency(name=name, version=tag or None, manifest=rel_path)
            continue
        cmd_match = re.match(r"^\s*(CMD|ENTRYPOINT)\s+(.+)$", line, re.IGNORECASE)
        if cmd_match:
            entry_points.append(
                EntryPoint(
                    kind="docker_cmd", name=cmd_match.group(1).upper(), file=rel_path, line=i,
                    detail=cmd_match.group(2).strip(),
                )
            )
    return base_dep, entry_points


def _parse_docker_compose(rel_path: str, abs_path: str) -> Tuple[List[Dependency], List[EntryPoint]]:
    deps: List[Dependency] = []
    entry_points: List[EntryPoint] = []
    try:
        with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
            data = yaml.safe_load(f)
    except (OSError, yaml.YAMLError):
        return deps, entry_points
    if not isinstance(data, dict):
        return deps, entry_points

    for service_name, service in (data.get("services") or {}).items():
        if not isinstance(service, dict):
            continue
        image = service.get("image")
        if isinstance(image, str):
            name, _, tag = image.partition(":")
            deps.append(Dependency(name=name, version=tag or None, manifest=rel_path))
        entry_points.append(
            EntryPoint(
                kind="docker_cmd", name=service_name, file=rel_path, line=0,
                detail=f"docker compose service: {image}" if image else "docker compose service",
            )
        )
    return deps, entry_points


def _extract_manifests(
    repo_path: str, files: List[str]
) -> Tuple[List[Dependency], List[str], List[EntryPoint], Optional[bool], List[str]]:
    """Returns (dependencies, manifests_found, manifest_entry_points,
    has_dockerfile, ci_files). Dependencies are collected in the fixed order
    of spec section 3.1's table, then capped at _MAX_DEPENDENCIES."""
    deps: List[Dependency] = []
    manifests_found: List[str] = []
    entry_points: List[EntryPoint] = []
    has_dockerfile = False
    ci_files: List[str] = []

    def abs_of(rel: str) -> str:
        return os.path.join(repo_path, rel)

    requirements_files = sorted(
        f for f in files if os.path.basename(f).lower().startswith("requirements") and f.endswith(".txt")
    )
    for rel in requirements_files:
        content, _ = _read_capped(abs_of(rel), cap_chars=20_000)
        found = _parse_requirements_txt(rel, content)
        if found:
            deps.extend(found)
            manifests_found.append(rel)

    for rel in sorted(f for f in files if os.path.basename(f) == "pyproject.toml"):
        d, e = _parse_pyproject_toml(rel, abs_of(rel))
        if d or e:
            deps.extend(d)
            entry_points.extend(e)
            manifests_found.append(rel)

    for rel in sorted(f for f in files if os.path.basename(f) == "setup.py"):
        content, _ = _read_capped(abs_of(rel), cap_chars=20_000)
        d, e = _parse_setup_py(rel, content)
        if d or e:
            deps.extend(d)
            entry_points.extend(e)
            manifests_found.append(rel)

    for rel in sorted(f for f in files if os.path.basename(f) == "package.json"):
        content, _ = _read_capped(abs_of(rel), cap_chars=20_000)
        d, e = _parse_package_json(rel, content)
        if d or e:
            deps.extend(d)
            entry_points.extend(e)
            manifests_found.append(rel)

    for rel in sorted(f for f in files if os.path.basename(f) == "pom.xml"):
        content, _ = _read_capped(abs_of(rel), cap_chars=20_000)
        d = _parse_pom_xml(rel, content)
        if d:
            deps.extend(d)
            manifests_found.append(rel)

    for rel in sorted(f for f in files if os.path.basename(f) in ("build.gradle", "build.gradle.kts")):
        content, _ = _read_capped(abs_of(rel), cap_chars=20_000)
        d = _parse_gradle(rel, content)
        if d:
            deps.extend(d)
            manifests_found.append(rel)

    for rel in sorted(f for f in files if os.path.basename(f) == "build.sbt"):
        content, _ = _read_capped(abs_of(rel), cap_chars=20_000)
        d = _parse_build_sbt(rel, content)
        if d:
            deps.extend(d)
            manifests_found.append(rel)

    for rel in sorted(f for f in files if os.path.basename(f) == "go.mod"):
        content, _ = _read_capped(abs_of(rel), cap_chars=20_000)
        d = _parse_go_mod(rel, content)
        if d:
            deps.extend(d)
            manifests_found.append(rel)

    for rel in sorted(f for f in files if os.path.basename(f) == "Cargo.toml"):
        d = _parse_cargo_toml(rel, abs_of(rel))
        if d:
            deps.extend(d)
            manifests_found.append(rel)

    for rel in sorted(f for f in files if os.path.basename(f) == "Dockerfile"):
        has_dockerfile = True
        content, _ = _read_capped(abs_of(rel), cap_chars=20_000)
        base_dep, e = _parse_dockerfile(rel, content)
        if base_dep:
            deps.append(base_dep)
        entry_points.extend(e)
        manifests_found.append(rel)

    for rel in sorted(
        f for f in files
        if re.match(r"^(.*/)?docker-compose\.ya?ml$", f, re.IGNORECASE)
    ):
        d, e = _parse_docker_compose(rel, abs_of(rel))
        if d or e:
            deps.extend(d)
            entry_points.extend(e)
            manifests_found.append(rel)

    for rel in sorted(
        f for f in files
        if re.match(r"^\.github/workflows/.+\.ya?ml$", f, re.IGNORECASE)
    ):
        ci_files.append(rel)
        manifests_found.append(rel)

    # Dedup by (name, manifest), preserve first-seen order, cap.
    seen: set = set()
    unique_deps: List[Dependency] = []
    for dep in deps:
        key = (dep.name, dep.manifest)
        if key in seen:
            continue
        seen.add(key)
        unique_deps.append(dep)

    return unique_deps[:_MAX_DEPENDENCIES], manifests_found, entry_points, has_dockerfile, ci_files


# --------------------------------------------------------------------------
# 3.2 — Entry points (code-pattern detection, beyond manifests)
# --------------------------------------------------------------------------

# kind is a plain `str` field on EntryPoint (not a closed enum at runtime),
# so two patterns below use kinds beyond the six the spec calls out by name
# ("celery_task", "shell_script") rather than force a Celery task or a
# top-level shell script into one of the six that doesn't actually describe
# it. Every other pattern below uses exactly the kind the spec names.
_PY_PATTERNS: List[Tuple[re.Pattern, str, str]] = [
    (re.compile(r'if\s+__name__\s*==\s*[\'"]__main__[\'"]'), "main", "__main__ guard"),
    (re.compile(r'^\s*def\s+main\s*\('), "main", "main()"),
    (re.compile(r'@(?:\w+\.)?(?:app|router)\.(get|post|put|delete|patch)\('), "http_route", None),
    (re.compile(r'\bAPIRouter\s*\('), "http_route", "APIRouter instantiation"),
    (re.compile(r'^\s*urlpatterns\s*='), "http_route", "Django urlpatterns"),
    (re.compile(r'@(?:\w+\.)?task\b'), "celery_task", "Celery task"),
]
_ROUTE_PATH_RE = re.compile(r'''\(\s*['"]([^'"]+)['"]''')

_JVM_PATTERNS: List[Tuple[re.Pattern, str, str]] = [
    (re.compile(r'public\s+static\s+void\s+main\s*\('), "main", "public static void main"),
    (re.compile(r'@RestController\b'), "http_route", "@RestController"),
    (re.compile(r'@RequestMapping\b'), "http_route", "@RequestMapping"),
    (re.compile(r'@(Get|Post|Put|Delete|Patch)Mapping\('), "http_route", None),
]

_SCALA_PATTERNS: List[Tuple[re.Pattern, str, str]] = [
    (re.compile(r'\bextends\s+App\b'), "main", "extends App"),
    (re.compile(r'def\s+main\s*\(\s*args\s*:\s*Array\[String\]'), "main", "def main(args: Array[String])"),
    (re.compile(r'\bSparkSession\.builder\b'), "spark_submit", "SparkSession.builder"),
]

_SHELL_SPARK_RE = re.compile(r'\bspark-submit\b')


def _scan_code_entry_points(repo_path: str, files: List[str]) -> List[EntryPoint]:
    entry_points: List[EntryPoint] = []
    for rel_path in files:
        ext = os.path.splitext(rel_path)[1].lower()
        abs_path = os.path.join(repo_path, rel_path)
        try:
            if os.path.getsize(abs_path) > 500_000:
                continue
        except OSError:
            continue

        if ext == ".py":
            content, _ = _read_capped(abs_path, cap_chars=200_000)
            for i, line in enumerate(content.splitlines(), start=1):
                for pattern, kind, label in _PY_PATTERNS:
                    match = pattern.search(line)
                    if not match:
                        continue
                    detail = label
                    if kind == "http_route":
                        route_match = _ROUTE_PATH_RE.search(line)
                        detail = route_match.group(1) if route_match else None
                        name = f"{match.group(1) if match.groups() else 'route'}"
                    else:
                        name = label or kind
                    entry_points.append(
                        EntryPoint(kind=kind, name=name, file=rel_path, line=i, detail=detail)
                    )

        elif ext in (".java", ".kt"):
            content, _ = _read_capped(abs_path, cap_chars=200_000)
            for i, line in enumerate(content.splitlines(), start=1):
                for pattern, kind, label in _JVM_PATTERNS:
                    match = pattern.search(line)
                    if match:
                        entry_points.append(
                            EntryPoint(kind=kind, name=label or kind, file=rel_path, line=i, detail=label)
                        )

        elif ext == ".scala":
            content, _ = _read_capped(abs_path, cap_chars=200_000)
            for i, line in enumerate(content.splitlines(), start=1):
                for pattern, kind, label in _SCALA_PATTERNS:
                    if pattern.search(line):
                        entry_points.append(
                            EntryPoint(kind=kind, name=label, file=rel_path, line=i, detail=label)
                        )

        elif ext in (".sh", ".bash"):
            is_rooted = "/" not in rel_path or rel_path.startswith(("bin/", "scripts/"))
            if not is_rooted:
                continue
            content, _ = _read_capped(abs_path, cap_chars=200_000)
            entry_points.append(
                EntryPoint(kind="shell_script", name=os.path.basename(rel_path), file=rel_path, line=1, detail=None)
            )
            for i, line in enumerate(content.splitlines(), start=1):
                if _SHELL_SPARK_RE.search(line):
                    entry_points.append(
                        EntryPoint(kind="spark_submit", name="spark-submit", file=rel_path, line=i, detail=line.strip()[:200])
                    )

    return entry_points


# --------------------------------------------------------------------------
# 3.3 — Configuration surface
# --------------------------------------------------------------------------

_PY_ENV_PATTERNS = [
    re.compile(r'os\.environ\[\s*[\'"]([A-Za-z_][A-Za-z0-9_]*)[\'"]\s*\]'),
    re.compile(r'os\.environ\.get\(\s*[\'"]([A-Za-z_][A-Za-z0-9_]*)[\'"](?:\s*,\s*([^)]+))?\)'),
    re.compile(r'os\.getenv\(\s*[\'"]([A-Za-z_][A-Za-z0-9_]*)[\'"](?:\s*,\s*([^)]+))?\)'),
]
_JS_ENV_PATTERNS = [
    re.compile(r'process\.env\.([A-Za-z_][A-Za-z0-9_]*)'),
    re.compile(r'process\.env\[\s*[\'"]([A-Za-z_][A-Za-z0-9_]*)[\'"]\s*\]'),
]
_JAVA_ENV_PATTERNS = [
    re.compile(r'System\.getenv\(\s*[\'"]([A-Za-z_][A-Za-z0-9_]*)[\'"]\s*\)'),
]


def _scan_env_var_usage(repo_path: str, files: List[str]) -> List[ConfigItem]:
    items: List[ConfigItem] = []
    for rel_path in files:
        ext = os.path.splitext(rel_path)[1].lower()
        abs_path = os.path.join(repo_path, rel_path)
        try:
            if os.path.getsize(abs_path) > 500_000:
                continue
        except OSError:
            continue

        if ext == ".py":
            patterns = [(p, i == 0) for i, p in enumerate(_PY_ENV_PATTERNS)]
        elif ext in (".js", ".jsx", ".ts", ".tsx"):
            patterns = [(p, True) for p in _JS_ENV_PATTERNS]
        elif ext in (".java", ".kt"):
            patterns = [(p, True) for p in _JAVA_ENV_PATTERNS]
        else:
            continue

        content, _ = _read_capped(abs_path, cap_chars=200_000)
        for pattern, no_default_group in patterns:
            for match in pattern.finditer(content):
                name = match.group(1)
                default = None
                if not no_default_group and match.groups() and len(match.groups()) > 1:
                    raw_default = match.group(2)
                    default = raw_default.strip() if raw_default else None
                items.append(
                    ConfigItem(name=name, source=rel_path, default=default, required=default is None)
                )
    return items


class _BaseSettingsVisitor(ast.NodeVisitor):
    """Finds `class X(BaseSettings): ...` and its annotated fields — pydantic
    v1 (`pydantic.BaseSettings`) and v2 (`pydantic_settings.BaseSettings`)
    both subclass under a base literally named BaseSettings, so a name match
    on the base (not an import-resolved type check) is enough here."""

    def __init__(self, rel_path: str) -> None:
        self.rel_path = rel_path
        self.items: List[ConfigItem] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        base_names = []
        for base in node.bases:
            if isinstance(base, ast.Name):
                base_names.append(base.id)
            elif isinstance(base, ast.Attribute):
                base_names.append(base.attr)
        if "BaseSettings" in base_names:
            for stmt in node.body:
                if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                    default = None
                    if stmt.value is not None:
                        try:
                            default = ast.unparse(stmt.value)
                        except Exception:
                            default = None
                    self.items.append(
                        ConfigItem(
                            name=stmt.target.id, source=self.rel_path,
                            default=default, required=default is None,
                        )
                    )
        self.generic_visit(node)


def _scan_pydantic_settings(repo_path: str, files: List[str]) -> List[ConfigItem]:
    items: List[ConfigItem] = []
    for rel_path in files:
        if not rel_path.endswith(".py"):
            continue
        abs_path = os.path.join(repo_path, rel_path)
        content, _ = _read_capped(abs_path, cap_chars=200_000)
        if "BaseSettings" not in content:
            continue
        try:
            tree = ast.parse(content)
        except SyntaxError:
            continue
        visitor = _BaseSettingsVisitor(rel_path)
        visitor.visit(tree)
        items.extend(visitor.items)
    return items


def _extract_config_items(repo_path: str, files: List[str]) -> List[ConfigItem]:
    all_items = _scan_env_var_usage(repo_path, files) + _scan_pydantic_settings(repo_path, files)
    seen: Dict[str, ConfigItem] = {}
    for item in all_items:
        seen.setdefault(item.name, item)
    return sorted(seen.values(), key=lambda c: c.name)


# --------------------------------------------------------------------------
# 3.4 — Module graph weights, hub/leaf ranking, cycle detection
# --------------------------------------------------------------------------


def _module_edges_from_components(
    modules: List[ModuleGroup], components: Dict[str, Node]
) -> List[ModuleEdge]:
    """Aggregate depends_on edges to module level, reusing
    module_descriptor._module_edge_weights — the exact traversal already
    used for the map step's "Depends on" section and the deterministic
    architecture diagram (see module_descriptor.py, overview_mapreduce.py).
    Imported lazily to avoid a hard import-time dependency from repo_facts
    on module_descriptor (they're siblings, not layered)."""
    from codewiki.src.be import module_descriptor as _module_descriptor

    file_to_module = {f: g.name for g in modules for f in g.files}
    edges: List[ModuleEdge] = []
    for group in modules:
        weights = _module_descriptor._module_edge_weights(
            group.name, group.files, components, file_to_module
        )
        for target, weight in sorted(weights.items()):
            edges.append(ModuleEdge(source=group.name, target=target, weight=weight))
    return edges


def _rank_hub_and_leaf_modules(
    modules: List[ModuleGroup], edges: List[ModuleEdge]
) -> Tuple[List[str], List[str]]:
    """Hub modules: highest in-degree (most depended upon) — "where should I
    start reading". Leaf modules: zero out-degree (depend on nothing else in
    the repository) — the standard bottom of a dependency DAG."""
    in_degree: Dict[str, int] = {m.name: 0 for m in modules}
    out_degree: Dict[str, int] = {m.name: 0 for m in modules}
    for edge in edges:
        out_degree[edge.source] = out_degree.get(edge.source, 0) + edge.weight
        in_degree[edge.target] = in_degree.get(edge.target, 0) + edge.weight

    hub_modules = [
        name for name, _ in sorted(in_degree.items(), key=lambda kv: (-kv[1], kv[0])) if in_degree[name] > 0
    ]
    leaf_modules = sorted(name for name, count in out_degree.items() if count == 0)
    return hub_modules, leaf_modules


def _detect_cycles(modules: List[ModuleGroup], edges: List[ModuleEdge]) -> List[List[str]]:
    """Strongly connected components of size > 1 in the module dependency
    graph, via Tarjan's algorithm — the standard, tractable definition of
    "cycle" at module granularity (enumerating every simple cycle can be
    combinatorially explosive; SCCs are not). Each returned group is sorted
    alphabetically for determinism, not traversal order."""
    graph: Dict[str, List[str]] = {m.name: [] for m in modules}
    for edge in edges:
        if edge.source in graph:
            graph[edge.source].append(edge.target)

    index_counter = [0]
    stack: List[str] = []
    lowlink: Dict[str, int] = {}
    index: Dict[str, int] = {}
    on_stack: Dict[str, bool] = {}
    sccs: List[List[str]] = []

    def strongconnect(node: str) -> None:
        index[node] = index_counter[0]
        lowlink[node] = index_counter[0]
        index_counter[0] += 1
        stack.append(node)
        on_stack[node] = True

        for neighbor in graph.get(node, []):
            if neighbor not in index:
                strongconnect(neighbor)
                lowlink[node] = min(lowlink[node], lowlink[neighbor])
            elif on_stack.get(neighbor):
                lowlink[node] = min(lowlink[node], index[neighbor])

        if lowlink[node] == index[node]:
            component: List[str] = []
            while True:
                w = stack.pop()
                on_stack[w] = False
                component.append(w)
                if w == node:
                    break
            if len(component) > 1:
                sccs.append(sorted(component))

    for name in graph:
        if name not in index:
            strongconnect(name)

    return sorted(sccs, key=lambda c: c[0])


# --------------------------------------------------------------------------
# README / other docs
# --------------------------------------------------------------------------


def _find_readme(repo_path: str, files: List[str]) -> Optional[str]:
    candidates = sorted(f for f in files if "/" not in f and os.path.basename(f).lower().startswith("readme."))
    if not candidates:
        return None
    abs_path = os.path.join(repo_path, candidates[0])
    content, truncated = _read_capped(abs_path, cap_chars=_README_CHAR_CAP)
    if truncated:
        content += "\n... (truncated)"
    return content


def _find_other_docs(repo_path: str, files: List[str]) -> Dict[str, str]:
    docs: Dict[str, str] = {}
    for rel_path in sorted(f for f in files if "/" not in f):
        if os.path.basename(rel_path).lower() not in _OTHER_DOC_NAMES:
            continue
        content, truncated = _read_capped(os.path.join(repo_path, rel_path), cap_chars=_OTHER_DOC_CHAR_CAP)
        if truncated:
            content += "\n... (truncated)"
        docs[rel_path] = content
    return docs


# --------------------------------------------------------------------------
# LOC / language stats, directory tree, tests
# --------------------------------------------------------------------------


def _count_lines(abs_path: str) -> int:
    try:
        with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
            return sum(1 for _ in f)
    except OSError:
        return 0


def _language_stats(repo_path: str, files: List[str]) -> Tuple[List[LanguageStat], int, int]:
    counts: Dict[str, int] = {}
    lines: Dict[str, int] = {}
    total_lines = 0
    for rel_path in files:
        ext = os.path.splitext(rel_path)[1].lower()
        language = _LANGUAGE_BY_EXT.get(ext)
        if language is None:
            continue
        n_lines = _count_lines(os.path.join(repo_path, rel_path))
        counts[language] = counts.get(language, 0) + 1
        lines[language] = lines.get(language, 0) + n_lines
        total_lines += n_lines

    stats = [
        LanguageStat(language=lang, files=counts[lang], lines=lines[lang])
        for lang in sorted(counts, key=lambda l: (-lines[l], l))
    ]
    return stats, len(files), total_lines


def _render_directory_tree(repo_path: str, depth: int = _DIRECTORY_TREE_DEPTH) -> str:
    lines: List[str] = []

    def walk(current: str, prefix: str, level: int) -> None:
        if level > depth:
            return
        try:
            entries = sorted(os.listdir(current))
        except OSError:
            return
        visible = [e for e in entries if not (e.startswith(".") and e != ".github") and e not in _EXCLUDED_DIRS]
        for i, entry in enumerate(visible):
            full = os.path.join(current, entry)
            connector = "└── " if i == len(visible) - 1 else "├── "
            is_dir = os.path.isdir(full)
            lines.append(f"{prefix}{connector}{entry}{'/' if is_dir else ''}")
            if is_dir and level < depth:
                extension = "    " if i == len(visible) - 1 else "│   "
                walk(full, prefix + extension, level + 1)

    walk(repo_path, "", 1)
    return "\n".join(lines)


def _count_tests_and_framework(repo_path: str, files: List[str]) -> Tuple[int, Optional[str]]:
    test_files = [f for f in files if _TEST_FILE_RE.search(f)]

    framework: Optional[str] = None
    manifest_names = {"requirements.txt", "requirements-dev.txt", "package.json", "pyproject.toml"}
    for rel_path in files:
        if os.path.basename(rel_path) not in manifest_names:
            continue
        content, _ = _read_capped(os.path.join(repo_path, rel_path), cap_chars=20_000)
        lowered = content.lower()
        for needle, label in _TEST_FRAMEWORK_MANIFEST_HINTS:
            if needle in lowered:
                framework = label
                break
        if framework:
            break

    if framework is None and any(f.endswith("_test.go") for f in files):
        framework = "go test"

    return len(test_files), framework


# --------------------------------------------------------------------------
# Entry point: extract_repo_facts
# --------------------------------------------------------------------------


def extract_repo_facts(
    repo_path: Path | str,
    modules: List[ModuleGroup],
    components: Optional[Dict[str, Node]] = None,
    commit_sha: Optional[str] = None,
) -> RepoFacts:
    """Extract every deterministic fact about a repository.

    `components` (the dependency-graph nodes already built by
    `DependencyGraphBuilder.build_dependency_graph()`) is required to
    compute module_edges/hub_modules/leaf_modules/cycles — those need the
    resolved import graph, which `modules` (directory groupings only) does
    not itself carry. When `components` is omitted, those four fields are
    empty rather than guessed. See module docstring for the debug CLI that
    builds both from a bare repository path.
    """
    repo_path = str(repo_path)
    name = os.path.basename(os.path.normpath(repo_path)) or repo_path
    files = _walk_repo_files(repo_path)

    dependencies, manifests_found, manifest_entry_points, has_dockerfile, ci_files = _extract_manifests(
        repo_path, files
    )
    code_entry_points = _scan_code_entry_points(repo_path, files)
    entry_points = manifest_entry_points + code_entry_points

    config_items = _extract_config_items(repo_path, files)

    if components is not None:
        module_edges = _module_edges_from_components(modules, components)
        hub_modules, leaf_modules = _rank_hub_and_leaf_modules(modules, module_edges)
        cycles = _detect_cycles(modules, module_edges)
    else:
        module_edges, hub_modules, leaf_modules, cycles = [], [], [], []

    readme_text = _find_readme(repo_path, files)
    other_docs = _find_other_docs(repo_path, files)
    languages, total_files, total_lines = _language_stats(repo_path, files)
    directory_tree = _render_directory_tree(repo_path)
    test_files, test_framework = _count_tests_and_framework(repo_path, files)

    return RepoFacts(
        name=name,
        commit_sha=commit_sha,
        total_files=total_files,
        total_lines=total_lines,
        languages=languages,
        directory_tree=directory_tree,
        dependencies=dependencies,
        manifests_found=manifests_found,
        entry_points=entry_points,
        config_items=config_items,
        module_edges=module_edges,
        hub_modules=hub_modules,
        leaf_modules=leaf_modules,
        cycles=cycles,
        readme_text=readme_text,
        other_docs=other_docs,
        test_files=test_files,
        test_framework=test_framework,
        has_dockerfile=has_dockerfile,
        has_ci=bool(ci_files),
        ci_files=sorted(ci_files),
    )


# --------------------------------------------------------------------------
# Debug CLI
# --------------------------------------------------------------------------


def _analyze_repo_path(repo_path: str) -> Tuple[List[ModuleGroup], Dict[str, Node]]:
    """Build (modules, components) for a bare repository path — what the CLI
    has, since it isn't handed an in-flight Config/graph_builder the way
    documentation_generator.py's pipeline is."""
    from codewiki.src.be.dependency_analyzer.dependency_graphs_builder import DependencyGraphBuilder
    from codewiki.src.be.module_grouper import group_modules
    from codewiki.src.config import Config

    config = Config(
        repo_path=repo_path,
        output_dir=".",
        dependency_graph_dir=".",
        docs_dir=".",
        max_depth=2,
        llm_base_url="",
        llm_api_key="",
        main_model="",
        cluster_model="",
    )
    components, _leaf_nodes = DependencyGraphBuilder(config).build_dependency_graph()
    files = sorted({n.relative_path for n in components.values()})
    modules = group_modules(files)
    return modules, components


def _facts_to_json_dict(facts: RepoFacts) -> dict:
    return asdict(facts)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract a deterministic Repository Fact Sheet (no LLM calls)."
    )
    parser.add_argument("--repo", required=True, help="Path to the repository to analyze.")
    parser.add_argument("--out", required=True, help="Path to write facts.json to.")
    args = parser.parse_args()

    modules, components = _analyze_repo_path(args.repo)
    facts = extract_repo_facts(args.repo, modules, components)

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(_facts_to_json_dict(facts), f, indent=2, sort_keys=False)

    print(f"Wrote {args.out}: {facts.total_files} files, {facts.total_lines} lines, "
          f"{len(facts.dependencies)} dependencies, {len(facts.entry_points)} entry points, "
          f"{len(facts.config_items)} config items, {len(facts.module_edges)} module edges, "
          f"{len(facts.cycles)} cycle(s).")


if __name__ == "__main__":
    main()
