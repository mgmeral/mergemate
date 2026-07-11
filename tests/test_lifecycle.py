"""
tests/test_lifecycle.py

Unit tests for forge_worker.lifecycle.

Uses an injectable fake runner — no real git or Docker required.
"""

from __future__ import annotations

import os
import sys

import pytest

_here = os.path.dirname(__file__)
_project_root = os.path.dirname(_here)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from forge_worker.lifecycle import (
    GuardViolationError,
    LifecycleConfig,
    ValidationResult,
    ValidationLifecycle,
    run_validation,
)
from forge_worker.git_guard import check as guard_check


# ---------------------------------------------------------------------------
# Fake runner helpers
# ---------------------------------------------------------------------------

def make_happy_runner(changed_files: list[str] | None = None) -> object:
    """
    Build a fake runner that simulates a clean merge (no conflicts).

    The runner tracks which commands were called so tests can inspect them.
    """
    if changed_files is None:
        changed_files = ["src/Foo.java", "src/Bar.java"]

    diff_output = "\n".join(changed_files) + "\n" if changed_files else ""

    calls: list[list[str]] = []

    def runner(argv: list[str], cwd: str) -> tuple[int, str, str]:
        calls.append(list(argv))
        subcmd_tokens = argv[1:] if argv and argv[0] == "git" else argv
        subcommand = subcmd_tokens[0] if subcmd_tokens else ""

        if subcommand == "clone":
            return 0, "", ""
        if subcommand == "fetch":
            return 0, "", ""
        if subcommand == "checkout":
            return 0, "", ""
        if subcommand == "merge":
            if "--abort" in subcmd_tokens:
                return 0, "", ""
            # No conflict: success
            return 0, "Already up to date.", ""
        if subcommand == "diff":
            return 0, diff_output, ""
        # Maven / other
        return 0, "BUILD SUCCESS", ""

    runner.calls = calls  # type: ignore[attr-defined]
    return runner


def make_conflict_runner(conflict_files: list[str] | None = None) -> object:
    """
    Build a fake runner that simulates a merge conflict.
    """
    if conflict_files is None:
        conflict_files = ["src/Conflict.java"]

    conflict_output_lines = "\n".join(
        f"CONFLICT (content): Merge conflict in {f}" for f in conflict_files
    )

    calls: list[list[str]] = []

    def runner(argv: list[str], cwd: str) -> tuple[int, str, str]:
        calls.append(list(argv))
        subcmd_tokens = argv[1:] if argv and argv[0] == "git" else argv
        subcommand = subcmd_tokens[0] if subcmd_tokens else ""

        if subcommand == "clone":
            return 0, "", ""
        if subcommand == "fetch":
            return 0, "", ""
        if subcommand == "checkout":
            return 0, "", ""
        if subcommand == "merge":
            if "--abort" in subcmd_tokens:
                return 0, "", ""
            # Conflict: non-zero rc and CONFLICT in output
            return 1, conflict_output_lines, "Automatic merge failed; fix conflicts and then commit the result."
        if subcommand == "diff":
            return 0, "src/Conflict.java\n", ""
        return 0, "", ""

    runner.calls = calls  # type: ignore[attr-defined]
    return runner


def _make_config(work_dir: str = "/work/repo") -> LifecycleConfig:
    return LifecycleConfig(
        remote_url="https://example.com/repo.git",
        feature_branch="feature/my-branch",
        target_branch="main",
        work_dir=work_dir,
    )


# ===========================================================================
# Test 1: Happy path — no conflicts, correct changed_files returned
# ===========================================================================

def test_happy_path_no_conflicts():
    """Happy path: all steps succeed, returns ValidationResult with no conflicts."""
    changed = ["src/Foo.java", "src/Bar.java"]
    runner = make_happy_runner(changed_files=changed)
    config = _make_config()

    result = run_validation(config, maven_command="mvn clean verify", runner=runner)

    assert isinstance(result, ValidationResult)
    assert result.has_conflicts is False
    assert result.conflict_files == []
    assert set(result.changed_files) == set(changed)
    assert result.maven_command == "mvn clean verify"
    assert len(result.lifecycle_log) > 0


# ===========================================================================
# Test 2: Merge conflict detected
# ===========================================================================

def test_merge_conflict_detected():
    """Merge conflict: ValidationResult has has_conflicts=True, maven_command=None."""
    conflict_files = ["src/Conflict.java"]
    runner = make_conflict_runner(conflict_files=conflict_files)
    config = _make_config()

    result = run_validation(config, maven_command="mvn clean verify", runner=runner)

    assert result.has_conflicts is True
    assert result.maven_command is None  # build skipped on conflict
    assert "src/Conflict.java" in result.conflict_files


# ===========================================================================
# Test 3: Guard violation raises GuardViolationError
# ===========================================================================

def test_guard_violation_raises_error():
    """
    If lifecycle somehow constructs a command the guard rejects,
    GuardViolationError is raised.

    We test this by directly invoking the guard on a rejected command via
    a patched lifecycle that uses a forbidden command. The simplest way is
    to exercise ValidationLifecycle with a runner but forcibly call _run
    with a bad argv.
    """
    config = _make_config()
    runner = make_happy_runner()
    lifecycle = ValidationLifecycle(config, maven_command=None, runner=runner)

    with pytest.raises(GuardViolationError) as exc_info:
        # Calling _run directly with a rejected command
        lifecycle._run(["git", "push", "origin", "main"])

    assert "push" in str(exc_info.value).lower() or "not allowed" in str(exc_info.value).lower()


# ===========================================================================
# Test 4: Step ordering in lifecycle_log
# ===========================================================================

def test_step_ordering_in_log():
    """lifecycle_log shows steps in order: clone, fetch, checkout, merge-check, diff."""
    runner = make_happy_runner()
    config = _make_config()

    result = run_validation(config, maven_command="mvn clean verify", runner=runner)

    log = result.lifecycle_log

    # Find index of each step marker
    def find_step(keyword: str) -> int:
        for i, entry in enumerate(log):
            if keyword in entry:
                return i
        return -1

    clone_idx = find_step("step: clone")
    fetch_idx = find_step("step: fetch")
    checkout_idx = find_step("step: checkout")
    merge_idx = find_step("step: merge-check")
    diff_idx = find_step("step: diff")

    assert clone_idx != -1, f"'step: clone' not found in log: {log}"
    assert fetch_idx != -1, f"'step: fetch' not found in log: {log}"
    assert checkout_idx != -1, f"'step: checkout' not found in log: {log}"
    assert merge_idx != -1, f"'step: merge-check' not found in log: {log}"
    assert diff_idx != -1, f"'step: diff' not found in log: {log}"

    assert clone_idx < fetch_idx, "clone must come before fetch"
    assert fetch_idx < checkout_idx, "fetch must come before checkout"
    assert checkout_idx < merge_idx, "checkout must come before merge-check"
    assert merge_idx < diff_idx, "merge-check must come before diff"


# ===========================================================================
# Test 5: Merge abort called after conflict detection
# ===========================================================================

def test_merge_abort_called_after_conflict():
    """After conflict detection, verify the abort command (merge --abort) was called."""
    runner = make_conflict_runner()
    config = _make_config()

    result = run_validation(config, maven_command="mvn clean verify", runner=runner)

    # Inspect calls on the runner
    calls = runner.calls  # type: ignore[attr-defined]

    # Find all merge commands
    merge_calls = [c for c in calls if len(c) > 1 and c[0] == "git" and c[1] == "merge"]

    # There must be at least two: the merge-check and the abort
    assert len(merge_calls) >= 2, f"Expected at least 2 merge calls, got: {merge_calls}"

    # The abort call must be present
    abort_calls = [c for c in merge_calls if "--abort" in c]
    assert abort_calls, f"merge --abort was not called. Merge calls: {merge_calls}"


# ===========================================================================
# Test 6: Guard validates every git command
# ===========================================================================

def test_guard_validates_all_commands():
    """All git commands issued by the lifecycle pass through the guard."""
    runner = make_happy_runner(changed_files=["pom.xml"])
    config = _make_config()

    result = run_validation(config, maven_command="mvn clean verify", runner=runner)

    # Verify that each git command in the runner's call list would be allowed by guard.
    calls = runner.calls  # type: ignore[attr-defined]
    git_calls = [c for c in calls if c and c[0] == "git"]

    for call in git_calls:
        guard_result = guard_check(call)
        assert guard_result.allowed, (
            f"Lifecycle issued a command the guard would reject: {call!r} — {guard_result.reason}"
        )


# ===========================================================================
# Test 7: No maven command — build step skipped cleanly
# ===========================================================================

def test_no_maven_command_skips_build():
    """When maven_command=None, build step is skipped and result.maven_command is None."""
    runner = make_happy_runner()
    config = _make_config()

    result = run_validation(config, maven_command=None, runner=runner)

    assert result.maven_command is None
    # No build entry in log
    build_in_log = any("step: build" in entry and "skipped" not in entry for entry in result.lifecycle_log)
    assert not build_in_log, f"Build should be skipped but log shows: {result.lifecycle_log}"


# ===========================================================================
# Test 8: ValidationResult fields completeness
# ===========================================================================

def test_validation_result_fields():
    """ValidationResult must have all required fields populated."""
    runner = make_happy_runner(changed_files=["src/A.java"])
    config = _make_config()

    result = run_validation(config, maven_command="mvn -pl :core test", runner=runner)

    assert hasattr(result, "has_conflicts")
    assert hasattr(result, "changed_files")
    assert hasattr(result, "conflict_files")
    assert hasattr(result, "maven_command")
    assert hasattr(result, "lifecycle_log")

    assert isinstance(result.has_conflicts, bool)
    assert isinstance(result.changed_files, list)
    assert isinstance(result.conflict_files, list)
    assert isinstance(result.lifecycle_log, list)
