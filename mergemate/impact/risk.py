"""
Risk rules engine for MergeMate impact analysis.
"""
from __future__ import annotations

import fnmatch
import os

from mergemate.domain.models import GitChangeSet, MavenProject, MavenModule, ChangedFile
from mergemate.config.loader import MergeMateConfig


# ---------------------------------------------------------------------------
# Individual rule checkers
# ---------------------------------------------------------------------------

def _check_root_pom_changed(
    changeset: GitChangeSet,
    project: MavenProject,
    module_file_map: dict[str, list],
    config: MergeMateConfig,
    impact_ratio: float,
) -> bool:
    from mergemate.impact.file_mapper import is_root_pom_change
    return is_root_pom_change(changeset.changed_files, project)


def _check_always_full_build_module(
    changeset: GitChangeSet,
    project: MavenProject,
    module_file_map: dict[str, list],
    config: MergeMateConfig,
    impact_ratio: float,
) -> bool:
    for artifact_id in config.always_full_build_modules:
        if artifact_id in module_file_map and module_file_map[artifact_id]:
            return True
    return False


def _check_full_build_file_patterns(
    changeset: GitChangeSet,
    project: MavenProject,
    module_file_map: dict[str, list],
    config: MergeMateConfig,
    impact_ratio: float,
) -> bool:
    if not config.full_build_file_patterns:
        return False
    for cf in changeset.changed_files:
        if _matches_full_build_patterns(cf.path, config.full_build_file_patterns):
            return True
    return False


def _check_aggregator_bom_pom_changed(
    changeset: GitChangeSet,
    project: MavenProject,
    module_file_map: dict[str, list],
    config: MergeMateConfig,
    impact_ratio: float,
) -> bool:
    """Any aggregator/BOM pom.xml changed (packaging=pom with modules or dependencyManagement)."""
    for cf in changeset.pom_files:
        norm = cf.path.replace("\\", "/")
        # Find the module this pom belongs to
        for module in project.modules.values():
            rel = module.relative_path.replace("\\", "/")
            pom_rel = (rel + "/pom.xml").lstrip("/") if rel else "pom.xml"
            if norm == pom_rel:
                if module.packaging == "pom" and (module.has_modules or module.has_dependency_management):
                    return True
    return False


def _check_application_yml_changed(
    changeset: GitChangeSet,
    project: MavenProject,
    module_file_map: dict[str, list],
    config: MergeMateConfig,
    impact_ratio: float,
) -> bool:
    for cf in changeset.changed_files:
        norm = cf.path.replace("\\", "/").lower()
        filename = norm.split("/")[-1]
        if filename in ("application.yml", "application.yaml", "application.properties"):
            return True
        # Also match application-*.yml patterns
        if filename.startswith("application-") and (filename.endswith(".yml") or filename.endswith(".yaml") or filename.endswith(".properties")):
            return True
    return False


def _check_migration_files_changed(
    changeset: GitChangeSet,
    project: MavenProject,
    module_file_map: dict[str, list],
    config: MergeMateConfig,
    impact_ratio: float,
) -> bool:
    return len(changeset.migration_files) > 0


def _check_spring_config_class_changed(
    changeset: GitChangeSet,
    project: MavenProject,
    module_file_map: dict[str, list],
    config: MergeMateConfig,
    impact_ratio: float,
) -> bool:
    for cf in changeset.java_production_files:
        filename = os.path.basename(cf.path.replace("\\", "/"))
        if filename.endswith("Config.java") or filename.endswith("Configuration.java"):
            return True
    return False


def _check_security_files_changed(
    changeset: GitChangeSet,
    project: MavenProject,
    module_file_map: dict[str, list],
    config: MergeMateConfig,
    impact_ratio: float,
) -> bool:
    for cf in changeset.changed_files:
        norm = cf.path.replace("\\", "/").lower()
        if "/security/" in norm:
            return True
    return False


def _check_impact_ratio_threshold(
    changeset: GitChangeSet,
    project: MavenProject,
    module_file_map: dict[str, list],
    config: MergeMateConfig,
    impact_ratio: float,
) -> bool:
    return impact_ratio >= config.full_build_threshold


# ---------------------------------------------------------------------------
# Risk rules registry
# ---------------------------------------------------------------------------

# Hard rules: always trigger full build when True
HARD_RULES: list[dict] = [
    {
        "name": "root_pom_changed",
        "description": "Root pom.xml or aggregator POM changed",
        "check": _check_root_pom_changed,
    },
    {
        "name": "aggregator_bom_pom_changed",
        "description": "Aggregator or BOM pom.xml changed",
        "check": _check_aggregator_bom_pom_changed,
    },
    {
        "name": "always_full_build_module",
        "description": "A module in always_full_build_modules was changed",
        "check": _check_always_full_build_module,
    },
    {
        "name": "full_build_file_pattern",
        "description": "A file matching full_build_file_patterns was changed",
        "check": _check_full_build_file_patterns,
    },
]

# Soft rules: increase risk level but don't force full build alone
SOFT_RULES: list[dict] = [
    {
        "name": "application_yml_changed",
        "description": "Application configuration file (application.yml/properties) changed",
        "check": _check_application_yml_changed,
    },
    {
        "name": "migration_files_changed",
        "description": "Liquibase/Flyway migration files changed",
        "check": _check_migration_files_changed,
    },
    {
        "name": "spring_config_class_changed",
        "description": "Spring configuration class (*Config.java / *Configuration.java) changed",
        "check": _check_spring_config_class_changed,
    },
    {
        "name": "security_files_changed",
        "description": "Security-related files changed (path contains /security/)",
        "check": _check_security_files_changed,
    },
]

# Combined list for external reference
RISK_RULES: list[dict] = HARD_RULES + SOFT_RULES


# ---------------------------------------------------------------------------
# Main evaluation function
# ---------------------------------------------------------------------------

def evaluate_risks(
    changeset: "GitChangeSet",
    project: MavenProject,
    module_file_map: dict[str, list],
    config: MergeMateConfig,
    impact_ratio: float,
) -> tuple[str, list[str], bool]:
    """
    Evaluate all risk rules.

    Returns:
    (risk_level, reasons, full_build_recommended)

    risk_level: "LOW" | "MEDIUM" | "HIGH" | "CRITICAL"
    reasons: list of triggered rule descriptions
    full_build_recommended: True if any hard rule or impact ratio >= threshold
    """
    reasons: list[str] = []
    full_build_recommended = False
    hard_rule_triggered = False

    # Evaluate hard rules
    for rule in HARD_RULES:
        if rule["check"](changeset, project, module_file_map, config, impact_ratio):
            reasons.append(rule["description"])
            full_build_recommended = True
            hard_rule_triggered = True

    # Evaluate soft rules
    soft_triggered: list[str] = []
    for rule in SOFT_RULES:
        if rule["check"](changeset, project, module_file_map, config, impact_ratio):
            soft_triggered.append(rule["description"])

    reasons.extend(soft_triggered)

    # Impact ratio rule
    ratio_triggered = impact_ratio >= config.full_build_threshold
    if ratio_triggered:
        full_build_recommended = True
        if f"Impact ratio {impact_ratio:.0%} >= threshold {config.full_build_threshold:.0%}" not in reasons:
            reasons.append(
                f"Impact ratio {impact_ratio:.0%} >= threshold {config.full_build_threshold:.0%}"
            )

    # Determine risk level
    if hard_rule_triggered:
        risk_level = "CRITICAL"
    elif ratio_triggered:
        risk_level = "HIGH"
    elif len(soft_triggered) >= 3 or impact_ratio >= 0.4:
        risk_level = "HIGH"
    elif len(soft_triggered) >= 1:
        risk_level = "MEDIUM"
    else:
        risk_level = "LOW"

    return risk_level, reasons, full_build_recommended


def _matches_full_build_patterns(file_path: str, patterns: list[str]) -> bool:
    """Use fnmatch to match file_path against a list of glob patterns."""
    norm = file_path.replace("\\", "/")
    filename = norm.split("/")[-1]
    for pattern in patterns:
        if fnmatch.fnmatch(norm, pattern):
            return True
        if fnmatch.fnmatch(filename, pattern):
            return True
    return False
