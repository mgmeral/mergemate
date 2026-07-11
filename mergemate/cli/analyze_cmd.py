"""
analyze command — full impact analysis pipeline.
"""
from __future__ import annotations

import os
import sys

from mergemate.git.diff import build_changeset
from mergemate.maven.jdk import (
    detect_jdk_requirement,
    detect_maven_runtime,
    check_jdk_compatibility,
    format_incompatibility_error,
)
from mergemate.maven.wrapper import find_maven_executable
from mergemate.config.loader import load_config


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
