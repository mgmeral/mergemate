"""
TestCandidate scoring with confidence and reasons.
"""
from __future__ import annotations

from mergemate.domain.models import JavaClassInfo, TestCandidate, MavenProject, ModuleImpact
from mergemate.java_analysis.class_graph import JavaDependencyGraph
from mergemate.java_analysis.test_finder import (
    TEST_SUFFIXES,
    INTEGRATION_SUFFIXES,
    match_level1_naming,
    match_level2_references,
    match_level3_reverse_deps,
)

# Score weights for each signal
SCORE_WEIGHTS = {
    "level1_name_match": 0.40,
    "level2_direct_import": 0.35,
    "level2_type_reference": 0.25,
    "level3_reverse_dep_1hop": 0.20,
    "level3_reverse_dep_2hop": 0.12,
    "level3_reverse_dep_3hop": 0.06,
    "same_module": 0.10,
    "same_package": 0.08,
    "downstream_module": 0.05,
    "integration_test_penalty": -0.05,
}

CONFIDENCE_THRESHOLDS = {
    "HIGH": 0.65,
    "MEDIUM": 0.35,
    # Below MEDIUM -> LOW
}


def score_test_candidates(
    changed_prod_class: JavaClassInfo,
    test_classes: list[JavaClassInfo],
    graph: JavaDependencyGraph,
    project: MavenProject,
    affected_module_ids: set[str],
    max_depth: int = 3,
) -> list[TestCandidate]:
    """
    Score all test classes for relevance to changed_prod_class.

    For each test class:
    1. Compute all applicable signals (name match, imports, type refs, reverse deps)
    2. Sum weighted scores (cap at 1.0)
    3. Collect reasons
    4. Assign confidence (HIGH/MEDIUM/LOW)

    Return sorted by score descending. Only return candidates with score > 0.
    """
    # Pre-compute level1, level2, level3 matches for this prod class
    l1_matches: dict[str, str] = {}
    for tc, reason in match_level1_naming(changed_prod_class, test_classes):
        l1_matches[tc.class_name] = reason

    # Split level2 into direct_import vs type_reference
    l2_import_matches: dict[str, str] = {}
    l2_ref_matches: dict[str, str] = {}

    for tc in test_classes:
        # Check imports: fully qualified or simple name
        for imp in tc.imports:
            if imp == changed_prod_class.qualified_name or imp.endswith("." + changed_prod_class.class_name):
                l2_import_matches[tc.class_name] = f"Directly imports {changed_prod_class.qualified_name}"
                break
        else:
            # Check referenced_types for simple name match
            if changed_prod_class.class_name in tc.referenced_types:
                l2_ref_matches[tc.class_name] = f"References type {changed_prod_class.class_name}"

    # Level 3: reverse deps
    # We need to compute per-test-class and per-hop-depth
    # Compute dependents at each depth
    l3_matches: dict[str, tuple[int, str]] = {}  # class_name -> (depth, reason)

    # Get all prod classes from the graph (non-test classes)
    all_in_graph = graph.all_classes()
    all_prod_in_graph = [c for c in all_in_graph if not c.is_test_class]

    # Find dependents at each depth
    for depth in range(1, max_depth + 1):
        dependents_at_depth = graph.dependents_of(
            changed_prod_class.class_name, max_depth=depth
        )
        # Filter to production classes only
        prod_deps_at_this_level = [
            d for d in dependents_at_depth if not d.is_test_class
        ]
        for dep_prod in prod_deps_at_this_level:
            # Find tests for this dep
            for tc, reason in match_level1_naming(dep_prod, test_classes):
                if tc.class_name not in l3_matches:
                    chain = (
                        f"Tests {dep_prod.class_name} which depends on "
                        f"{changed_prod_class.class_name}"
                    )
                    l3_matches[tc.class_name] = (depth, chain)
            for tc, reason in match_level2_references(dep_prod, test_classes):
                if tc.class_name not in l3_matches:
                    chain = (
                        f"Tests {dep_prod.class_name} which depends on "
                        f"{changed_prod_class.class_name}"
                    )
                    l3_matches[tc.class_name] = (depth, chain)

    # Determine module of changed prod class
    prod_module_id = _find_module_for_class(changed_prod_class, project)

    # Score each test class
    candidates: list[TestCandidate] = []

    for tc in test_classes:
        signals: dict[str, bool] = {}
        reasons: list[str] = []

        # Level 1
        if tc.class_name in l1_matches:
            signals["level1_name_match"] = True
            reasons.append(f"Name matches changed class {changed_prod_class.class_name}")

        # Level 2 direct import
        if tc.class_name in l2_import_matches:
            signals["level2_direct_import"] = True
            reasons.append(l2_import_matches[tc.class_name])

        # Level 2 type reference
        if tc.class_name in l2_ref_matches:
            signals["level2_type_reference"] = True
            reasons.append(l2_ref_matches[tc.class_name])

        # Level 3
        if tc.class_name in l3_matches:
            hop_depth, chain_reason = l3_matches[tc.class_name]
            if hop_depth == 1:
                signals["level3_reverse_dep_1hop"] = True
            elif hop_depth == 2:
                signals["level3_reverse_dep_2hop"] = True
            else:
                signals["level3_reverse_dep_3hop"] = True
            reasons.append(chain_reason)

        # Module-based signals
        test_module_id = _find_module_for_class(tc, project)

        if prod_module_id and test_module_id and prod_module_id == test_module_id:
            signals["same_module"] = True
            reasons.append(f"In same Maven module ({prod_module_id})")
        elif test_module_id and test_module_id in affected_module_ids:
            signals["downstream_module"] = True
            reasons.append(f"In affected module ({test_module_id})")

        # Same package
        if changed_prod_class.package and tc.package == changed_prod_class.package:
            signals["same_package"] = True
            reasons.append(f"In same package ({changed_prod_class.package})")

        # Integration test penalty
        is_integration = _is_integration_test(tc)
        if is_integration:
            signals["integration_test_penalty"] = True

        # Compute score
        score = _compute_score(signals)

        if score <= 0.0:
            continue

        confidence = _assign_confidence(score)

        candidates.append(TestCandidate(
            class_name=tc.class_name,
            file_path=tc.file_path,
            module_artifact_id=test_module_id or "",
            score=round(score, 4),
            confidence=confidence,
            reasons=reasons,
            is_integration_test=is_integration,
        ))

    # Sort by score descending
    candidates.sort(key=lambda c: c.score, reverse=True)
    return candidates


def _is_integration_test(tc: JavaClassInfo) -> bool:
    """Check if the test class is an integration test."""
    for suffix in INTEGRATION_SUFFIXES:
        if tc.class_name.endswith(suffix):
            return True
    return False


def _find_module_for_class(
    java_class: JavaClassInfo,
    project: MavenProject,
) -> str | None:
    """Find which Maven module this Java class belongs to, by file path prefix."""
    if not java_class.file_path:
        return None

    file_path = java_class.file_path.replace("\\", "/")
    best_match: str | None = None
    best_len = -1

    for artifact_id, module in project.modules.items():
        rel_path = module.relative_path.replace("\\", "/")
        if rel_path == "":
            # Root module — matches everything, but lowest priority
            if best_len < 0:
                best_match = artifact_id
                best_len = 0
        else:
            prefix = rel_path if rel_path.endswith("/") else rel_path + "/"
            if file_path.startswith(prefix) or file_path.startswith(rel_path + "/"):
                if len(rel_path) > best_len:
                    best_match = artifact_id
                    best_len = len(rel_path)

    return best_match


def _compute_score(signals: dict[str, bool]) -> float:
    """Sum weights for True signals, cap at 1.0."""
    total = sum(SCORE_WEIGHTS[k] for k, v in signals.items() if v)
    return min(total, 1.0)


def _assign_confidence(score: float) -> str:
    if score >= CONFIDENCE_THRESHOLDS["HIGH"]:
        return "HIGH"
    elif score >= CONFIDENCE_THRESHOLDS["MEDIUM"]:
        return "MEDIUM"
    return "LOW"
