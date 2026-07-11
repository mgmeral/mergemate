"""
Maven project loader — discovers all modules from a root pom.xml.
Independent of forge_planner; uses MavenModule from mergemate.domain.models.
"""
from __future__ import annotations

import os
import xml.etree.ElementTree as ET
from mergemate.domain.models import MavenModule, MavenProject

# Maven POM XML namespace
_MVN_NS = "http://maven.apache.org/POM/4.0.0"


def _ns(tag: str) -> str:
    return f"{{{_MVN_NS}}}{tag}"


def _find(parent: ET.Element, tag: str) -> ET.Element | None:
    el = parent.find(_ns(tag))
    if el is not None:
        return el
    return parent.find(tag)


def _find_all(root: ET.Element, path: str) -> list[ET.Element]:
    """Find all elements matching path, trying namespaced and plain."""
    ns_parts = [_ns(p) for p in path.split("/")]
    ns_path = "/".join(ns_parts)
    results = root.findall(ns_path)
    plain_results = root.findall(path)
    seen = {id(el) for el in results}
    for el in plain_results:
        if id(el) not in seen:
            results.append(el)
            seen.add(id(el))
    return results


def _text(el: ET.Element | None) -> str | None:
    if el is not None and el.text:
        return el.text.strip()
    return None


def load_project(
    root_pom_path: str,
    active_profiles: list[str] | None = None,
) -> MavenProject:
    """
    Recursively discover all Maven modules starting from root_pom_path.
    Populates MavenProject.modules dict (artifactId → MavenModule).

    Rules:
    - Read artifactId, groupId, version, packaging from each pom.xml
    - Resolve groupId/version from <parent> when not explicitly set in child
    - Follow <modules> recursively
    - Also follow modules inside <profiles> when profile is active
      (activeByDefault=true OR profile id in active_profiles list)
    - Keep only reactor-internal dependency edges in MavenModule.dependencies
    """
    active_profiles = active_profiles or []
    root_pom_path = os.path.abspath(root_pom_path)
    root_dir = os.path.dirname(root_pom_path)

    project = MavenProject(
        root_pom=root_pom_path,
        root_dir=root_dir,
        modules={},
        active_profiles=list(active_profiles),
    )

    # First pass: collect all modules
    _collect_modules(root_pom_path, root_dir, project, active_profiles, parent_info=None)

    # Second pass: filter dependencies to only reactor-internal ones
    known_artifact_ids = set(project.modules.keys())
    for module in project.modules.values():
        module.dependencies = [
            dep for dep in module.dependencies
            if dep in known_artifact_ids
        ]

    return project


def _collect_modules(
    pom_path: str,
    project_root: str,
    project: MavenProject,
    active_profiles: list[str],
    parent_info: dict | None,
) -> None:
    """Recursively collect MavenModule entries from pom_path."""
    try:
        tree = ET.parse(pom_path)
    except (ET.ParseError, FileNotFoundError, OSError):
        return

    root = tree.getroot()
    pom_dir = os.path.dirname(pom_path)

    # Extract parent info (for inheriting groupId/version)
    parent_el = _find(root, "parent")
    parent_group_id = None
    parent_version = None
    if parent_el is not None:
        parent_group_id = _text(_find(parent_el, "groupId"))
        parent_version = _text(_find(parent_el, "version"))

    # Read artifact coordinates
    artifact_id = _text(_find(root, "artifactId")) or os.path.basename(pom_dir)
    group_id = _text(_find(root, "groupId")) or parent_group_id or ""
    version = _text(_find(root, "version")) or parent_version or ""
    packaging = _text(_find(root, "packaging")) or "jar"

    # Compute relative_path from project root
    rel_path = os.path.relpath(pom_dir, project_root).replace("\\", "/")
    if rel_path == ".":
        rel_path = ""

    # Check for has_modules and has_dependency_management
    has_modules_flag = False
    has_dep_mgmt = _find(root, "dependencyManagement") is not None

    # Collect direct sub-module dirs from <modules>
    submodule_dirs: list[str] = []
    modules_el = _find(root, "modules")
    if modules_el is not None:
        for mod_el in list(modules_el):
            if mod_el.text:
                mod_name = mod_el.text.strip()
                submodule_dirs.append(mod_name)
                has_modules_flag = True

    # Profile modules
    profiles_el = _find(root, "profiles")
    if profiles_el is not None:
        for profile_el in list(profiles_el):
            if _is_profile_active(profile_el, active_profiles):
                profile_modules_el = _find(profile_el, "modules")
                if profile_modules_el is not None:
                    for mod_el in list(profile_modules_el):
                        if mod_el.text:
                            mod_name = mod_el.text.strip()
                            if mod_name not in submodule_dirs:
                                submodule_dirs.append(mod_name)
                            has_modules_flag = True

    # Collect all raw dependency artifactIds (will be filtered later)
    raw_deps: list[str] = []
    dependencies_el = _find(root, "dependencies")
    if dependencies_el is not None:
        for dep_el in list(dependencies_el):
            dep_artifact = _text(_find(dep_el, "artifactId"))
            if dep_artifact:
                raw_deps.append(dep_artifact)

    module = MavenModule(
        artifact_id=artifact_id,
        group_id=group_id,
        version=version,
        packaging=packaging,
        relative_path=rel_path,
        pom_path=pom_path,
        dependencies=list(raw_deps),
        submodule_dirs=list(submodule_dirs),
        has_modules=has_modules_flag,
        has_dependency_management=has_dep_mgmt,
    )

    project.modules[artifact_id] = module

    # Recurse into sub-modules
    for mod_name in submodule_dirs:
        child_dir = os.path.join(pom_dir, mod_name)
        child_pom = os.path.join(child_dir, "pom.xml")
        if os.path.isfile(child_pom):
            _collect_modules(child_pom, project_root, project, active_profiles, parent_info={
                "group_id": group_id,
                "version": version,
                "artifact_id": artifact_id,
            })


def _is_profile_active(profile_el: ET.Element, active_profiles: list[str]) -> bool:
    """Return True if profile should be activated."""
    profile_id_el = _find(profile_el, "id")
    profile_id = _text(profile_id_el) or ""

    # Check if id is in active_profiles list
    if profile_id in active_profiles:
        return True

    # Check activeByDefault
    activation_el = _find(profile_el, "activation")
    if activation_el is not None:
        active_by_default_el = _find(activation_el, "activeByDefault")
        if active_by_default_el is not None:
            val = (_text(active_by_default_el) or "").lower()
            if val == "true":
                return True

    return False
