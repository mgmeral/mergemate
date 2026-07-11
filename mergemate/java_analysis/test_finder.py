"""
Test class discovery and Level 1/2/3 matching.
"""
from __future__ import annotations

import os

from mergemate.domain.models import JavaClassInfo, MavenProject
from mergemate.java_analysis.class_graph import JavaDependencyGraph
from mergemate.java_analysis.parser import parse_java_files

# Test class name suffixes/patterns
TEST_SUFFIXES = ["Test", "Tests", "IT", "IntegrationTest", "Spec"]
INTEGRATION_SUFFIXES = ["IT", "IntegrationTest"]


def find_test_classes(
    repo_root: str,
    project: MavenProject,
    unit_patterns: list[str] | None = None,
    integration_patterns: list[str] | None = None,
) -> list[JavaClassInfo]:
    """
    Discover all test Java files in the project.
    Scans src/test/java directories of all modules.
    Parses each file to get JavaClassInfo.
    """
    test_file_paths: list[str] = []

    for module in project.modules.values():
        module_dir = os.path.join(project.root_dir, module.relative_path) if module.relative_path else project.root_dir
        test_java_dir = os.path.join(module_dir, "src", "test", "java")

        if not os.path.isdir(test_java_dir):
            continue

        for dirpath, _dirnames, filenames in os.walk(test_java_dir):
            for fname in filenames:
                if fname.endswith(".java"):
                    abs_path = os.path.join(dirpath, fname)
                    rel_path = os.path.relpath(abs_path, project.root_dir).replace("\\", "/")
                    test_file_paths.append(rel_path)

    return parse_java_files(test_file_paths, project.root_dir)


def find_production_classes(
    repo_root: str,
    project: MavenProject,
    file_paths: list[str],
) -> list[JavaClassInfo]:
    """Parse the given changed production Java files."""
    return parse_java_files(file_paths, repo_root)


def match_level1_naming(
    prod_class: JavaClassInfo,
    test_classes: list[JavaClassInfo],
) -> list[tuple[JavaClassInfo, str]]:
    """
    Level 1: Naming convention match.
    Find tests whose name = prod_class.class_name + suffix (Test, Tests, IT, etc.)
    Returns: [(test_class, reason), ...]
    """
    results: list[tuple[JavaClassInfo, str]] = []
    for tc in test_classes:
        for suffix in TEST_SUFFIXES:
            expected = prod_class.class_name + suffix
            if tc.class_name == expected:
                reason = f"Name matches changed class {prod_class.class_name} (+ {suffix} suffix)"
                results.append((tc, reason))
                break
    return results


def match_level2_references(
    prod_class: JavaClassInfo,
    test_classes: list[JavaClassInfo],
) -> list[tuple[JavaClassInfo, str]]:
    """
    Level 2: Import and type reference matching.
    Find tests that import or reference the production class.
    Returns: [(test_class, reason), ...]
    """
    results: list[tuple[JavaClassInfo, str]] = []
    for tc in test_classes:
        # Check imports: fully qualified or simple name
        for imp in tc.imports:
            if imp == prod_class.qualified_name or imp.endswith("." + prod_class.class_name):
                reason = f"Directly imports {prod_class.qualified_name}"
                results.append((tc, reason))
                break
        else:
            # Check referenced_types for simple name match
            if prod_class.class_name in tc.referenced_types:
                reason = f"References type {prod_class.class_name}"
                results.append((tc, reason))
    return results


def match_level3_reverse_deps(
    prod_class: JavaClassInfo,
    all_prod_classes: list[JavaClassInfo],
    graph: JavaDependencyGraph,
    test_classes: list[JavaClassInfo],
    max_depth: int = 3,
) -> list[tuple[JavaClassInfo, str]]:
    """
    Level 3: Reverse dependency graph.

    1. Find all production classes that transitively depend on prod_class (via graph)
    2. For each such dependent production class, find its tests (level 1 + level 2)
    3. Return those tests with reason explaining the chain
    """
    results: list[tuple[JavaClassInfo, str]] = []

    # Find prod classes that depend on prod_class
    dependents = graph.dependents_of(prod_class.class_name, max_depth=max_depth)

    # Filter to only production classes
    prod_class_names = {pc.class_name for pc in all_prod_classes}
    prod_dependents = [d for d in dependents if not d.is_test_class]

    seen_tests: set[str] = set()

    for dep_prod in prod_dependents:
        # Find tests for this dependent prod class
        l1 = match_level1_naming(dep_prod, test_classes)
        l2 = match_level2_references(dep_prod, test_classes)

        for tc, reason in l1 + l2:
            if tc.class_name not in seen_tests:
                seen_tests.add(tc.class_name)
                chain_reason = (
                    f"Tests {dep_prod.class_name} which depends on {prod_class.class_name} "
                    f"(via {reason})"
                )
                results.append((tc, chain_reason))

    return results
