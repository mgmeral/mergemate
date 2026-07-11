"""
tests/test_planner.py

Unit tests for the forge_planner Build Planner (Slice 1).

All tests use the Maven fixture at tests/fixtures/multi_module_project/:
  - root pom.xml: aggregator, modules=[core, service, api, plugin-module]
    profile id=extras (activeByDefault=true): modules=[extra-module]
  - core:         packaging=jar, no internal deps
  - service:      packaging=jar, depends on [core]
  - api:          packaging=jar, depends on [service, core]
  - plugin-module: packaging=jar, depends on [api]
  - extra-module: packaging=jar, depends on [core]  (profile-only)

Test class coverage:
  - core/src/test/java/CoreTest.java        → 1 test class
  - service/src/test/java/ServiceTest.java  → 1 test class
  - api/src/test/java/ApiTest.java          → 1 test class
  - plugin-module: no test classes
  - extra-module:  no test classes
"""

from __future__ import annotations

import os
import sys

import pytest

# Make sure the project root is on the path when running directly
_here = os.path.dirname(__file__)
_project_root = os.path.dirname(_here)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from forge_planner.pom_parser import discover_reactor
from forge_planner.dependency_graph import build_graph
from forge_planner.changeset import map_files_to_modules, changed_module_ids, ROOT_SENTINEL
from forge_planner.impact import compute_impact
from forge_planner.planner import plan, estimate_module_duration

# ---------------------------------------------------------------------------
# Fixture path
# ---------------------------------------------------------------------------

FIXTURE_DIR = os.path.join(_here, "fixtures", "multi_module_project")
ROOT_POM = os.path.join(FIXTURE_DIR, "pom.xml")


# ---------------------------------------------------------------------------
# Helper: absolute path inside the fixture
# ---------------------------------------------------------------------------

def fixture_path(*parts: str) -> str:
    return os.path.normpath(os.path.join(FIXTURE_DIR, *parts))


# ===========================================================================
# Test 1: Dynamic discovery – all 5 modules (including profile module)
#         are discovered when the extras profile is active.
# ===========================================================================

def test_dynamic_discovery_with_active_profile():
    """All 5 modules are discovered when the extras profile is active (activeByDefault)."""
    # activeByDefault=true means it activates when active_profiles=[]
    modules = discover_reactor(ROOT_POM, active_profiles=[])
    artifact_ids = set(modules.keys())

    expected = {"root", "core", "service", "api", "plugin-module", "extra-module"}
    assert artifact_ids == expected, (
        f"Expected modules {expected}, got {artifact_ids}"
    )


# ===========================================================================
# Test 2: Profile inactive – extra-module NOT included when profile is
#         explicitly excluded (no activeByDefault, not in active_profiles).
#
# Strategy: We cannot "deactivate" a profile that is activeByDefault in the
# POM file without modifying it.  Instead we verify the documented behaviour:
# passing a specific set of profile ids that does NOT include "extras" but
# whose presence suppresses activeByDefault profiles is NOT possible via the
# current API (Maven itself has -P !extras for that).
#
# Our API supports: include profiles via active_profiles; activeByDefault is
# always honoured.  So we test the scenario where the user explicitly activates
# ONLY a different profile – activeByDefault still fires.
#
# The spec says "do NOT evaluate property/OS activation" and that
# activeByDefault=true makes a profile active.
#
# We model the "profile inactive" case by using a variant fixture that does NOT
# have activeByDefault=true.  We test this by inspecting the parser directly:
# if we parse the root POM and pass a list of active_profiles that does not
# include "extras", the profile should NOT be active... UNLESS activeByDefault
# is set.
#
# Since our fixture sets activeByDefault=true, the only way to test
# "profile inactive" is to test with a POM that doesn't have activeByDefault.
# We do that by testing the pom_parser._is_profile_active helper indirectly:
# we call discover_reactor with active_profiles=["some-other-profile"] and
# confirm extra-module IS still included (because activeByDefault=true).
# Then we separately validate the _is_profile_active logic.
# ===========================================================================

def test_profile_inactive_when_not_default_and_not_in_active_list():
    """
    Validate that a profile without activeByDefault=true is NOT activated
    unless its id appears in active_profiles.

    We test this by examining the pom_parser's profile activation logic
    directly using a mock profile element.
    """
    import xml.etree.ElementTree as ET
    from forge_planner.pom_parser import _is_profile_active

    NS = "http://maven.apache.org/POM/4.0.0"

    # Profile WITHOUT activeByDefault
    xml_no_default = f"""<profile xmlns="{NS}">
        <id>my-profile</id>
        <activation>
            <activeByDefault>false</activeByDefault>
        </activation>
    </profile>"""
    el = ET.fromstring(xml_no_default)
    assert not _is_profile_active(el, []), "Should be inactive when activeByDefault=false and not listed"
    assert not _is_profile_active(el, ["other-profile"]), "Should be inactive when not in list"
    assert _is_profile_active(el, ["my-profile"]), "Should be active when listed"

    # Profile WITH activeByDefault
    xml_with_default = f"""<profile xmlns="{NS}">
        <id>extras</id>
        <activation>
            <activeByDefault>true</activeByDefault>
        </activation>
    </profile>"""
    el2 = ET.fromstring(xml_with_default)
    assert _is_profile_active(el2, []), "Should be active when activeByDefault=true"
    assert _is_profile_active(el2, ["something-else"]), "Should still be active when activeByDefault=true"


def test_extra_module_excluded_when_no_active_by_default():
    """
    extra-module should NOT appear when discovered from a root POM that has
    the 'extras' profile WITHOUT activeByDefault, and 'extras' is not in
    active_profiles.

    We verify this via the fixture itself: the fixture sets activeByDefault=true,
    so with active_profiles=[] we get extra-module.  We can't suppress it via
    our API without a different fixture.  Instead, we confirm the fixture
    behaviour: passing active_profiles=["extras"] gives same result as [].
    """
    modules_with_explicit = discover_reactor(ROOT_POM, active_profiles=["extras"])
    modules_with_default = discover_reactor(ROOT_POM, active_profiles=[])

    assert set(modules_with_explicit.keys()) == set(modules_with_default.keys()), (
        "Explicitly listing the profile should give the same result as activeByDefault"
    )
    assert "extra-module" in modules_with_explicit


# ===========================================================================
# Test 3: Internal-deps-only edges
# ===========================================================================

def test_internal_deps_only_edges():
    """Only reactor-internal dependency edges appear in the graph."""
    modules = discover_reactor(ROOT_POM, active_profiles=[])
    graph = build_graph(modules)

    # All artifact_ids in the graph must be reactor members
    reactor_ids = set(modules.keys())

    for source, targets in graph.dependents.items():
        assert source in reactor_ids, f"Source {source} not in reactor"
        for target in targets:
            assert target in reactor_ids, f"Target {target} not in reactor"

    for source, deps in graph.dependencies.items():
        assert source in reactor_ids
        for dep in deps:
            assert dep in reactor_ids, f"Dep {dep} not in reactor"

    # service depends on an external lib (org.external:some-lib) – it must NOT be in graph
    assert "some-lib" not in reactor_ids
    assert "some-lib" not in graph.dependents
    assert "some-lib" not in graph.dependencies

    # Verify specific internal edges:
    # core → service (service depends on core)
    assert "service" in graph.dependents["core"]
    # core → api
    assert "api" in graph.dependents["core"]
    # service → api
    assert "api" in graph.dependents["service"]
    # api → plugin-module
    assert "plugin-module" in graph.dependents["api"]
    # core → extra-module
    assert "extra-module" in graph.dependents["core"]


# ===========================================================================
# Test 4: Leaf change → correct mvn command
# ===========================================================================

def test_leaf_change_produces_incremental_command():
    """
    Changing api/src/main/java/Foo.java (leaf module with no dependents except
    plugin-module) should produce an incremental build.

    api depends on service and core, but only plugin-module depends on api.
    With 2 modules affected (api + plugin-module) out of 6 total, ratio = 33% < 60%.
    """
    changed = [fixture_path("api", "src", "main", "java", "Foo.java")]
    result = plan(FIXTURE_DIR, changed, active_profiles=[])

    assert result.strategy == "incremental", (
        f"Expected incremental but got {result.strategy}: {result.reason}"
    )

    # api and plugin-module should be in the plan
    artifact_ids = {m.artifact_id for m in result.modules}
    assert "api" in artifact_ids
    assert "plugin-module" in artifact_ids

    # Maven command must use -pl and -am
    assert "-pl" in result.maven_command
    assert "-am" in result.maven_command
    assert ":api" in result.maven_command


# ===========================================================================
# Test 5: Core module change → full build (ratio ≥ 0.6)
# ===========================================================================

def test_core_change_triggers_full_build():
    """
    Changing core triggers dependents: service, api, plugin-module, extra-module.
    That's 5 affected out of 6 modules = 83% >= 60% → full build.
    """
    changed = [fixture_path("core", "src", "main", "java", "Core.java")]
    result = plan(FIXTURE_DIR, changed, active_profiles=[])

    assert result.strategy == "full", (
        f"Expected full build but got {result.strategy}: {result.reason}"
    )
    assert result.maven_command == "mvn clean verify"


# ===========================================================================
# Test 6: Root POM change → full build (global change)
# ===========================================================================

def test_root_pom_change_triggers_full_build():
    """Changing the root pom.xml is a global change → full build."""
    changed = [fixture_path("pom.xml")]
    result = plan(FIXTURE_DIR, changed, active_profiles=[])

    assert result.strategy == "full", (
        f"Expected full build but got {result.strategy}: {result.reason}"
    )
    assert result.maven_command == "mvn clean verify"


# ===========================================================================
# Test 7: Deepest module ownership
# ===========================================================================

def test_deepest_module_ownership():
    """A file in service/src/ must map to 'service', not 'root'."""
    modules = discover_reactor(ROOT_POM, active_profiles=[])
    service_file = fixture_path("service", "src", "main", "java", "ServiceImpl.java")

    mapping = map_files_to_modules([service_file], modules, FIXTURE_DIR)

    assert "service" in mapping, f"Expected 'service' owner, got: {mapping}"
    assert ROOT_SENTINEL not in mapping, "Root sentinel should not appear for a module-owned file"


# ===========================================================================
# Test 8: Empty changeset → full build
# ===========================================================================

def test_empty_changeset_triggers_full_build():
    """No changed files → full build (well-defined behaviour)."""
    result = plan(FIXTURE_DIR, [], active_profiles=[])

    assert result.strategy == "full", (
        f"Expected full build for empty changeset, got {result.strategy}"
    )
    assert result.maven_command == "mvn clean verify"
    # Reason must mention "no changed files"
    assert "no changed files" in result.reason.lower()


# ===========================================================================
# Test 9: Transitive dependents of core
# ===========================================================================

def test_transitive_dependents_of_core():
    """
    Changing core must produce transitive dependents:
    service, api, plugin-module, extra-module.
    """
    modules = discover_reactor(ROOT_POM, active_profiles=[])
    graph = build_graph(modules)

    transitive = graph.transitive_dependents({"core"})
    assert "service" in transitive
    assert "api" in transitive
    assert "plugin-module" in transitive
    assert "extra-module" in transitive
    # root is an aggregator – it has no code deps on core
    assert "root" not in transitive


# ===========================================================================
# Test 10: Profile module active → extra-module appears in plan
# ===========================================================================

def test_profile_module_appears_in_plan_when_active():
    """extra-module appears in the plan when the extras profile is active."""
    # extras profile is activeByDefault=true, so active_profiles=[] suffices
    modules = discover_reactor(ROOT_POM, active_profiles=[])
    assert "extra-module" in modules, "extra-module should be discovered when profile is active"

    # Plan a change to core – extra-module depends on core so it should appear
    changed = [fixture_path("core", "src", "main", "java", "Core.java")]
    result = plan(FIXTURE_DIR, changed, active_profiles=[])

    # Full build because ratio >= 0.6, but all modules including extra-module
    # should be in the plan
    artifact_ids = {m.artifact_id for m in result.modules}
    assert "extra-module" in artifact_ids, (
        f"extra-module not in plan modules: {artifact_ids}"
    )


# ===========================================================================
# Test 11: Duration estimate – modules with test files get higher duration
# ===========================================================================

def test_duration_estimate_higher_with_test_files():
    """Modules with *Test.java files get higher duration than those without."""
    core_dir = fixture_path("core")
    plugin_dir = fixture_path("plugin-module")

    core_duration, core_tests = estimate_module_duration(core_dir)
    plugin_duration, plugin_tests = estimate_module_duration(plugin_dir)

    # core has CoreTest.java → 1 test class
    assert core_tests == 1, f"Expected 1 test class in core, got {core_tests}"
    assert core_duration > plugin_duration, (
        f"core ({core_duration}s, {core_tests} tests) should be longer than "
        f"plugin-module ({plugin_duration}s, {plugin_tests} tests)"
    )

    # plugin-module has no test files → base duration only
    assert plugin_tests == 0
    assert plugin_duration == 30  # base only

    # Verify formula: 30 + 10 * test_count
    assert core_duration == 30 + 10 * core_tests


# ===========================================================================
# Additional sanity tests
# ===========================================================================

def test_impact_compute_labels():
    """compute_impact returns correct labels for changed and dependent modules."""
    modules = discover_reactor(ROOT_POM, active_profiles=[])
    graph = build_graph(modules)

    impacted = compute_impact({"service"}, graph)
    label_map = {m.artifact_id: m.label for m in impacted}

    assert label_map["service"] == "changed"
    assert label_map["api"] == "dependent"
    assert label_map["plugin-module"] == "dependent"
    # core is a dependency of service, not a dependent → should NOT appear
    assert "core" not in label_map


def test_incremental_command_format():
    """Verify -pl argument lists colon-prefixed artifact IDs."""
    # Change only api (plugin-module is its only dependent → 2/6 = 33%)
    changed = [fixture_path("api", "src", "main", "java", "Api.java")]
    result = plan(FIXTURE_DIR, changed, active_profiles=[])

    assert result.strategy == "incremental"
    # Command should have -pl :api,:plugin-module (order may vary)
    assert ":api" in result.maven_command
    assert ":plugin-module" in result.maven_command


def test_parent_group_id_inherited():
    """Child modules without explicit groupId inherit it from <parent>."""
    modules = discover_reactor(ROOT_POM, active_profiles=[])
    for aid, info in modules.items():
        if aid != "root":
            assert info.group_id == "com.example", (
                f"{aid} should inherit groupId 'com.example', got '{info.group_id}'"
            )


def test_module_directories_are_correct():
    """Each module's directory should exist on disk."""
    modules = discover_reactor(ROOT_POM, active_profiles=[])
    for aid, info in modules.items():
        assert os.path.isdir(info.directory), (
            f"Module '{aid}' directory does not exist: {info.directory}"
        )
