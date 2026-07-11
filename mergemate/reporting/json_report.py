"""
JSON report generator for MergeMate impact analysis.
"""
from __future__ import annotations

import json
import dataclasses
from mergemate.domain.models import ImpactAnalysis, GitChangeSet, ValidationPlan


def build_json_report(
    changeset: GitChangeSet,
    impact: ImpactAnalysis | None = None,
    plan: ValidationPlan | None = None,
    jdk_compat=None,
) -> dict:
    """Build a JSON-serializable report dict."""
    report: dict = {
        "source": changeset.source_ref,
        "target": changeset.target_ref,
        "merge_base": changeset.merge_base,
        "changed_files": [
            {"path": cf.path, "status": cf.status}
            for cf in changeset.changed_files
        ],
        "java_production_files": [cf.path for cf in changeset.java_production_files],
        "java_test_files": [cf.path for cf in changeset.java_test_files],
        "pom_files": [cf.path for cf in changeset.pom_files],
        "config_files": [cf.path for cf in changeset.config_files],
        "migration_files": [cf.path for cf in changeset.migration_files],
    }

    if jdk_compat is not None:
        req = jdk_compat.requirement
        rt = jdk_compat.runtime
        report["jdk"] = {
            "required_version": req.required_version,
            "detected_from": req.detected_from,
            "detection_method": req.detection_method,
            "runtime_java_version": rt.java_version,
            "runtime_java_major": rt.java_major,
            "runtime_maven_version": rt.maven_version,
            "compatible": jdk_compat.compatible,
            "message": jdk_compat.message,
        }

    if impact is not None:
        report["impact"] = {
            "strategy": impact.strategy,
            "strategy_reason": impact.strategy_reason,
            "changed_modules": impact.changed_modules,
            "affected_modules": [
                {
                    "artifact_id": m.artifact_id,
                    "label": m.label,
                    "reason": m.reason,
                }
                for m in impact.affected_modules
            ],
            "risk_level": impact.risk_level,
            "risk_reasons": impact.risk_reasons,
            "full_build_recommended": impact.full_build_recommended,
        }

    if plan is not None and plan.maven_command is not None:
        report["maven_command"] = {
            "argv": plan.maven_command.argv,
            "display_command": plan.maven_command.display_command,
            "goal": plan.maven_command.goal,
        }

    return report


def dump_report(report: dict) -> str:
    """Serialize to JSON string with indent=2."""
    return json.dumps(report, indent=2)
