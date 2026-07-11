"""
tests/test_lifecycle_fix.py

Tests for lifecycle fixes:
  - Target branch fetch (Step 2b: git fetch origin <target_branch>)
  - Guard rejects bypass attempts
  - Work dir path is /workspace/repo
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
    ValidationLifecycle,
    run_validation,
)
from forge_worker.git_guard import check as guard_check


# ---------------------------------------------------------------------------
# Fake runner that records all calls
# ---------------------------------------------------------------------------

def _make_recording_runner():
    """
    A runner that succeeds for all git commands and records argv calls.
    diff returns a small list of changed files.
    """
    calls: list[list[str]] = []

    def runner(argv: list[str], cwd: str) -> tuple[int, str, str]:
        calls.append(list(argv))
        tokens = argv[1:] if argv and argv[0] == "git" else argv
        subcommand = tokens[0] if tokens else ""

        if subcommand == "clone":
            return 0, "", ""
        if subcommand == "fetch":
            return 0, "", ""
        if subcommand == "checkout":
            return 0, "", ""
        if subcommand == "merge":
            if "--abort" in tokens:
                return 0, "", ""
            return 0, "Already up to date.", ""
        if subcommand == "diff":
            return 0, "src/Foo.java\n", ""
        return 0, "BUILD SUCCESS", ""

    runner.calls = calls  # type: ignore[attr-defined]
    return runner


def _make_config(work_dir: str = "/workspace/repo") -> LifecycleConfig:
    return LifecycleConfig(
        remote_url="https://example.com/repo.git",
        feature_branch="feature/my-branch",
        target_branch="main",
        work_dir=work_dir,
    )


# ===========================================================================
# Test 16: ValidationLifecycle.run() calls git fetch origin <target_branch>
# ===========================================================================

class TestTargetBranchFetch:
    def test_fetch_target_branch_is_called(self):
        """run() must call 'git fetch origin <target_branch>' after fetching the feature branch."""
        runner = _make_recording_runner()
        config = _make_config()
        run_validation(config, maven_command=None, runner=runner)

        calls = runner.calls  # type: ignore[attr-defined]
        fetch_calls = [c for c in calls if len(c) >= 2 and c[0] == "git" and c[1] == "fetch"]

        # There must be at least 2 fetch calls: feature branch + target branch
        assert len(fetch_calls) >= 2, (
            f"Expected at least 2 git fetch calls, got {len(fetch_calls)}: {fetch_calls}"
        )

    def test_target_branch_fetched_explicitly(self):
        """The target branch 'main' must appear as an argument in a git fetch call."""
        runner = _make_recording_runner()
        config = _make_config()  # target_branch="main"
        run_validation(config, maven_command=None, runner=runner)

        calls = runner.calls  # type: ignore[attr-defined]
        target_fetch_calls = [
            c for c in calls
            if c[:3] == ["git", "fetch", "origin"] and "main" in c
        ]

        assert len(target_fetch_calls) >= 1, (
            f"Expected 'git fetch origin main' to be called. Fetch calls: "
            f"{[c for c in calls if 'fetch' in c]}"
        )

    def test_feature_branch_fetched_explicitly(self):
        """The feature branch must also be fetched."""
        runner = _make_recording_runner()
        config = _make_config()  # feature_branch="feature/my-branch"
        run_validation(config, maven_command=None, runner=runner)

        calls = runner.calls  # type: ignore[attr-defined]
        feature_fetch_calls = [
            c for c in calls
            if c[:3] == ["git", "fetch", "origin"] and "feature/my-branch" in c
        ]

        assert len(feature_fetch_calls) >= 1, (
            f"Expected 'git fetch origin feature/my-branch' to be called. "
            f"Fetch calls: {[c for c in calls if 'fetch' in c]}"
        )

    def test_target_branch_fetch_appears_in_log(self):
        """The lifecycle log must contain a 'fetch-target' entry."""
        runner = _make_recording_runner()
        config = _make_config()
        result = run_validation(config, maven_command=None, runner=runner)

        log = result.lifecycle_log
        fetch_target_entries = [e for e in log if "fetch-target" in e]
        assert len(fetch_target_entries) >= 1, (
            f"Expected 'fetch-target' entry in lifecycle log. Log: {log}"
        )

    def test_target_fetch_comes_after_feature_fetch_in_log(self):
        """Target branch fetch must occur after feature branch fetch in the lifecycle log."""
        runner = _make_recording_runner()
        config = _make_config()
        result = run_validation(config, maven_command=None, runner=runner)

        log = result.lifecycle_log

        def find_first(keyword: str) -> int:
            for i, entry in enumerate(log):
                if keyword in entry:
                    return i
            return -1

        feature_fetch_idx = find_first("step: fetch")
        target_fetch_idx = find_first("step: fetch-target")

        assert feature_fetch_idx != -1, f"'step: fetch' not found in log: {log}"
        assert target_fetch_idx != -1, f"'step: fetch-target' not found in log: {log}"
        assert feature_fetch_idx < target_fetch_idx, (
            "Feature branch fetch must come before target branch fetch in the log"
        )

    def test_different_target_branch_is_fetched(self):
        """If target_branch is 'develop', then 'develop' is fetched, not 'main'."""
        runner = _make_recording_runner()
        config = LifecycleConfig(
            remote_url="https://example.com/repo.git",
            feature_branch="feature/xyz",
            target_branch="develop",
            work_dir="/workspace/repo",
        )
        run_validation(config, maven_command=None, runner=runner)

        calls = runner.calls  # type: ignore[attr-defined]
        develop_fetch = [
            c for c in calls
            if c[:3] == ["git", "fetch", "origin"] and "develop" in c
        ]
        assert len(develop_fetch) >= 1, (
            f"Expected 'git fetch origin develop'. Fetch calls: "
            f"{[c for c in calls if 'fetch' in c]}"
        )


# ===========================================================================
# Test 17: Guard rejects command → GuardViolationError raised
# ===========================================================================

class TestGuardRejection:
    def test_guard_violation_raises_error_on_bad_command(self):
        """If _run() is called with a forbidden command, GuardViolationError is raised."""
        runner = _make_recording_runner()
        config = _make_config()
        lifecycle = ValidationLifecycle(config, maven_command=None, runner=runner)

        with pytest.raises(GuardViolationError):
            lifecycle._run(["git", "push", "origin", "main"])

    def test_guard_violation_on_fetch_with_extra_args(self):
        """A fetch with suspicious args (e.g., refspec override) is rejected by the guard."""
        runner = _make_recording_runner()
        config = _make_config()
        lifecycle = ValidationLifecycle(config, maven_command=None, runner=runner)

        # Attempt to force-push (definitely not allowed)
        with pytest.raises(GuardViolationError):
            lifecycle._run(["git", "push", "--force", "origin", "main"])

    def test_all_lifecycle_commands_pass_guard(self):
        """All commands issued during a full lifecycle run are accepted by the guard."""
        runner = _make_recording_runner()
        config = _make_config()
        run_validation(config, maven_command=None, runner=runner)

        calls = runner.calls  # type: ignore[attr-defined]
        git_calls = [c for c in calls if c and c[0] == "git"]

        for cmd in git_calls:
            result = guard_check(cmd)
            assert result.allowed, (
                f"Lifecycle issued a guard-rejected command: {cmd!r} — {result.reason}"
            )


# ===========================================================================
# Test 18: Work dir path is /workspace/repo
# ===========================================================================

class TestWorkDirPath:
    def test_work_dir_can_be_workspace_repo(self):
        """LifecycleConfig accepts /workspace/repo as work_dir."""
        config = _make_config(work_dir="/workspace/repo")
        assert config.work_dir == "/workspace/repo"

    def test_work_dir_is_used_as_cwd_for_git_commands(self):
        """The work_dir is passed as cwd to the runner for git commands."""
        cwd_seen: list[str] = []

        def recording_runner(argv: list[str], cwd: str) -> tuple[int, str, str]:
            cwd_seen.append(cwd)
            tokens = argv[1:] if argv and argv[0] == "git" else argv
            subcommand = tokens[0] if tokens else ""
            if subcommand == "clone":
                return 0, "", ""
            if subcommand == "fetch":
                return 0, "", ""
            if subcommand == "checkout":
                return 0, "", ""
            if subcommand == "merge":
                if "--abort" in tokens:
                    return 0, "", ""
                return 0, "Already up to date.", ""
            if subcommand == "diff":
                return 0, "src/Foo.java\n", ""
            return 0, "BUILD SUCCESS", ""

        config = _make_config(work_dir="/workspace/repo")
        run_validation(config, maven_command=None, runner=recording_runner)

        # At least some commands should have used /workspace/repo as cwd
        assert "/workspace/repo" in cwd_seen, (
            f"Expected /workspace/repo in cwd list. cwds seen: {cwd_seen}"
        )

    def test_default_work_dir_in_test_config_is_workspace_repo(self):
        """The _make_config helper defaults to /workspace/repo (not /workspace)."""
        config = _make_config()  # no explicit work_dir arg
        assert config.work_dir == "/workspace/repo"
