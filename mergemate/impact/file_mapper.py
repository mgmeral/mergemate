"""
File-to-module mapper: maps changed files to their owning Maven module.
"""
from __future__ import annotations

import os
from mergemate.domain.models import ChangedFile, MavenProject, MavenModule


def _normalize(path: str) -> str:
    """Normalize path separators to forward slashes."""
    return path.replace("\\", "/")


def map_file_to_module(
    file_path: str,
    project: MavenProject,
) -> MavenModule | None:
    """
    Find the deepest Maven module that owns this file.

    "Deepest" means the module whose relative_path is the longest prefix of file_path.

    file_path: path relative to project root (as returned by git diff --name-status)
    Returns None if the file doesn't belong to any known module.
    """
    norm_file = _normalize(file_path)

    best_module: MavenModule | None = None
    best_depth: int = -1

    for module in project.modules.values():
        rel = _normalize(module.relative_path)
        if rel == "" or rel == ".":
            # root module — matches everything with depth 0
            depth = 0
            if depth > best_depth:
                best_depth = depth
                best_module = module
        else:
            # module relative path must be a prefix of the file path
            prefix = rel if rel.endswith("/") else rel + "/"
            if norm_file.startswith(prefix) or norm_file == rel:
                # depth = number of path components in rel
                depth = len(rel.split("/"))
                if depth > best_depth:
                    best_depth = depth
                    best_module = module

    return best_module


def map_changeset_to_modules(
    changed_files: list[ChangedFile],
    project: MavenProject,
) -> dict[str, list[ChangedFile]]:
    """
    Map all changed files to their owning modules.
    Returns: {artifact_id -> [ChangedFile, ...]}
    Files with no owner are mapped to key "" (empty string).
    """
    result: dict[str, list[ChangedFile]] = {}

    for cf in changed_files:
        module = map_file_to_module(cf.path, project)
        if module is not None:
            key = module.artifact_id
        else:
            key = ""
        result.setdefault(key, []).append(cf)

    return result


def is_root_pom_change(changed_files: list[ChangedFile], project: MavenProject) -> bool:
    """Return True if the root pom.xml (or a pom in an aggregator module) was changed."""
    for cf in changed_files:
        norm = _normalize(cf.path)
        filename = norm.split("/")[-1]
        if filename != "pom.xml":
            continue

        # Check if this pom.xml belongs to an aggregator module (has_modules=True)
        module = map_file_to_module(cf.path, project)
        if module is not None:
            if module.has_modules:
                return True
            # Also check if it's the root pom
            if module.relative_path in ("", "."):
                return True
        else:
            # Root-level pom.xml with no owning module
            if norm == "pom.xml":
                return True

    return False
