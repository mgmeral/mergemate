import subprocess
import re
import os
import xml.etree.ElementTree as ET
from mergemate.domain.models import JdkRequirement, JdkRuntime, JdkCompatibility

# Maven POM XML namespace
_MVN_NS = "http://maven.apache.org/POM/4.0.0"


def _ns(tag: str) -> str:
    """Return tag with Maven namespace."""
    return f"{{{_MVN_NS}}}{tag}"


def _find_element(parent: ET.Element, tag: str) -> ET.Element | None:
    """Find a child element trying both namespaced and plain tag."""
    el = parent.find(_ns(tag))
    if el is not None:
        return el
    return parent.find(tag)


def _find_all_elements(root: ET.Element, tag: str) -> list[ET.Element]:
    """Find all descendant elements with the given tag (ns and plain)."""
    results = list(root.iter(_ns(tag)))
    # Also try plain (without ns) to handle non-namespaced POMs
    plain = list(root.iter(tag))
    # Merge without duplicates (identity check)
    seen_ids = {id(el) for el in results}
    for el in plain:
        if id(el) not in seen_ids:
            results.append(el)
            seen_ids.add(id(el))
    return results


# ---------------------------------------------------------------------------
# JDK Requirement Detection
# ---------------------------------------------------------------------------

def detect_jdk_requirement(root_pom_path: str) -> JdkRequirement:
    """
    Detect required JDK version from POM files.

    Priority (first match wins):
    1. maven.compiler.release property in root POM
    2. maven-compiler-plugin <release> configuration
    3. java.version property
    4. jdk.version property
    5. maven.compiler.source property
    6. maven-compiler-plugin <source> configuration
    7. maven-compiler-plugin <target> configuration
    8. Parent POM (follow relativePath)
    9. If none found: JdkRequirement(required_version=None, detected_from=None, detection_method="none")
    """
    result = _parse_pom_for_jdk(root_pom_path)
    if result is not None:
        return result

    # Follow parent POM
    parent_pom_path = _get_parent_pom_path(root_pom_path)
    if parent_pom_path is not None and os.path.isfile(parent_pom_path):
        result = _parse_pom_for_jdk(parent_pom_path)
        if result is not None:
            return result

    return JdkRequirement(
        required_version=None,
        detected_from=None,
        detection_method="none",
    )


def _parse_pom_for_jdk(pom_path: str) -> JdkRequirement | None:
    """
    Parse a single POM file for JDK version indicators.
    Returns JdkRequirement if found, None otherwise.
    """
    try:
        tree = ET.parse(pom_path)
    except (ET.ParseError, FileNotFoundError, OSError):
        return None

    root = tree.getroot()

    # Helper to find properties element and get a named property
    def get_property(name: str) -> str | None:
        properties = _find_element(root, "properties")
        if properties is None:
            return None
        child = _find_element(properties, name)
        if child is not None and child.text:
            return child.text.strip()
        return None

    # 1. maven.compiler.release property
    value = get_property("maven.compiler.release")
    if value:
        return JdkRequirement(
            required_version=value,
            detected_from=f"{pom_path} -> maven.compiler.release",
            detection_method="property",
        )

    # 2. maven-compiler-plugin <release> configuration
    compiler_release = _find_compiler_plugin_config(root, "release")
    if compiler_release:
        return JdkRequirement(
            required_version=compiler_release,
            detected_from=f"{pom_path} -> maven-compiler-plugin <release>",
            detection_method="compiler-plugin",
        )

    # 3. java.version property
    value = get_property("java.version")
    if value:
        return JdkRequirement(
            required_version=value,
            detected_from=f"{pom_path} -> java.version",
            detection_method="property",
        )

    # 4. jdk.version property
    value = get_property("jdk.version")
    if value:
        return JdkRequirement(
            required_version=value,
            detected_from=f"{pom_path} -> jdk.version",
            detection_method="property",
        )

    # 5. maven.compiler.source property
    value = get_property("maven.compiler.source")
    if value:
        return JdkRequirement(
            required_version=value,
            detected_from=f"{pom_path} -> maven.compiler.source",
            detection_method="property",
        )

    # 6. maven-compiler-plugin <source> configuration
    compiler_source = _find_compiler_plugin_config(root, "source")
    if compiler_source:
        return JdkRequirement(
            required_version=compiler_source,
            detected_from=f"{pom_path} -> maven-compiler-plugin <source>",
            detection_method="compiler-plugin",
        )

    # 7. maven-compiler-plugin <target> configuration
    compiler_target = _find_compiler_plugin_config(root, "target")
    if compiler_target:
        return JdkRequirement(
            required_version=compiler_target,
            detected_from=f"{pom_path} -> maven-compiler-plugin <target>",
            detection_method="compiler-plugin",
        )

    return None


def _find_compiler_plugin_config(root: ET.Element, config_key: str) -> str | None:
    """Find a configuration key in maven-compiler-plugin."""
    # Search in all plugin elements (handles build/plugins and pluginManagement/plugins)
    for plugin in _find_all_elements(root, "plugin"):
        artifact_id_el = _find_element(plugin, "artifactId")
        if artifact_id_el is None or artifact_id_el.text != "maven-compiler-plugin":
            continue
        # Find configuration/config_key
        config = _find_element(plugin, "configuration")
        if config is not None:
            key_el = _find_element(config, config_key)
            if key_el is not None and key_el.text:
                return key_el.text.strip()
        # Also check executions/execution/configuration
        for execution in _find_all_elements(plugin, "execution"):
            exec_config = _find_element(execution, "configuration")
            if exec_config is not None:
                key_el = _find_element(exec_config, config_key)
                if key_el is not None and key_el.text:
                    return key_el.text.strip()
    return None


def _get_parent_pom_path(pom_path: str) -> str | None:
    """
    Given a POM file, find the parent POM path.
    Uses <relativePath> if present, defaults to ../pom.xml.
    Returns absolute path if the file exists, None otherwise.
    """
    try:
        tree = ET.parse(pom_path)
    except (ET.ParseError, FileNotFoundError, OSError):
        return None

    root = tree.getroot()
    parent = _find_element(root, "parent")
    if parent is None:
        return None

    pom_dir = os.path.dirname(os.path.abspath(pom_path))

    relative_path_el = _find_element(parent, "relativePath")
    if relative_path_el is not None and relative_path_el.text:
        relative_path = relative_path_el.text.strip()
        if relative_path == "":
            return None
        candidate = os.path.normpath(os.path.join(pom_dir, relative_path))
        # If it's a directory, append pom.xml
        if os.path.isdir(candidate):
            candidate = os.path.join(candidate, "pom.xml")
        if os.path.isfile(candidate):
            return candidate
        return None

    # Default: ../pom.xml
    candidate = os.path.normpath(os.path.join(pom_dir, "..", "pom.xml"))
    if os.path.isfile(candidate):
        return candidate
    return None


# ---------------------------------------------------------------------------
# Maven Runtime JDK Detection
# ---------------------------------------------------------------------------

def detect_maven_runtime(maven_executable: str = "mvn") -> JdkRuntime:
    """
    Run `<maven_executable> -version` and parse:
    - Java version
    - JAVA_HOME (if shown)
    - Maven version

    Example `mvn -version` output:
        Apache Maven 3.9.6 (...)
        Maven home: /opt/maven
        Java version: 17.0.12, vendor: Eclipse Adoptium, runtime: /opt/jdk-17
        Default locale: en_US, platform encoding: UTF-8
        OS name: "linux", version: "5.15", arch: "amd64", family: "unix"

    Returns JdkRuntime.
    """
    result = subprocess.run(
        [maven_executable, "-version"],
        capture_output=True,
        text=True,
    )
    # mvn -version writes to stdout on some versions, stderr on others
    output = result.stdout + result.stderr

    maven_version = _parse_maven_version(output)
    java_version, java_major = _parse_java_version(output)
    java_home = _parse_java_home(output)

    return JdkRuntime(
        java_version=java_version,
        java_major=java_major,
        java_home=java_home,
        maven_version=maven_version,
        source="mvn -version output",
    )


def _parse_maven_version(output: str) -> str:
    """Extract Maven version from output."""
    match = re.search(r"Apache Maven\s+([\d.]+)", output)
    if match:
        return match.group(1)
    return "unknown"


def _parse_java_version(output: str) -> tuple[str, int]:
    """Extract Java version and major from output."""
    # Format: "Java version: 17.0.12, vendor: ..."
    match = re.search(r"Java version:\s*([\d.]+)", output)
    if match:
        java_version = match.group(1)
        major = _extract_major_version(java_version)
        return java_version, major

    # Fallback: "java version "11.0.2""
    match = re.search(r'java version\s+"([\d._]+)"', output, re.IGNORECASE)
    if match:
        java_version = match.group(1)
        major = _extract_major_version(java_version)
        return java_version, major

    return "unknown", 0


def _extract_major_version(version_str: str) -> int:
    """Extract major version number from version string like '17.0.12' or '1.8.0_292'."""
    parts = version_str.split(".")
    if not parts:
        return 0
    try:
        first = int(parts[0])
        # Old format: 1.8.x -> major is 8
        if first == 1 and len(parts) > 1:
            return int(parts[1])
        return first
    except ValueError:
        return 0


def _parse_java_home(output: str) -> str | None:
    """Extract JAVA_HOME from mvn output."""
    # Format: "Java home: /opt/jdk-17"  or "runtime: /opt/jdk-17"
    match = re.search(r"Java home:\s*(.+)", output)
    if match:
        return match.group(1).strip()
    match = re.search(r"runtime:\s*(.+?)(?:,|$)", output)
    if match:
        return match.group(1).strip()
    return None


def check_jdk_compatibility(
    requirement: JdkRequirement,
    runtime: JdkRuntime,
    allow_newer_major: bool = True,
) -> JdkCompatibility:
    """
    Compare required vs active JDK.

    If requirement.required_version is None: compatible=True, message="No JDK version requirement found"
    If major versions match: compatible=True
    If runtime is newer AND allow_newer_major=True: compatible=True with warning
    Otherwise: compatible=False with clear error message
    """
    if requirement.required_version is None:
        return JdkCompatibility(
            requirement=requirement,
            runtime=runtime,
            compatible=True,
            message="No JDK version requirement found",
        )

    required_major = _extract_major_version(requirement.required_version)
    runtime_major = runtime.java_major

    if required_major == runtime_major:
        return JdkCompatibility(
            requirement=requirement,
            runtime=runtime,
            compatible=True,
            message=f"JDK version compatible: required {required_major}, runtime {runtime_major}",
        )

    if runtime_major > required_major and allow_newer_major:
        return JdkCompatibility(
            requirement=requirement,
            runtime=runtime,
            compatible=True,
            message=(
                f"Runtime JDK {runtime_major} is newer than required JDK {required_major}. "
                f"Proceeding (allow_newer_major=True)."
            ),
        )

    return JdkCompatibility(
        requirement=requirement,
        runtime=runtime,
        compatible=False,
        message=(
            f"Project requires JDK {required_major} but Maven is running with JDK {runtime_major}."
        ),
    )


def format_incompatibility_error(compat: JdkCompatibility) -> str:
    """
    Format a human-readable error.
    """
    req = compat.requirement
    rt = compat.runtime
    required_major = _extract_major_version(req.required_version) if req.required_version else "unknown"
    runtime_major = rt.java_major

    lines = [
        f"Project requires JDK {required_major} but Maven is running with JDK {runtime_major}.",
        "",
    ]

    if req.detected_from:
        lines.append("Detected from:")
        lines.append(f"  {req.detected_from}")
        lines.append("")

    lines.append("Current Maven runtime:")
    lines.append(f"  Java {rt.java_version}")
    if rt.java_home:
        lines.append(f"  JAVA_HOME={rt.java_home}")
    lines.append("")
    lines.append("Configure JAVA_HOME or Maven Toolchains before running validation.")

    return "\n".join(lines)
