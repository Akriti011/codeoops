"""Authored-text harvesting for map-reduce overview generation.

Pure, deterministic, no LLM calls: pulls the repository authors' own words
for a module, in priority order, and stops at the first hit. This is meant
to seed module_descriptor.py's "authored text" section with something a
human actually wrote, rather than only architecture facts a machine derived.

Priority order (first non-empty hit wins):
  1. A README in the module's own directory — first paragraph
  2. A Python module docstring (ast-parsed; not attempted for other
     languages — CodeWiki's dependency graph has no per-file "module" node
     to read a docstring from for those, and this stays a deterministic,
     no-LLM harvester rather than growing a docstring parser per language)
  3. The module's highest-in-degree class's docstring (from the dependency
     graph's own Node.docstring — already extracted by CodeWiki's AST pass)
  4. A manifest "description" field (the module's own directory first,
     falling back to the repository root)
"""

from __future__ import annotations

import ast
import json
import logging
import os
import re
from typing import Dict, List, Optional

from codewiki.src.be.dependency_analyzer.models.core import Node
from codewiki.src.be.utils import count_tokens

logger = logging.getLogger(__name__)

_HARVEST_TOKEN_CAP = int(os.getenv("DOC_HARVEST_TOKEN_BUDGET", "120"))

_MANIFEST_NAMES = {"package.json", "pyproject.toml"}


def _cap_tokens(text: str, cap: int = _HARVEST_TOKEN_CAP) -> str:
    text = text.strip()
    if count_tokens(text) <= cap:
        return text
    # Trim by words until under budget, good enough for a ~120-token cap on
    # prose. Then prefer ending at the last full sentence within that cut —
    # a mid-sentence cutoff reads as broken, a dropped trailing half-sentence
    # doesn't.
    words = text.split()
    while words and count_tokens(" ".join(words)) > cap:
        words.pop()
    truncated = " ".join(words).strip()
    last_sentence_end = max(truncated.rfind(". "), truncated.rfind("! "), truncated.rfind("? "))
    if last_sentence_end > len(truncated) * 0.4:
        truncated = truncated[: last_sentence_end + 1]
    return truncated.strip()


def _first_paragraph(text: str) -> str:
    """First non-empty block of a README, with markdown heading/badge noise
    stripped — the "first paragraph", not the first line."""
    lines = text.splitlines()
    paragraph: List[str] = []
    started = False
    for line in lines:
        stripped = line.strip()
        if not stripped:
            if started:
                break
            continue
        if stripped.startswith("#") or stripped.startswith("!["):
            continue
        paragraph.append(stripped)
        started = True
    return " ".join(paragraph).strip()


def _harvest_readme(repo_path: str, module_files: List[str]) -> Optional[str]:
    module_dirs = {os.path.dirname(f) for f in module_files}
    for module_dir in sorted(module_dirs):
        abs_dir = os.path.join(repo_path, module_dir) if module_dir else repo_path
        try:
            entries = os.listdir(abs_dir)
        except OSError:
            continue
        for entry in entries:
            if entry.lower().startswith("readme."):
                try:
                    with open(os.path.join(abs_dir, entry), "r", encoding="utf-8", errors="replace") as f:
                        content = f.read(8000)
                except OSError:
                    continue
                paragraph = _first_paragraph(content)
                if paragraph:
                    return paragraph
    return None


def _harvest_module_docstring(repo_path: str, module_files: List[str]) -> Optional[str]:
    for rel_path in module_files:
        if not rel_path.endswith(".py"):
            continue
        abs_path = os.path.join(repo_path, rel_path)
        try:
            with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
                source = f.read()
            tree = ast.parse(source)
            docstring = ast.get_docstring(tree)
        except (OSError, SyntaxError, ValueError):
            continue
        if docstring and docstring.strip():
            return docstring.strip()
    return None


def _harvest_top_class_docstring(
    module_files: List[str], components: Dict[str, Node], in_degree: Dict[str, int]
) -> Optional[str]:
    file_set = set(module_files)
    candidates = [
        node
        for node in components.values()
        if node.relative_path in file_set
        and node.component_type == "class"
        and node.has_docstring
        and node.docstring
        and node.docstring.strip()
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda n: in_degree.get(n.id, 0), reverse=True)
    return candidates[0].docstring.strip()


def _manifest_description(abs_dir: str) -> Optional[str]:
    for name in _MANIFEST_NAMES:
        path = os.path.join(abs_dir, name)
        if not os.path.isfile(path):
            continue
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
        except OSError:
            continue
        if name == "package.json":
            try:
                data = json.loads(content)
            except json.JSONDecodeError:
                continue
            description = data.get("description")
            if isinstance(description, str) and description.strip():
                return description.strip()
        elif name == "pyproject.toml":
            match = re.search(r'^\s*description\s*=\s*["\']([^"\']+)["\']', content, re.MULTILINE)
            if match:
                return match.group(1).strip()
    return None


def _harvest_manifest_description(repo_path: str, module_files: List[str]) -> Optional[str]:
    module_dirs = sorted({os.path.dirname(f) for f in module_files})
    for module_dir in module_dirs:
        abs_dir = os.path.join(repo_path, module_dir) if module_dir else repo_path
        description = _manifest_description(abs_dir)
        if description:
            return description
    return _manifest_description(repo_path)


def harvest_authored_text(
    repo_path: str,
    module_files: List[str],
    components: Dict[str, Node],
    in_degree: Dict[str, int],
) -> str:
    """Return the first non-empty authored-text hit for this module, capped
    to ~120 tokens. Returns "" if none of the four sources have anything —
    never fabricated filler."""
    for harvester in (
        lambda: _harvest_readme(repo_path, module_files),
        lambda: _harvest_module_docstring(repo_path, module_files),
        lambda: _harvest_top_class_docstring(module_files, components, in_degree),
        lambda: _harvest_manifest_description(repo_path, module_files),
    ):
        result = harvester()
        if result:
            return _cap_tokens(result)
    return ""
