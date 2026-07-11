"""
Maven command builder — centralises all MavenCommand construction.
"""
from __future__ import annotations

from mergemate.domain.models import MavenCommand, ImpactAnalysis
from mergemate.maven.wrapper import get_effective_maven_argv


def build_maven_command(
    project_dir: str,
    impact: ImpactAnalysis,
    goal: str,
    test_candidates: list | None = None,
    force_full: bool = False,
    extra_args: list[str] | None = None,
) -> MavenCommand:
    """
    Build the Maven command argv list.

    Rules:
    - goal="compile": add -DskipTests
    - goal="test": if test_candidates and not full build:
        unit tests: -Dtest=TestA,TestB test
        integration tests: -Dit.test=ITTestA verify
        if both unit and IT: return primary unit test command only
    - goal="verify": no extra test flags (run everything)
    - Incremental: ./mvnw -pl :mod-a,:mod-b -am <goal> [flags]
    - Full: ./mvnw <goal> [flags]

    display_command: argv joined with spaces, line-wrapped with backslash at 80 chars
    """
    maven_args: list[str] = []

    use_incremental = (
        impact.strategy == "incremental"
        and not force_full
        and not impact.full_build_recommended
    )

    if use_incremental:
        # Collect changed + dependent modules for -pl
        primary_ids = [
            m.artifact_id
            for m in impact.affected_modules
            if m.label in ("changed", "dependent")
        ]
        if primary_ids:
            maven_args += ["-pl", _pl_arg(primary_ids), "-am"]

    # Build goal-specific flags
    if goal == "compile":
        maven_args.append(goal)
        maven_args.append("-DskipTests")
    elif goal == "test":
        # Check for specific test candidates (unit tests only for primary command)
        if test_candidates and use_incremental:
            unit_tests = [
                tc for tc in test_candidates
                if not tc.is_integration_test
            ]
            if unit_tests:
                test_list = ",".join(tc.class_name for tc in unit_tests)
                maven_args.append(f"-Dtest={test_list}")
        maven_args.append(goal)
    elif goal == "verify":
        maven_args.append(goal)
    else:
        maven_args.append(goal)

    if extra_args:
        maven_args.extend(extra_args)

    argv = get_effective_maven_argv(project_dir, maven_args)
    display = _format_display_command(argv)

    return MavenCommand(
        argv=argv,
        display_command=display,
        goal=goal,
    )


def _format_display_command(argv: list[str]) -> str:
    """
    Join argv into a readable string.
    Wrap long commands with backslash continuation at ~80 chars.
    """
    joined = " ".join(argv)
    if len(joined) <= 80:
        return joined

    # Wrap at ~80 chars with backslash continuation
    lines = []
    current_line = ""
    for token in argv:
        if not current_line:
            current_line = token
        elif len(current_line) + 1 + len(token) <= 78:
            current_line += " " + token
        else:
            lines.append(current_line + " \\")
            current_line = "  " + token
    if current_line:
        lines.append(current_line)

    return "\n".join(lines)


def _pl_arg(module_ids: list[str]) -> str:
    """Build -pl :mod-a,:mod-b string."""
    return ",".join(f":{m}" for m in sorted(module_ids))
