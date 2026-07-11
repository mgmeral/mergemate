"""
JavaDependencyGraph — directed graph of Java class dependencies.

Edge A -> B means "A uses B" (A references/imports B).
Reverse edge B -> A (B has A as dependent).

Used to find test classes that transitively depend on a production class.
"""
from __future__ import annotations

from collections import deque

from mergemate.domain.models import JavaClassInfo


class JavaDependencyGraph:
    """
    Directed graph of Java class dependencies.
    Edge A -> B means "A uses B" (A references B).
    Reverse edge B -> A means "A is a dependent of B".
    """

    def __init__(self, classes: list[JavaClassInfo]):
        self._by_simple: dict[str, list[JavaClassInfo]] = {}
        self._by_qualified: dict[str, JavaClassInfo] = {}
        # qualified_name -> set of qualified names that use it (dependents)
        self._dependents: dict[str, set[str]] = {}
        # qualified_name -> set of qualified names it uses (dependencies)
        self._dependencies: dict[str, set[str]] = {}
        self._build(classes)

    def _build(self, classes: list[JavaClassInfo]) -> None:
        """Build indexes and edges from class list."""
        # Build name indexes
        for cls in classes:
            qn = cls.qualified_name
            self._by_qualified[qn] = cls
            sn = cls.class_name
            if sn not in self._by_simple:
                self._by_simple[sn] = []
            if cls not in self._by_simple[sn]:
                self._by_simple[sn].append(cls)

        # Initialize edge sets
        for cls in classes:
            qn = cls.qualified_name
            if qn not in self._dependents:
                self._dependents[qn] = set()
            if qn not in self._dependencies:
                self._dependencies[qn] = set()

        # Build edges: for each class, look at imports, extends, implements, referenced_types
        for cls in classes:
            src_qn = cls.qualified_name

            # Resolve targets from imports
            for imp in cls.imports:
                target = self._resolve(imp)
                if target is not None and target.qualified_name != src_qn:
                    tgt_qn = target.qualified_name
                    self._dependencies[src_qn].add(tgt_qn)
                    self._dependents[tgt_qn].add(src_qn)

            # Resolve targets from extends (simple names)
            for ext_name in cls.extends:
                target = self._resolve_name(ext_name)
                if target is not None and target.qualified_name != src_qn:
                    tgt_qn = target.qualified_name
                    self._dependencies[src_qn].add(tgt_qn)
                    self._dependents[tgt_qn].add(src_qn)

            # Resolve targets from implements (simple names)
            for impl_name in cls.implements:
                target = self._resolve_name(impl_name)
                if target is not None and target.qualified_name != src_qn:
                    tgt_qn = target.qualified_name
                    self._dependencies[src_qn].add(tgt_qn)
                    self._dependents[tgt_qn].add(src_qn)

            # Resolve targets from referenced_types (simple names)
            for ref_type in cls.referenced_types:
                target = self._resolve_name(ref_type)
                if target is not None and target.qualified_name != src_qn:
                    tgt_qn = target.qualified_name
                    self._dependencies[src_qn].add(tgt_qn)
                    self._dependents[tgt_qn].add(src_qn)

    def _resolve(self, name: str) -> JavaClassInfo | None:
        """Resolve an import path or qualified name to a JavaClassInfo."""
        # Try exact qualified name match first
        if name in self._by_qualified:
            return self._by_qualified[name]
        # Try simple name match
        return self._resolve_name(name.split(".")[-1] if "." in name else name)

    def _resolve_name(self, simple_name: str) -> JavaClassInfo | None:
        """Resolve a simple class name to a JavaClassInfo (first match)."""
        candidates = self._by_simple.get(simple_name, [])
        if candidates:
            return candidates[0]
        return None

    def dependents_of(self, class_name: str, max_depth: int = 3) -> list[JavaClassInfo]:
        """
        BFS: find all classes that transitively depend on class_name.
        class_name can be simple or qualified.
        Returns JavaClassInfo objects (not the queried class itself).
        """
        # Find the root class
        root = self.find_class(class_name)
        if root is None:
            return []

        root_qn = root.qualified_name
        visited: set[str] = {root_qn}
        result: list[JavaClassInfo] = []
        queue: deque[tuple[str, int]] = deque([(root_qn, 0)])

        while queue:
            current_qn, depth = queue.popleft()
            if depth >= max_depth:
                continue
            for dep_qn in self._dependents.get(current_qn, set()):
                if dep_qn not in visited:
                    visited.add(dep_qn)
                    dep_cls = self._by_qualified.get(dep_qn)
                    if dep_cls is not None:
                        result.append(dep_cls)
                        queue.append((dep_qn, depth + 1))

        return result

    def dependencies_of(self, class_name: str) -> list[JavaClassInfo]:
        """Return classes that class_name directly depends on."""
        cls = self.find_class(class_name)
        if cls is None:
            return []
        result = []
        for dep_qn in self._dependencies.get(cls.qualified_name, set()):
            dep_cls = self._by_qualified.get(dep_qn)
            if dep_cls is not None:
                result.append(dep_cls)
        return result

    def find_class(self, name: str) -> JavaClassInfo | None:
        """Find by simple or qualified name. Returns first match for simple names."""
        if name in self._by_qualified:
            return self._by_qualified[name]
        candidates = self._by_simple.get(name, [])
        if candidates:
            return candidates[0]
        return None

    def all_classes(self) -> list[JavaClassInfo]:
        return list(self._by_qualified.values())
