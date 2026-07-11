"""
Maven module dependency graph.

Edge A -> B means "A depends on B" (B must build before A).
Reverse edge B -> A means "A is a dependent of B".
"""
from __future__ import annotations

from collections import deque
from mergemate.domain.models import MavenModule, MavenProject


class ModuleGraph:
    """
    Directed dependency graph for Maven modules.
    Edge A -> B means "A depends on B" (B must build before A).
    Reverse edge B -> A means "A is a dependent of B".
    """

    def __init__(self, project: MavenProject):
        self._modules = project.modules  # artifactId -> MavenModule
        self._dependents: dict[str, set[str]] = {}   # B -> {all A that depend on B}
        self._dependencies: dict[str, set[str]] = {}  # A -> {all B that A depends on}
        self._build(project)

    def _build(self, project: MavenProject) -> None:
        """Build the graph from module dependency lists."""
        # Initialize empty sets for all modules
        for artifact_id in project.modules:
            self._dependents.setdefault(artifact_id, set())
            self._dependencies.setdefault(artifact_id, set())

        for artifact_id, module in project.modules.items():
            for dep_id in module.dependencies:
                if dep_id in project.modules:
                    # A depends on dep_id
                    self._dependencies.setdefault(artifact_id, set()).add(dep_id)
                    # dep_id has A as a dependent
                    self._dependents.setdefault(dep_id, set()).add(artifact_id)

    def transitive_dependents(
        self,
        module_ids: set[str],
        max_depth: int = 10,
    ) -> set[str]:
        """
        BFS from module_ids following dependent edges.
        Returns all modules that transitively depend on any of the given modules.
        Does NOT include the input modules themselves.
        Respects max_depth to prevent infinite loops.
        """
        visited: set[str] = set()
        queue: deque[tuple[str, int]] = deque()

        for mid in module_ids:
            for dependent in self._dependents.get(mid, set()):
                if dependent not in module_ids and dependent not in visited:
                    visited.add(dependent)
                    queue.append((dependent, 1))

        while queue:
            current, depth = queue.popleft()
            if depth >= max_depth:
                continue
            for dependent in self._dependents.get(current, set()):
                if dependent not in module_ids and dependent not in visited:
                    visited.add(dependent)
                    queue.append((dependent, depth + 1))

        return visited

    def transitive_dependencies(
        self,
        module_ids: set[str],
        max_depth: int = 10,
    ) -> set[str]:
        """
        BFS from module_ids following dependency edges.
        Returns all modules that the given modules transitively depend on.
        """
        visited: set[str] = set()
        queue: deque[tuple[str, int]] = deque()

        for mid in module_ids:
            for dep in self._dependencies.get(mid, set()):
                if dep not in module_ids and dep not in visited:
                    visited.add(dep)
                    queue.append((dep, 1))

        while queue:
            current, depth = queue.popleft()
            if depth >= max_depth:
                continue
            for dep in self._dependencies.get(current, set()):
                if dep not in module_ids and dep not in visited:
                    visited.add(dep)
                    queue.append((dep, depth + 1))

        return visited

    def direct_dependents(self, artifact_id: str) -> set[str]:
        """Return the set of modules that directly depend on artifact_id."""
        return set(self._dependents.get(artifact_id, set()))

    def all_module_ids(self) -> set[str]:
        return set(self._modules.keys())
