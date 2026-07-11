"""
planner.py

Core build planner: decides full vs incremental build strategy and produces
an ExecutionPlan.

Strategy rules
--------------
Global change condition (triggers full build):
  - Root reactor POM was changed (file maps to ROOT_SENTINEL), OR
  - Any aggregator/BOM POM was changed (packaging=pom with <modules> or
    <dependencyManagement>)

Full build if:
  - Global change occurred, OR
  - No changed files at all (empty changeset), OR
  - len(changed ∪ dependents) / len(buildable_modules) >= 0.6

Incremental build:
  - mvn clean verify -pl :mod1,:mod2 -am

Full build:
  - mvn clean verify

Duration estimate (transparent heuristic, labeled clearly in reason):
  - 30s base per module
  - +10s per test class (*Test.java, *IT.java) found under src/test/java
  - Interface is stable so it can be replaced by historical data later
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Literal, Optional

from forge_planner.changeset import changed_module_ids, ROOT_SENTINEL
from forge_planner.dependency_graph import DependencyGraph, build_graph
from forge_planner.impact import compute_impact, ImpactedModule
from forge_planner.pom_parser import ModuleInfo, discover_reactor

_BASE_DURATION_S = 30
_PER_TEST_CLASS_S = 10


# ---------------------------------------------------------------------------
# Public dataclasses
# ---------------------------------------------------------------------------

@dataclass
class PlannedModule:
    artifact_id: str
    label: Literal["changed", "dependent", "dependency"]
    reason: str
    estimated_duration_seconds: int
    estimated_test_count: int


@dataclass
class ExecutionPlan:
    strategy: Literal["full", "incremental"]
    reason: str
    modules: list[PlannedModule]
    maven_command: str
    estimated_duration_seconds: int
    estimated_test_count: int

    def to_dict(self) -> dict:
        """Convert to a JSON-serialisable dict."""
        return {
            "strategy": self.strategy,
            "reason": self.reason,
            "modules": [
                {
                    "artifact_id": m.artifact_id,
                    "label": m.label,
                    "reason": m.reason,
                    "estimated_duration_seconds": m.estimated_duration_seconds,
                    "estimated_test_count": m.estimated_test_count,
                }
                for m in self.modules
            ],
            "maven_command": self.maven_command,
            "estimated_duration_seconds": self.estimated_duration_seconds,
            "estimated_test_count": self.estimated_test_count,
        }


# ---------------------------------------------------------------------------
# Duration estimation
# ---------------------------------------------------------------------------

def estimate_module_duration(module_dir: str) -> tuple[int, int]:
    """
    Estimate build duration and test-class count for a module.

    HEURISTIC (transparent): 30s base + 10s per *Test.java / *IT.java file
    found anywhere under <module>/src/test/java/.

    This interface is stable — it can be replaced by historical data later
    by substituting a different implementation of this function.

    Returns
    -------
    (estimated_duration_seconds, test_class_count)
    """
    test_root = os.path.join(module_dir, "src", "test", "java")
    test_count = 0

    if os.path.isdir(test_root):
        for dirpath, _dirnames, filenames in os.walk(test_root):
            for fname in filenames:
                if fname.endswith("Test.java") or fname.endswith("IT.java"):
                    test_count += 1

    duration = _BASE_DURATION_S + _PER_TEST_CLASS_S * test_count
    return duration, test_count


# ---------------------------------------------------------------------------
# Main planner entry point
# ---------------------------------------------------------------------------

def plan(
    repo_root: str,
    changed_files: list[str],
    active_profiles: list[str] | None = None,
) -> ExecutionPlan:
    """
    Produce an ExecutionPlan for the given set of changed files.

    Parameters
    ----------
    repo_root : str
        Absolute path to the repository root (must contain pom.xml).
    changed_files : list[str]
        Paths to changed files (absolute or relative to repo_root).
    active_profiles : list[str] | None
        Profile ids to treat as active, in addition to profiles that are
        activeByDefault.  Pass [] to suppress all non-default profiles.
        Pass None to use the default (activeByDefault only).

    Returns
    -------
    ExecutionPlan
    """
    repo_root = os.path.abspath(repo_root)
    root_pom = os.path.join(repo_root, "pom.xml")

    if active_profiles is None:
        active_profiles = []

    # 1. Discover reactor
    modules: dict[str, ModuleInfo] = discover_reactor(root_pom, active_profiles)

    # 2. Build dependency graph
    graph: DependencyGraph = build_graph(modules)

    # Buildable modules: all modules except the root aggregator (packaging=pom
    # with submodules but no direct artifact output other than aggregation)
    # For build ratio calculation we include everything in the reactor.
    buildable_modules = modules  # all discovered modules

    # 3. Map changed files to modules
    if not changed_files:
        # Empty changeset → full build by definition
        return _full_build_plan(
            reason="no changed files specified; defaulting to full build",
            modules=modules,
        )

    changed_ids, is_global = changed_module_ids(changed_files, modules, repo_root)

    # 4. Global change check
    if is_global:
        return _full_build_plan(
            reason="global change detected (root POM or aggregator/BOM POM changed)",
            modules=modules,
        )

    # 5. Compute impact set (changed + transitive dependents)
    impacted: list[ImpactedModule] = compute_impact(changed_ids, graph, include_upstream=False)
    impacted_ids = {m.artifact_id for m in impacted}

    # 6. Ratio check
    ratio = len(impacted_ids) / max(len(buildable_modules), 1)
    if ratio >= 0.6:
        return _full_build_plan(
            reason=(
                f"impact ratio {ratio:.0%} >= 60% of reactor "
                f"({len(impacted_ids)}/{len(buildable_modules)} modules affected)"
            ),
            modules=modules,
        )

    # 7. Incremental build
    # Also include upstream deps via -am (Maven will resolve them, but we label them)
    impacted_with_upstream = compute_impact(changed_ids, graph, include_upstream=True)

    planned = [
        _to_planned_module(m, modules)
        for m in impacted_with_upstream
    ]

    # -pl argument: only changed + dependent modules (not the upstream deps,
    # those are handled by -am)
    pl_modules = [m for m in impacted_with_upstream if m.label in ("changed", "dependent")]
    pl_arg = ",".join(f":{m.artifact_id}" for m in pl_modules)
    command = f"mvn clean verify -pl {pl_arg} -am"

    total_duration = sum(m.estimated_duration_seconds for m in planned)
    total_tests = sum(m.estimated_test_count for m in planned)

    return ExecutionPlan(
        strategy="incremental",
        reason=(
            f"impact ratio {ratio:.0%} < 60%; "
            f"{len(impacted_ids)} module(s) affected out of {len(buildable_modules)}"
        ),
        modules=planned,
        maven_command=command,
        estimated_duration_seconds=total_duration,
        estimated_test_count=total_tests,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _to_planned_module(impacted: ImpactedModule, modules: dict[str, ModuleInfo]) -> PlannedModule:
    info = modules.get(impacted.artifact_id)
    if info:
        duration, test_count = estimate_module_duration(info.directory)
    else:
        duration, test_count = _BASE_DURATION_S, 0
    return PlannedModule(
        artifact_id=impacted.artifact_id,
        label=impacted.label,
        reason=impacted.reason,
        estimated_duration_seconds=duration,
        estimated_test_count=test_count,
    )


def _full_build_plan(reason: str, modules: dict[str, ModuleInfo]) -> ExecutionPlan:
    """Build an ExecutionPlan for a full build."""
    planned: list[PlannedModule] = []
    for aid, info in sorted(modules.items()):
        duration, test_count = estimate_module_duration(info.directory)
        planned.append(PlannedModule(
            artifact_id=aid,
            label="changed",   # all modules are "in scope" for a full build
            reason="full build includes all modules",
            estimated_duration_seconds=duration,
            estimated_test_count=test_count,
        ))

    total_duration = sum(m.estimated_duration_seconds for m in planned)
    total_tests = sum(m.estimated_test_count for m in planned)

    return ExecutionPlan(
        strategy="full",
        reason=reason,
        modules=planned,
        maven_command="mvn clean verify",
        estimated_duration_seconds=total_duration,
        estimated_test_count=total_tests,
    )
