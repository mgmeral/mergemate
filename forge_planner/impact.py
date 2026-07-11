"""
impact.py

Computes the impact set: which modules are affected by a set of changes.

affected = changed_modules ∪ transitive_dependents(changed_modules)

Labels:
  "changed"   – the module itself has changed files
  "dependent" – a module that transitively depends on a changed module
  "dependency" – a module pulled in via -am (upstream dependency of a selected
                 module); used when the caller explicitly requests it
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from forge_planner.dependency_graph import DependencyGraph


@dataclass
class ImpactedModule:
    artifact_id: str
    label: Literal["changed", "dependent", "dependency"]
    reason: str


def compute_impact(
    changed_ids: set[str],
    graph: DependencyGraph,
    include_upstream: bool = False,
) -> list[ImpactedModule]:
    """
    Compute the full impact set.

    Parameters
    ----------
    changed_ids : set[str]
        Artifact IDs of modules that directly contain changed files.
    graph : DependencyGraph
        Reactor dependency graph.
    include_upstream : bool
        If True, also include upstream dependencies (-am behaviour) and label
        them as "dependency".

    Returns
    -------
    list[ImpactedModule]
        Ordered list: changed first, then dependents, then dependencies.
    """
    result: list[ImpactedModule] = []
    seen: set[str] = set()

    # 1. Changed modules
    for aid in sorted(changed_ids):
        result.append(ImpactedModule(
            artifact_id=aid,
            label="changed",
            reason="contains changed files",
        ))
        seen.add(aid)

    # 2. Transitive dependents
    transitive_deps = graph.transitive_dependents(changed_ids)
    for aid in sorted(transitive_deps):
        if aid not in seen:
            # Find the shortest reason chain (which changed module triggered this?)
            # For simplicity, report "depends on a changed module"
            result.append(ImpactedModule(
                artifact_id=aid,
                label="dependent",
                reason=f"transitively depends on a changed module",
            ))
            seen.add(aid)

    # 3. Upstream dependencies (only when requested, for -am)
    if include_upstream:
        selected = changed_ids | transitive_deps
        upstream = graph.transitive_dependencies(selected)
        for aid in sorted(upstream):
            if aid not in seen:
                result.append(ImpactedModule(
                    artifact_id=aid,
                    label="dependency",
                    reason="upstream dependency required by -am",
                ))
                seen.add(aid)

    return result
