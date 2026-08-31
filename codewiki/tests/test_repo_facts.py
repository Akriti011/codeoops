"""Unit tests for repo_facts.extract_repo_facts (OVERVIEW_QUALITY_SPEC.md
section 3).

No LLM calls anywhere in repo_facts.py, and none in this file — these run
against a small, checked-in fixture repository (tests/fixtures/
repo_facts_fixture/) so extraction is exact-assertable and fast.
"""

from __future__ import annotations

import os
import time

import pytest

from codewiki.src.repo_facts import Dependency, extract_repo_facts, _analyze_repo_path

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "repo_facts_fixture")


@pytest.fixture(scope="module")
def facts():
    modules, components = _analyze_repo_path(FIXTURE)
    return extract_repo_facts(FIXTURE, modules, components)


def test_extraction_runs_under_one_second():
    start = time.perf_counter()
    modules, components = _analyze_repo_path(FIXTURE)
    extract_repo_facts(FIXTURE, modules, components)
    elapsed = time.perf_counter() - start
    assert elapsed < 1.0, f"extraction took {elapsed:.3f}s, expected < 1s"


def test_dependencies_exact(facts):
    assert facts.dependencies == [
        Dependency(name="requests", version="2.31.0", manifest="requirements.txt"),
        Dependency(name="flask", version="2.0.1", manifest="requirements.txt"),
    ]


def test_manifests_found_exact(facts):
    # requirements.txt (dependencies) and the .github/workflows CI file
    # (see test_ci_detected) are both real manifests in this fixture.
    assert facts.manifests_found == ["requirements.txt", ".github/workflows/ci.yml"]


def test_entry_points_exact(facts):
    main_entries = sorted(
        (e.file, e.line, e.name, e.detail) for e in facts.entry_points if e.kind == "main"
    )
    assert main_entries == [
        ("app/main.py", 6, "main()", "main()"),
        ("app/main.py", 11, "__main__ guard", "__main__ guard"),
    ]
    # No http_route/console_script/npm_script/docker_cmd/spark_submit
    # patterns exist in this fixture — nothing invented for them.
    assert {e.kind for e in facts.entry_points} == {"main"}


def test_config_items_exact(facts):
    by_name = {c.name: c for c in facts.config_items}
    assert set(by_name) == {"API_KEY", "DEBUG"}

    assert by_name["API_KEY"].source == "app/settings.py"
    assert by_name["API_KEY"].required is True
    assert by_name["API_KEY"].default is None

    assert by_name["DEBUG"].source == "app/settings.py"
    assert by_name["DEBUG"].required is False
    assert by_name["DEBUG"].default == '"false"'


def test_readme_captured_verbatim(facts):
    assert facts.readme_text is not None
    assert facts.readme_text.startswith("# Demo Fixture")
    assert "not a real project" in facts.readme_text.lower()


def test_ci_detected(facts):
    assert facts.has_ci is True
    assert facts.ci_files == [".github/workflows/ci.yml"]


def test_no_dockerfile(facts):
    assert facts.has_dockerfile is False


def test_language_stats_python(facts):
    langs = {l.language: l for l in facts.languages}
    assert langs["Python"].files == 4  # __init__, settings, service, main


def test_single_module_has_no_edges_or_cycles(facts):
    # All four .py files live directly under app/, so module_grouper puts
    # them in one module — nothing to draw a cross-module edge between,
    # and a single module can't cycle with itself.
    assert facts.module_edges == []
    assert facts.hub_modules == []
    assert facts.leaf_modules == ["app"]
    assert facts.cycles == []


def test_no_llm_import_anywhere():
    """repo_facts.py must not import anything LLM-related — grep-level
    guarantee that this stage really is deterministic."""
    import codewiki.src.repo_facts as module

    source = open(module.__file__, encoding="utf-8").read()
    for forbidden in ("backend.py", "LLMBackend", "ollama", "openai", ".complete("):
        assert forbidden not in source, f"repo_facts.py references {forbidden!r}"
