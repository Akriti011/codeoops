"""Executable architecture rules.

CodeOops orchestrates a documentation engine; it must never become one. These
tests fail the build if that line is crossed, so the rule survives refactors and
future contributors.

CodeWiki is now wired (app/providers/codewiki_provider.py), so the boundary
these tests guard has shifted from "no implementation exists" to "exactly one
implementation exists, it talks HTTP only, and CodeWiki's own protocol
details (its endpoints, form fields, file names) never leak outside
app/services/codewiki/."
"""

from __future__ import annotations

import re
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1] / "app"

FORBIDDEN_IMPORTS = (
    "openai",
    "anthropic",
    "ollama",
    "litellm",
    "langchain",
    "google.generativeai",
    "transformers",
)

FORBIDDEN_SYMBOLS = (
    "generate_overview",
    "build_documentation",
    "summarize_repository",
    "summarise_repository",
    "create_architecture_document",
    "generate_markdown",
    "render_documentation",
    "SAMPLE_DOCUMENTATION",
    "PLACEHOLDER_DOCS",
)


def _python_sources() -> list[Path]:
    return sorted(APP_ROOT.rglob("*.py"))


def test_backend_has_python_sources() -> None:
    assert _python_sources(), "no backend sources found; the guard would be vacuous"


def test_no_llm_client_is_imported_anywhere_in_the_backend() -> None:
    offenders: list[str] = []
    for path in _python_sources():
        source = path.read_text(encoding="utf-8")
        for module in FORBIDDEN_IMPORTS:
            pattern = rf"^\s*(?:import\s+{re.escape(module)}|from\s+{re.escape(module)}[\s.])"
            if re.search(pattern, source, flags=re.MULTILINE):
                offenders.append(f"{path.relative_to(APP_ROOT)} imports {module}")
    assert not offenders, offenders


def test_no_documentation_generation_symbols_exist() -> None:
    offenders: list[str] = []
    for path in _python_sources():
        source = path.read_text(encoding="utf-8")
        for symbol in FORBIDDEN_SYMBOLS:
            if re.search(rf"(?:def|class)\s+{re.escape(symbol)}\b", source):
                offenders.append(f"{path.relative_to(APP_ROOT)} defines {symbol}")
    assert not offenders, offenders


def test_no_markdown_documents_are_embedded_in_the_backend() -> None:
    """A heuristic against hardcoded 'sample documentation' creeping in."""
    offenders: list[str] = []
    for path in _python_sources():
        source = path.read_text(encoding="utf-8")
        if re.search(r"^#{1,3}\s+\w+", source, flags=re.MULTILINE) and "```" in source:
            offenders.append(str(path.relative_to(APP_ROOT)))
    assert not offenders, offenders


def test_exactly_one_documentation_provider_is_implemented() -> None:
    """CodeWikiProvider is the sanctioned adapter. No second engine may appear."""
    provider_module = APP_ROOT / "providers" / "documentation_provider.py"
    assert "class DocumentationProvider(ABC)" in provider_module.read_text(encoding="utf-8")

    subclasses: set[str] = set()
    for path in _python_sources():
        source = path.read_text(encoding="utf-8")
        subclasses.update(re.findall(r"^class\s+(\w+)\(DocumentationProvider\)", source, re.M))

    assert subclasses == {"CodeWikiProvider"}, subclasses


# Literal CodeWiki wire-protocol strings that only make sense if you are
# talking to CodeWiki's actual HTTP surface or parsing its actual
# metadata.json — as opposed to "overview.md"/"metadata.json", which
# CodeOops's own artifact store is free to reuse as its own filenames. These
# may only appear inside app/services/codewiki/ — everywhere else must go
# through that package's functions rather than re-encoding the protocol.
_CODEWIKI_PROTOCOL_MARKERS = (
    "/api/job/",
    "static-docs",
    "generation_info",
)


def test_codewiki_protocol_details_are_confined_to_the_codewiki_package() -> None:
    offenders: list[str] = []
    for path in _python_sources():
        relative = path.relative_to(APP_ROOT).as_posix()
        if relative.startswith("services/codewiki/"):
            continue
        source = path.read_text(encoding="utf-8")
        for marker in _CODEWIKI_PROTOCOL_MARKERS:
            if marker in source:
                offenders.append(f"{relative} references {marker!r}")
    assert not offenders, offenders
