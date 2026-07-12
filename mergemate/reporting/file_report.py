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
    working_dir: str | None = None,
    status: str | None = None,
) -> str:
    """
    Write report files to .mergemate/runs/<run-id>/.

    Files written:
    - report.json: full structured report
    - report.html: standalone HTML report
    - stdout.log: Maven stdout (if result provided)
    - stderr.log: Maven stderr (if result provided)

    Args:
        working_dir: Maven execution directory; used to find surefire/failsafe results.
        status: terminal status string (success/failure/error/timeout/skipped).

    Returns the run directory path.
    Creates parent dirs if needed.
    """
    if run_id is None:
        run_id = str(uuid.uuid4())

    started_at = datetime.now(timezone.utc).isoformat()

    run_dir = os.path.join(repo_root, ".mergemate", "runs", run_id)
    os.makedirs(run_dir, exist_ok=True)

    # Collect surefire/failsafe results (best-effort, never raises)
    surefire = None
    if working_dir and result is not None:
        try:
            from mergemate.reporting.surefire import collect_surefire_results
            surefire = collect_surefire_results(working_dir)
            if not surefire.suites:
                surefire = None
        except Exception:
            surefire = None

    # Build report dict
    report_dict = _build_report_dict(
        run_id=run_id,
        started_at=started_at,
        changeset=changeset,
        impact=impact,
        plan=plan,
        result=result,
        surefire=surefire,
        status=status,
    )

    # Write report.json
    report_path = os.path.join(run_dir, "report.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report_dict, f, indent=2)

    # Write report.html (best-effort)
    try:
        from mergemate.reporting.html_report import write_html_report
        write_html_report(run_dir, report_dict, surefire)
    except Exception:
        pass

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
    surefire=None,
    status: str | None = None,
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
        "impact": {
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
        },
        # Flat copies for backwards compatibility with existing tests/consumers
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

    if impact.test_candidates:
        report["test_candidates"] = [
            {
                "class_name": c.class_name,
                "file_path": c.file_path,
                "module_artifact_id": c.module_artifact_id,
                "score": round(c.score, 4),
                "confidence": c.confidence,
                "reasons": c.reasons,
                "is_integration_test": c.is_integration_test,
            }
            for c in impact.test_candidates
        ]

    if plan is not None and plan.maven_command is not None:
        report["maven_command"] = {
            "argv": plan.maven_command.argv,
            "display_command": plan.maven_command.display_command,
            "goal": plan.maven_command.goal,
        }

    if result is not None:
        report["execution"] = {
            "status": status or "",
            "exit_code": result.exit_code,
            "timed_out": result.timed_out,
            "duration_seconds": result.duration_seconds,
        }

    if surefire is not None and surefire.suites:
        report["surefire"] = {
            "total_tests": surefire.total_tests,
            "total_passed": surefire.total_passed,
            "total_failures": surefire.total_failures,
            "total_skipped": surefire.total_skipped,
            "total_time_seconds": round(surefire.total_time, 3),
            "all_passed": surefire.all_passed,
            "suites": [
                {
                    "name": s.name,
                    "tests": s.tests,
                    "passed": s.passed,
                    "failures": s.failures,
                    "errors": s.errors,
                    "skipped": s.skipped,
                    "time_seconds": round(s.time_seconds, 3),
                }
                for s in surefire.suites
            ],
        }

    return report
