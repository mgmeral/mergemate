"""
pom_parser.py

Parses Maven POM files to discover the reactor structure.

Responsibilities:
- Recursively discover modules via <modules> elements from the root pom.xml
- Read artifactId, groupId, version, packaging, dependencies for each module
- Resolve groupId/version from <parent> when not explicitly set
- Include modules declared inside <profiles> when the profile is active
  (activeByDefault=true, or profile id is in the explicit active_profiles list)
- Does NOT evaluate property-based or OS-based profile activation
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional
import xml.etree.ElementTree as ET

# Maven POM namespace
_NS = "http://maven.apache.org/POM/4.0.0"


def _tag(local: str) -> str:
    """Return namespace-qualified tag name."""
    return f"{{{_NS}}}{local}"


def _find_text(element: ET.Element, tag: str) -> Optional[str]:
    """Find a direct child element and return its text, or None."""
    child = element.find(_tag(tag))
    if child is not None and child.text:
        return child.text.strip()
    return None


@dataclass
class Dependency:
    group_id: str
    artifact_id: str
    version: Optional[str] = None
    scope: Optional[str] = None


@dataclass
class ModuleInfo:
    """All relevant information parsed from a single POM file."""
    artifact_id: str
    group_id: str
    version: str
    packaging: str                          # jar, war, pom, …
    directory: str                          # absolute path of the module directory
    pom_path: str                           # absolute path to this pom.xml
    dependencies: list[Dependency] = field(default_factory=list)
    # Sub-module directory names (relative to this module's dir)
    submodule_dirs: list[str] = field(default_factory=list)
    # Whether this POM is an aggregator (has <modules>) or has <dependencyManagement>
    has_modules: bool = False
    has_dependency_management: bool = False


def _is_profile_active(
    profile_element: ET.Element,
    active_profiles: list[str],
) -> bool:
    """
    Determine whether a profile element should be considered active.

    A profile is active if:
    - Its id is explicitly listed in active_profiles, OR
    - It has <activation><activeByDefault>true</activeByDefault></activation>

    Property-based and OS-based activation are NOT evaluated.
    """
    profile_id_el = profile_element.find(_tag("id"))
    profile_id = profile_id_el.text.strip() if (profile_id_el is not None and profile_id_el.text) else ""

    # Explicitly activated
    if profile_id in active_profiles:
        return True

    # activeByDefault
    activation = profile_element.find(_tag("activation"))
    if activation is not None:
        abd = activation.find(_tag("activeByDefault"))
        if abd is not None and abd.text and abd.text.strip().lower() == "true":
            return True

    return False


def parse_pom(pom_path: str, active_profiles: list[str] | None = None) -> ModuleInfo:
    """
    Parse a single pom.xml file and return a ModuleInfo.

    Parent groupId/version are used as fallback if the POM doesn't declare its own.
    """
    if active_profiles is None:
        active_profiles = []

    tree = ET.parse(pom_path)
    root = tree.getroot()
    module_dir = os.path.dirname(os.path.abspath(pom_path))

    # --- groupId / version: may be inherited from <parent> ---
    parent_el = root.find(_tag("parent"))
    parent_group_id = ""
    parent_version = ""
    if parent_el is not None:
        parent_group_id = _find_text(parent_el, "groupId") or ""
        parent_version = _find_text(parent_el, "version") or ""

    artifact_id = _find_text(root, "artifactId") or ""
    group_id = _find_text(root, "groupId") or parent_group_id
    version = _find_text(root, "version") or parent_version
    packaging = _find_text(root, "packaging") or "jar"

    # --- Direct module declarations ---
    submodule_dirs: list[str] = []
    modules_el = root.find(_tag("modules"))
    has_modules = modules_el is not None and len(list(modules_el)) > 0
    if modules_el is not None:
        for mod_el in modules_el.findall(_tag("module")):
            if mod_el.text:
                submodule_dirs.append(mod_el.text.strip())

    # --- Profile module declarations ---
    profiles_el = root.find(_tag("profiles"))
    if profiles_el is not None:
        for profile_el in profiles_el.findall(_tag("profile")):
            if _is_profile_active(profile_el, active_profiles):
                profile_modules_el = profile_el.find(_tag("modules"))
                if profile_modules_el is not None:
                    for mod_el in profile_modules_el.findall(_tag("module")):
                        if mod_el.text:
                            mod_name = mod_el.text.strip()
                            if mod_name not in submodule_dirs:
                                submodule_dirs.append(mod_name)

    # --- Dependencies ---
    dependencies: list[Dependency] = []
    deps_el = root.find(_tag("dependencies"))
    if deps_el is not None:
        for dep_el in deps_el.findall(_tag("dependency")):
            dep_group = _find_text(dep_el, "groupId") or ""
            dep_artifact = _find_text(dep_el, "artifactId") or ""
            dep_version = _find_text(dep_el, "version")
            dep_scope = _find_text(dep_el, "scope")
            if dep_artifact:
                dependencies.append(Dependency(dep_group, dep_artifact, dep_version, dep_scope))

    # --- dependencyManagement presence ---
    has_dm = root.find(_tag("dependencyManagement")) is not None

    return ModuleInfo(
        artifact_id=artifact_id,
        group_id=group_id,
        version=version,
        packaging=packaging,
        directory=module_dir,
        pom_path=os.path.abspath(pom_path),
        dependencies=dependencies,
        submodule_dirs=submodule_dirs,
        has_modules=has_modules or len(submodule_dirs) > 0,
        has_dependency_management=has_dm,
    )


def discover_reactor(
    root_pom: str,
    active_profiles: list[str] | None = None,
) -> dict[str, ModuleInfo]:
    """
    Recursively discover all modules in the Maven reactor starting from root_pom.

    Returns a dict mapping artifactId → ModuleInfo for every module found,
    including the root aggregator itself.

    active_profiles: list of profile ids to treat as active (in addition to
    profiles with activeByDefault=true).
    """
    if active_profiles is None:
        active_profiles = []

    visited: dict[str, ModuleInfo] = {}  # artifactId → ModuleInfo
    queue: list[str] = [os.path.abspath(root_pom)]

    while queue:
        pom_path = queue.pop(0)
        if not os.path.isfile(pom_path):
            continue

        info = parse_pom(pom_path, active_profiles)

        # Avoid processing the same module twice (by pom_path)
        if any(m.pom_path == info.pom_path for m in visited.values()):
            continue

        visited[info.artifact_id] = info

        # Enqueue children
        for sub_dir in info.submodule_dirs:
            child_pom = os.path.join(info.directory, sub_dir, "pom.xml")
            child_pom = os.path.abspath(child_pom)
            if os.path.isfile(child_pom):
                queue.append(child_pom)

    return visited
