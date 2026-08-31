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

from codewiki.src.be import module_descriptor
from codewiki.src.be.dependency_analyzer.models.core import Node
from codewiki.src.repo_facts import _analyze_repo_path

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
    assert "def Greeter.greet(self, name)" in descriptor
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
