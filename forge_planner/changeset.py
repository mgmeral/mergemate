"""
changeset.py

Maps a list of changed file paths to the owning Maven modules.

Rules:
- A file belongs to the module whose directory is its deepest ancestor.
- Files that are not under any module directory (other than the reactor root)
  are assigned to a special "_root_" sentinel, indicating a global/root scope
  change (e.g., the root pom.xml itself).
"""

from __future__ import annotations

import os

from forge_planner.pom_parser import ModuleInfo

# Sentinel key used to represent root/global changes
ROOT_SENTINEL = "_root_"


def map_files_to_modules(
    changed_files: list[str],
    modules: dict[str, ModuleInfo],
    repo_root: str,
) -> dict[str, set[str]]:
    """
    Map each changed file to the artifact_id of its owning module.

    A file "belongs" to the module whose directory is the deepest (longest)
    ancestor path of the file.  If no module directory qualifies (other than
    the repo root), the file is assigned to ROOT_SENTINEL.

    Parameters
    ----------
    changed_files : list[str]
        List of file paths (absolute or relative to repo_root).
    modules : dict[str, ModuleInfo]
        Reactor modules as returned by pom_parser.discover_reactor().
    repo_root : str
        Absolute path to the repository root.

    Returns
    -------
    dict[str, set[str]]
        Mapping of artifact_id (or ROOT_SENTINEL) → set of changed file paths
        belonging to that module.
    """
    repo_root = os.path.abspath(repo_root)

    # Build a lookup: directory (normalized, absolute) → artifact_id
    # Sort by path depth (longest first) so deepest wins
    dir_to_module: list[tuple[str, str]] = []
    for artifact_id, info in modules.items():
        mod_dir = os.path.abspath(info.directory)
        dir_to_module.append((mod_dir, artifact_id))

    # Sort longest path first (deepest ancestor wins)
    dir_to_module.sort(key=lambda x: len(x[0]), reverse=True)

    result: dict[str, set[str]] = {}

    for file_path in changed_files:
        # Normalize to absolute path
        if not os.path.isabs(file_path):
            file_path = os.path.join(repo_root, file_path)
        file_path = os.path.normpath(file_path)

        owner = ROOT_SENTINEL
        for mod_dir, artifact_id in dir_to_module:
            # Check if file_path is inside mod_dir (but not equal to it)
            # Use os.path.commonpath for robust comparison
            try:
                rel = os.path.relpath(file_path, mod_dir)
                # If rel doesn't start with '..', it's inside mod_dir
                if not rel.startswith(".."):
                    owner = artifact_id
                    break
            except ValueError:
                # On Windows, relpath raises ValueError across drives
                continue

        result.setdefault(owner, set()).add(file_path)

    return result


def changed_module_ids(
    changed_files: list[str],
    modules: dict[str, ModuleInfo],
    repo_root: str,
) -> tuple[set[str], bool]:
    """
    Return the set of changed module artifact_ids and a flag indicating
    whether a global (root/aggregator) change was detected.

    Parameters
    ----------
    changed_files : list[str]
        List of changed file paths (absolute or relative to repo_root).
    modules : dict[str, ModuleInfo]
        Reactor modules.
    repo_root : str
        Absolute repo root path.

    Returns
    -------
    (changed_ids, is_global_change)
        changed_ids: set of artifact_ids of modules that own changed files.
                     Does NOT include ROOT_SENTINEL.
        is_global_change: True if any file maps to ROOT_SENTINEL (root-level
                          files), or if any changed module is an aggregator POM
                          (packaging=pom with submodules) or has dependencyManagement.
    """
    mapping = map_files_to_modules(changed_files, modules, repo_root)

    changed_ids: set[str] = set()
    is_global = ROOT_SENTINEL in mapping

    for owner, files in mapping.items():
        if owner == ROOT_SENTINEL:
            continue
        changed_ids.add(owner)

    # Also check if any changed module is itself an aggregator/BOM POM
    if not is_global:
        for aid in changed_ids:
            info = modules.get(aid)
            if info and info.packaging == "pom" and (info.has_modules or info.has_dependency_management):
                is_global = True
                break

    return changed_ids, is_global
