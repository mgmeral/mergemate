"""
analyze command — full impact analysis pipeline.
"""
from __future__ import annotations

import os
import sys
import uuid
from datetime import datetime, timezone

from mergemate.git.diff import build_changeset
from mergemate.maven.jdk import (
    detect_jdk_requirement,
    detect_maven_runtime,
    check_jdk_compatibility,
    format_incompatibility_error,
)
from mergemate.maven.wrapper import find_maven_executable
from mergemate.config.loader import load_config
from mergemate.domain.models import ValidationExecution, determine_status


def run_analyze(args):
    repo_dir = args.repo_dir or os.getcwd()
    config = load_config(repo_dir)

    target = args.target or config.target_branch
    if not target:
        print("Error: --target is required (or set targetBranch in .mergemate.yml)", file=sys.stderr)
        sys.exit(1)

    source = getattr(args, "source", "HEAD")
    profiles = (
        [p.strip() for p in args.profiles.split(",") if p.strip()]
        if getattr(args, "profiles", "")
        else []
    )
    goal = getattr(args, "goal", None)   # None for analyze-only

    # 1. Git diff
    changeset = build_changeset(repo_dir, source, target)

    # 2. Maven project
    root_pom = os.path.join(repo_dir, "pom.xml")
    project = None
    if os.path.exists(root_pom):
        from mergemate.maven.project import load_project
        project = load_project(root_pom, profiles)

    # 3. JDK detection
    maven_exe = find_maven_executable(repo_dir)
    jdk_compat = None
    if os.path.exists(root_pom):
        jdk_req = detect_jdk_requirement(root_pom)
        try:
            jdk_runtime = detect_maven_runtime(maven_exe)
            jdk_compat = check_jdk_compatibility(jdk_req, jdk_runtime)
            if not jdk_compat.compatible and config.jdk_strict:
                print(format_incompatibility_error(jdk_compat), file=sys.stderr)
                sys.exit(1)
        except Exception:
            pass   # JDK detection failed gracefully

    # 4. Impact analysis
    impact = None
    plan = None
    if project:
        from mergemate.impact.analyzer import ImpactAnalyzer
        # Allow --impact-depth to override config
        impact_depth = getattr(args, "impact_depth", None)
        if impact_depth is not None:
            config.impact_max_depth = impact_depth
        analyzer = ImpactAnalyzer(config)
        impact = analyzer.analyze(changeset, project, repo_dir)
        if goal:
            plan = analyzer.build_validation_plan(impact, project, repo_dir, goal=goal)

    # 5. Report
    if getattr(args, "json", False):
        from mergemate.reporting.json_report import build_json_report, dump_report
        report = build_json_report(changeset, impact, plan, jdk_compat)
        print(dump_report(report))
    else:
        from mergemate.reporting.console import print_analyze_report
        print_analyze_report(changeset, impact, plan, jdk_compat)


def run_validation(args, goal: str) -> int:
    """
    Run the full validation pipeline (analyze + Maven execution).

    Steps:
    1. Run same analysis pipeline as run_analyze
    2. Create LocalWorktreeAdapter (or CurrentWorkspaceAdapter per config)
    3. Prepare the worktree via adapter.prepare()
    4. Build MavenCommand via build_maven_command()
    5. Run via CommandRunner.run()
    6. Write report via write_run_report()
    7. Print result summary
    8. Return exit code (0=success, 1=failure/error/timeout)
    """
    repo_dir = args.repo_dir or os.getcwd()
    config = load_config(repo_dir)

    target = args.target or config.target_branch
    if not target:
        print("Error: --target is required (or set targetBranch in .mergemate.yml)", file=sys.stderr)
        return 1

    source = getattr(args, "source", "HEAD")
    profiles = (
        [p.strip() for p in args.profiles.split(",") if p.strip()]
        if getattr(args, "profiles", "")
        else []
    )
    force_full = getattr(args, "full", False)

    run_id = str(uuid.uuid4())
    started_at = datetime.now(timezone.utc).isoformat()

    # 1. Git diff
    try:
        changeset = build_changeset(repo_dir, source, target)
    except Exception as e:
        print(f"Error: Failed to compute git changeset: {e}", file=sys.stderr)
        return 1

    # 2. Maven project
    root_pom = os.path.join(repo_dir, "pom.xml")
    project = None
    if os.path.exists(root_pom):
        from mergemate.maven.project import load_project
        project = load_project(root_pom, profiles)

    # 3. JDK detection
    maven_exe = find_maven_executable(repo_dir)
    if os.path.exists(root_pom):
        jdk_req = detect_jdk_requirement(root_pom)
        try:
            jdk_runtime = detect_maven_runtime(maven_exe)
            jdk_compat = check_jdk_compatibility(jdk_req, jdk_runtime)
            if not jdk_compat.compatible and config.jdk_strict:
                print(format_incompatibility_error(jdk_compat), file=sys.stderr)
                return 1
        except Exception:
            pass

    # 4. Impact analysis
    impact = None
    if project:
        from mergemate.impact.analyzer import ImpactAnalyzer
        impact_depth = getattr(args, "impact_depth", None)
        if impact_depth is not None:
            config.impact_max_depth = impact_depth
        analyzer = ImpactAnalyzer(config)
        impact = analyzer.analyze(changeset, project, repo_dir)

    if impact is None:
        print("Warning: No Maven project found. Cannot build Maven command.", file=sys.stderr)
        return 1

    # 5. Build Maven command
    from mergemate.maven.command_builder import build_maven_command
    maven_cmd = build_maven_command(
        project_dir=repo_dir,
        impact=impact,
        goal=goal,
        test_candidates=impact.test_candidates if impact.test_candidates else None,
        force_full=force_full,
    )

    # Determine timeout from config
    timeout_map = {
        "test": config.timeout_test,
        "compile": config.timeout_compile,
        "verify": config.timeout_verify,
    }
    timeout_s = timeout_map.get(goal, 1800)

    # Print pre-run info
    print(f"Running: {maven_cmd.display_command}")
    print(f"Timeout: {timeout_s}s")
    print()

    # 6. Create execution adapter and run
    from mergemate.execution.adapter import ExecutionResult

    error_message: str | None = None
    exec_result: ExecutionResult | None = None
    working_dir: str | None = None

    # Determine execution mode
    use_worktree = config.execution_mode == "worktree"

    if use_worktree:
        from mergemate.execution.local_worktree import LocalWorktreeAdapter
        adapter = LocalWorktreeAdapter(repo_dir)
    else:
        from mergemate.execution.current_workspace import CurrentWorkspaceAdapter
        adapter = CurrentWorkspaceAdapter()

    try:
        try:
            working_dir = adapter.prepare(repo_dir, source)
        except Exception as e:
            error_message = f"Failed to prepare execution environment: {e}"
            print(f"Warning: {error_message}", file=sys.stderr)
            print("Falling back to current directory.", file=sys.stderr)
            working_dir = repo_dir

        print(f"Working dir: {working_dir}")
        print()

        from mergemate.execution.runner import CommandRunner
        runner = CommandRunner(adapter=adapter, stream_output=True)
        exec_result = runner.run(
            command=maven_cmd,
            working_dir=working_dir or repo_dir,
            timeout_s=timeout_s,
        )
    except Exception as e:
        error_message = str(e)
        print(f"Error: {error_message}", file=sys.stderr)
    finally:
        try:
            adapter.cleanup()
        except Exception:
            pass

    # 7. Build ValidationPlan
    from mergemate.domain.models import ValidationPlan
    plan = ValidationPlan(
        impact=impact,
        maven_command=maven_cmd,
        profile=goal,
    )

    # 8. Determine status
    timed_out = exec_result.timed_out if exec_result else False
    exit_code = exec_result.exit_code if exec_result else None
    duration = exec_result.duration_seconds if exec_result else 0.0

    status = determine_status(
        exit_code=exit_code,
        timed_out=timed_out,
        maven_command=maven_cmd,
        error_message=error_message,
    )

    # 9. Write report
    from mergemate.reporting.file_report import write_run_report

    stdout_path: str | None = None
    stderr_path: str | None = None
    report_dir: str | None = None

    try:
        report_dir = write_run_report(
            repo_root=repo_dir,
            changeset=changeset,
            impact=impact,
            plan=plan,
            result=exec_result,
            run_id=run_id,
        )
        if exec_result and exec_result.stdout:
            stdout_path = os.path.join(report_dir, "stdout.log")
        if exec_result and exec_result.stderr:
            stderr_path = os.path.join(report_dir, "stderr.log")
    except Exception as e:
        print(f"Warning: Failed to write report: {e}", file=sys.stderr)

    # 10. Build ValidationExecution
    finished_at = datetime.now(timezone.utc).isoformat()
    execution = ValidationExecution(
        run_id=run_id,
        status=status,
        started_at=started_at,
        finished_at=finished_at,
        exit_code=exit_code,
        duration_seconds=duration,
        maven_command=maven_cmd,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        report_dir=report_dir,
        error_message=error_message,
        timed_out=timed_out,
    )

    # 11. Print result summary
    from mergemate.reporting.console import print_validation_result
    print()
    print_validation_result(execution)

    # Return exit code
    if status == "success":
        return 0
    return 1


def run_test(args) -> int:
    return run_validation(args, "test")


def run_compile(args) -> int:
    return run_validation(args, "compile")


def run_verify(args) -> int:
    return run_validation(args, "verify")
