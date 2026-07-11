"""
dependency_graph.py

Builds a directed dependency graph of the Maven reactor.

Edge semantics: if module A depends on module B (B is in A's <dependencies>),
we record the edge B → A, meaning "B must be built before A" and "A is a
dependent of B".  This is the standard Maven reactor ordering direction.

Only reactor-internal edges are kept (i.e., the depended-on artifactId must be
another module discovered in the same reactor).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from forge_planner.pom_parser import ModuleInfo


@dataclass
class DependencyGraph:
    """
    Directed graph of the reactor.

    dependents[X] = set of modules that directly depend on X
                    (i.e., X must be built before them)
    dependencies[X] = set of modules that X directly depends on
    """
    # artifact_id → set of artifact_ids that depend on it (downstream consumers)
    dependents: dict[str, set[str]] = field(default_factory=dict)
    # artifact_id → set of artifact_ids it depends on (upstream providers)
    dependencies: dict[str, set[str]] = field(default_factory=dict)

    def all_modules(self) -> set[str]:
        """Return the full set of artifact_ids in the graph."""
        return set(self.dependents.keys()) | set(self.dependencies.keys())

    def transitive_dependents(self, artifact_ids: set[str]) -> set[str]:
        """
        Return the set of all modules that transitively depend on any module
        in artifact_ids (not including artifact_ids themselves).
        """
        visited: set[str] = set()
        queue: list[str] = list(artifact_ids)

        while queue:
            current = queue.pop(0)
            for dep in self.dependents.get(current, set()):
                if dep not in visited and dep not in artifact_ids:
                    visited.add(dep)
                    queue.append(dep)

        return visited

    def transitive_dependencies(self, artifact_ids: set[str]) -> set[str]:
        """
        Return the set of all modules that artifact_ids transitively depend on
        (not including artifact_ids themselves).  Used for -am flag resolution.
        """
        visited: set[str] = set()
        queue: list[str] = list(artifact_ids)

        while queue:
            current = queue.pop(0)
            for dep in self.dependencies.get(current, set()):
                if dep not in visited and dep not in artifact_ids:
                    visited.add(dep)
                    queue.append(dep)

        return visited


def build_graph(modules: dict[str, ModuleInfo]) -> DependencyGraph:
    """
    Build a DependencyGraph from the reactor module map.

    Parameters
    ----------
    modules : dict[str, ModuleInfo]
        Mapping of artifactId → ModuleInfo for every module in the reactor,
        as returned by pom_parser.discover_reactor().

    Returns
    -------
    DependencyGraph
        Graph with only reactor-internal edges.
    """
    reactor_ids = set(modules.keys())

    graph = DependencyGraph(
        dependents={aid: set() for aid in reactor_ids},
        dependencies={aid: set() for aid in reactor_ids},
    )

    for artifact_id, info in modules.items():
        for dep in info.dependencies:
            if dep.artifact_id in reactor_ids:
                # artifact_id depends on dep.artifact_id
                # Edge: dep.artifact_id → artifact_id
                graph.dependents[dep.artifact_id].add(artifact_id)
                graph.dependencies[artifact_id].add(dep.artifact_id)

    return graph
