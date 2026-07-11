from __future__ import annotations
from dataclasses import dataclass, field
from typing import Literal, Optional


@dataclass
class ChangedFile:
    path: str          # relative to repo root
    status: Literal["added", "modified", "deleted", "renamed", "copied"]
    old_path: Optional[str] = None   # for renames


@dataclass
class GitChangeSet:
    source_ref: str
    target_ref: str
    merge_base: str
    changed_files: list[ChangedFile] = field(default_factory=list)

    # Categorised subsets (populated by classifiers)
    java_production_files: list[ChangedFile] = field(default_factory=list)
    java_test_files: list[ChangedFile] = field(default_factory=list)
    pom_files: list[ChangedFile] = field(default_factory=list)
    config_files: list[ChangedFile] = field(default_factory=list)
    migration_files: list[ChangedFile] = field(default_factory=list)


@dataclass
class MavenModule:
    artifact_id: str
    group_id: str
    version: str
    packaging: str         # jar, war, pom
    relative_path: str     # relative to repo root, e.g. "services/order-service"
    pom_path: str          # absolute path to pom.xml
    dependencies: list[str] = field(default_factory=list)  # artifactIds of internal deps
    submodule_dirs: list[str] = field(default_factory=list)
    has_modules: bool = False
    has_dependency_management: bool = False


@dataclass
class MavenProject:
    root_pom: str          # absolute path
    root_dir: str          # absolute path of project root
    modules: dict[str, MavenModule] = field(default_factory=dict)  # artifactId -> MavenModule
    active_profiles: list[str] = field(default_factory=list)


@dataclass
class JdkRequirement:
    required_version: Optional[str]     # e.g. "17"
    detected_from: Optional[str]        # e.g. "root pom.xml -> maven.compiler.release"
    detection_method: Optional[str]     # "property", "compiler-plugin", "effective-pom", "none"


@dataclass
class JdkRuntime:
    java_version: str       # e.g. "17.0.12"
    java_major: int         # e.g. 17
    java_home: Optional[str]
    maven_version: str      # e.g. "3.9.6"
    source: str             # "mvn -version output"


@dataclass
class JdkCompatibility:
    requirement: JdkRequirement
    runtime: JdkRuntime
    compatible: bool
    message: str            # human-readable compatibility message


@dataclass
class ModuleImpact:
    artifact_id: str
    label: Literal["changed", "dependent", "dependency"]
    reason: str


@dataclass
class ImpactAnalysis:
    strategy: Literal["full", "incremental"]
    strategy_reason: str
    changed_modules: list[str]
    affected_modules: list[ModuleImpact]   # all modules in the plan
    risk_level: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
    risk_reasons: list[str]
    full_build_recommended: bool
    jdk_compatibility: Optional[JdkCompatibility] = None


@dataclass
class MavenCommand:
    argv: list[str]
    display_command: str    # human-readable version for printing
    goal: str               # "test", "compile", "verify"


@dataclass
class ValidationPlan:
    impact: ImpactAnalysis
    maven_command: Optional[MavenCommand]   # None for analyze-only
    profile: str           # "analyze", "test", "compile", "verify", "full"
