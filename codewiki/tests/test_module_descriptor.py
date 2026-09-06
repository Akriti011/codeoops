"""Unit tests for module_descriptor.build_module_descriptor's signature-based
evidence digest (OVERVIEW_QUALITY_SPEC.md section 4.1).

No LLM calls anywhere in this file. The public/private and ranking tests
use small, hand-built Node objects (no real files needed on disk — see
_make_function_node) so cap/ranking behavior is exact-assertable without a
60-symbol fixture repository; the inclusion/exclusion test runs against the
real repo_facts_fixture/ used by test_repo_facts.py, exercising the real
AST extraction path end to end.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from codewiki.src.be import module_descriptor
from codewiki.src.be.dependency_analyzer.models.core import Node
from codewiki.src.be.repo_facts import _analyze_repo_path

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "repo_facts_fixture")


def _make_function_node(name: str, relative_path: str, docstring: str = "") -> Node:
    return Node(
        id=f"{relative_path}::{name}",
        name=name,
        component_type="function",
        file_path=relative_path,
        relative_path=relative_path,
        depends_on=set(),
        source_code=f"def {name}():\n    pass\n",
        start_line=1,
        end_line=2,
        has_docstring=bool(docstring),
        docstring=docstring,
        parameters=[],
        node_type="function",
        display_name=f"function {name}",
        component_id=f"{relative_path}::{name}",
        language="python",
        qualified_name=name,
    )


def test_digest_includes_public_symbols_and_excludes_private():
    """Greeter, Greeter.greet and main are public and must appear;
    Greeter._internal_helper is private (leading underscore) and must not
    appear anywhere in the digest — not in PUBLIC SURFACE, and not picked
    as the "most-referenced function body" fallback either."""
    modules, components = _analyze_repo_path(FIXTURE)
    assert len(modules) == 1  # see test_repo_facts.py — one module, all files under app/
    module = modules[0]
    file_to_module = {f: module.name for f in module.files}

    descriptor = module_descriptor.build_module_descriptor(
        module_name=module.name,
        module_files=module.files,
        components=components,
        in_degree={},
        file_to_module=file_to_module,
        repo_path=FIXTURE,
    )

    assert "class Greeter" in descriptor
    # Verbatim signature slicing (OVERVIEW_QUALITY_SPEC.md Part 2): the real
    # type hint and return annotation, not just the bare parameter name
    # Node.parameters alone would give.
    assert "def Greeter.greet(self, name: str) -> str" in descriptor
    assert "def main()" in descriptor
    assert "_internal_helper" not in descriptor


def test_symbol_cap_respected():
    """80 equally-ranked synthetic functions in one module; only
    MAX_SYMBOLS_PER_MODULE (60) may appear, and — since cross-module refs
    and file size tie at zero for all of them — the tie-break is
    alphabetical, so it must be exactly func_000..func_059."""
    rel_path = "synthetic/module.py"
    components = {}
    for i in range(80):
        node = _make_function_node(f"func_{i:03d}", rel_path)
        components[node.id] = node

    descriptor = module_descriptor.build_module_descriptor(
        module_name="synthetic",
        module_files=[rel_path],
        components=components,
        in_degree={},
        file_to_module={rel_path: "synthetic"},
        repo_path="/nonexistent",
        budget=1_000_000,  # large enough that the symbol cap binds, not the token budget
    )

    # Isolate the PUBLIC SURFACE listing itself — with a budget this large,
    # the most-referenced function's body is also appended per the "only if
    # budget remains" rule, and it would otherwise duplicate one name here.
    surface_section = descriptor.split("MOST-REFERENCED FUNCTION BODY")[0]
    shown = re.findall(r"def (func_\d{3})\(\)", surface_section)
    assert len(shown) == module_descriptor.MAX_SYMBOLS_PER_MODULE == 60
    assert shown == [f"func_{i:03d}" for i in range(60)]
    assert "(top 60 of 80 by cross-module references)" in descriptor


def test_ranking_prefers_cross_module_referenced_symbols():
    """`popular`, referenced from another module, must rank ahead of
    `obscure`, which nothing references — spec 4.1's primary ranking
    signal."""
    file_a = "pkg_a/mod.py"
    file_b = "pkg_b/caller.py"
    popular = _make_function_node("popular", file_a)
    obscure = _make_function_node("obscure", file_a)
    caller = _make_function_node("caller", file_b).model_copy(update={"depends_on": {popular.id}})
    components = {n.id: n for n in (popular, obscure, caller)}

    descriptor = module_descriptor.build_module_descriptor(
        module_name="pkg_a",
        module_files=[file_a],
        components=components,
        in_degree={},
        file_to_module={file_a: "pkg_a", file_b: "pkg_b"},
        repo_path="/nonexistent",
        budget=100_000,
    )

    assert descriptor.index("def popular()") < descriptor.index("def obscure()")


def test_imports_from_and_imported_by_present_with_weights():
    modules, components = _analyze_repo_path(FIXTURE)
    module = modules[0]
    file_to_module = {f: module.name for f in module.files}

    # A second, synthetic module that depends on this one, so IMPORTED BY
    # has something real to report (the fixture repo alone is one module —
    # see test_repo_facts.py — so it never has incoming edges on its own).
    # Points its depends_on directly at the fixture's `main` component id.
    external_file = "external/consumer.py"
    main_id = next(n.id for n in components.values() if n.name == "main")
    consumer = _make_function_node("consumer", external_file).model_copy(
        update={"depends_on": {main_id}}
    )
    all_components = dict(components)
    all_components[consumer.id] = consumer
    file_to_module[external_file] = "external"

    descriptor = module_descriptor.build_module_descriptor(
        module_name=module.name,
        module_files=module.files,
        components=all_components,
        in_degree={},
        file_to_module=file_to_module,
        repo_path=FIXTURE,
    )

    assert "IMPORTED BY: external (1)" in descriptor


# ---------------------------------------------------------------------
# Part 2 — verbatim signature slicing
# ---------------------------------------------------------------------


def test_slice_signature_captures_types_defaults_and_decorator(tmp_path):
    source = (
        "class Ignore:\n"
        "    pass\n"
        "\n"
        '@app.get("/jobs/{id}")\n'
        "def submit(self, repo_url: str, branch: str | None = None) -> RunHandle:\n"
        "    return RunHandle()\n"
    )
    path = tmp_path / "mod.py"
    path.write_text(source)

    result = module_descriptor.slice_signature(path, start_line=5, language="python")

    assert result == (
        '@app.get("/jobs/{id}") def submit(self, repo_url: str, '
        "branch: str | None = None) -> RunHandle"
    )


def test_slice_signature_class_with_bases():
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "settings.py"
        path.write_text("class Settings(BaseSettings):\n    debug: bool = False\n")
        result = module_descriptor.slice_signature(path, start_line=1, language="python")
        assert result == "class Settings(BaseSettings)"


def test_slice_signature_falls_back_beyond_line_cap():
    """A signature spanning more than 3 lines never finds its terminator
    inside the window — must return None (degrade), not raise or guess."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "mod.py"
        path.write_text(
            "def build_module_descriptor(\n"
            "    module_name: str,\n"
            "    module_files: list,\n"
            "    components: dict,\n"
            "    repo_path: str,\n"
            ") -> str:\n"
            "    pass\n"
        )
        result = module_descriptor.slice_signature(path, start_line=1, language="python")
        assert result is None


def test_slice_signature_missing_file_returns_none():
    assert module_descriptor.slice_signature(Path("/no/such/file.py"), 1, "python") is None


def test_language_falls_back_to_file_extension_when_node_language_is_none():
    """Node.language came back None for every node in a hand-checked real
    fixture (see module_descriptor.py's _effective_language) — simulate
    that gap explicitly here (_make_function_node sets it, matching how a
    real analyzer constructs a Node) and confirm the fallback still infers
    Python from the file extension rather than silently disabling
    slicing."""
    node = _make_function_node("foo", "pkg/mod.py").model_copy(update={"language": None})
    assert node.language is None
    assert module_descriptor._effective_language(node) == "python"


# ---------------------------------------------------------------------
# Part 1.2 — CONSTANTS
# ---------------------------------------------------------------------


def test_constants_present_and_secrets_redacted(tmp_path):
    rel_path = "pkg/settings.py"
    (tmp_path / "pkg").mkdir()
    (tmp_path / rel_path).write_text(
        'ARTIFACT_NAMES = ("overview.md",)\n'
        'API_SECRET_KEY = "sk-super-secret-value"\n'
        "small_case_not_a_constant = 1\n"
    )
    node = _make_function_node("foo", rel_path)
    components = {node.id: node}

    descriptor = module_descriptor.build_module_descriptor(
        module_name="pkg",
        module_files=[rel_path],
        components=components,
        in_degree={},
        file_to_module={rel_path: "pkg"},
        repo_path=str(tmp_path),
    )

    assert 'ARTIFACT_NAMES = ("overview.md",)' in descriptor
    assert "API_SECRET_KEY = <redacted>" in descriptor
    assert "sk-super-secret-value" not in descriptor
    assert "small_case_not_a_constant" not in descriptor


# ---------------------------------------------------------------------
# Part 1.4 — ENTRY POINTS now sourced from repo_facts's real detector
# ---------------------------------------------------------------------


def test_entry_points_use_real_detector_not_filename_allowlist(tmp_path):
    """A file that is NOT in the old filename allowlist (main.py,
    __main__.py, manage.py, app.py, ...) but does contain a real detected
    pattern must still show up — proving this reads from
    repo_facts._scan_code_entry_points, not the old evidence_extractor
    filename set."""
    rel_path = "pkg/handlers.py"
    (tmp_path / "pkg").mkdir()
    (tmp_path / rel_path).write_text(
        '@app.get("/health")\n'
        "def health():\n"
        "    return 'ok'\n"
    )
    node = _make_function_node("health", rel_path)
    components = {node.id: node}

    descriptor = module_descriptor.build_module_descriptor(
        module_name="pkg",
        module_files=[rel_path],
        components=components,
        in_degree={},
        file_to_module={rel_path: "pkg"},
        repo_path=str(tmp_path),
    )

    assert "ENTRY POINTS" in descriptor
    assert "http_route" in descriptor
    assert "/health" in descriptor
