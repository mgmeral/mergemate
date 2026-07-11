"""
File report writer — writes .mergemate/runs/<run-id>/ report files after a validation run.
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone

from mergemate.domain.models import ImpactAnalysis, GitChangeSet, ValidationPlan
from mergemate.execution.adapter import ExecutionResult


def write_run_report(
    repo_root: str,
    changeset: GitChangeSet,
    impact: ImpactAnalysis,
    plan: ValidationPlan | None,
    result: ExecutionResult | None,
    run_id: str | None = None,
) -> str:
    """
    Write report files to .mergemate/runs/<run-id>/.

    Files written:
    - report.json: full structured report
    - stdout.log: Maven stdout (if result provided)
    - stderr.log: Maven stderr (if result provided)

    Returns the run directory path.
    Creates parent dirs if needed.
    """
    if run_id is None:
        run_id = str(uuid.uuid4())

    started_at = datetime.now(timezone.utc).isoformat()

    run_dir = os.path.join(repo_root, ".mergemate", "runs", run_id)
    os.makedirs(run_dir, exist_ok=True)

    # Build and write report.json
    report_dict = _build_report_dict(
        run_id=run_id,
        started_at=started_at,
        changeset=changeset,
        impact=impact,
        plan=plan,
        result=result,
    )
    report_path = os.path.join(run_dir, "report.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report_dict, f, indent=2)

    # Write stdout.log
    if result is not None and result.stdout:
        stdout_path = os.path.join(run_dir, "stdout.log")
        with open(stdout_path, "w", encoding="utf-8") as f:
            f.write(result.stdout)

    # Write stderr.log
    if result is not None and result.stderr:
        stderr_path = os.path.join(run_dir, "stderr.log")
        with open(stderr_path, "w", encoding="utf-8") as f:
            f.write(result.stderr)

    return run_dir


def _build_report_dict(
    run_id: str,
    started_at: str,
    changeset: GitChangeSet,
    impact: ImpactAnalysis,
    plan: ValidationPlan | None,
    result: ExecutionResult | None,
) -> dict:
    """Build the JSON report dict."""
    report: dict = {
        "run_id": run_id,
        "started_at": started_at,
        "source": changeset.source_ref,
        "target": changeset.target_ref,
        "merge_base": changeset.merge_base,
        "changed_files": [
            {"path": cf.path, "status": cf.status}
            for cf in changeset.changed_files
        ],
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

    if result is not None:
        report["execution"] = {
            "exit_code": result.exit_code,
            "timed_out": result.timed_out,
            "duration_seconds": result.duration_seconds,
        }

    return report
