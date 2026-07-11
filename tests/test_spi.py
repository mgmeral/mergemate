"""
tests/test_spi.py

Tests for forge_spi: Plugin SPI (Slice 5).

Covers:
  1.  ValidationStep is an ABC — cannot be instantiated directly
  2.  StepResult dataclass fields are correct
  3.  StepContext is a proper dataclass
  4.  GitCloneFetchStep.name == "git-clone-fetch"
  5.  GitCloneFetchStep.run() happy path → success=True, metadata has "cloned_to"
  6.  GitCloneFetchStep.run() with failing runner → success=False
  7.  GitMergeCheckStep.run() happy path → success=True, has_conflicts=False, changed_files list
  8.  GitMergeCheckStep.run() with conflict in merge stdout → success=False, has_conflicts=True
  9.  GitMergeCheckStep.run() verifies merge-abort is always called
  10. MavenBuildStep.can_run() returns False when ctx.maven_command is None
  11. MavenBuildStep.can_run() returns True when ctx.maven_command is set
  12. MavenBuildStep.run() success (exit_code=0) → success=True
  13. MavenBuildStep.run() failure (exit_code=1) → success=False
  14. Guard rejection: a step returns failure when guard blocks a command
  15. ValidationStep.can_run() default returns True
"""

from __future__ import annotations

import dataclasses
import os
import sys
from typing import Callable

import pytest

_here = os.path.dirname(__file__)
_project_root = os.path.dirname(_here)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from forge_spi.context import StepContext
from forge_spi.result import StepResult
from forge_spi.step import ValidationStep
from forge_spi.plugins.git_plugin import GitCloneFetchStep, GitMergeCheckStep
from forge_spi.plugins.maven_plugin import MavenBuildStep


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_context(
    maven_command: str | None = "mvn clean verify",
    runner: Callable[[list[str], str], tuple[int, str, str]] | None = None,
    changed_files: list[str] | None = None,
    extra: dict | None = None,
) -> StepContext:
    """Build a minimal StepContext for testing."""
    return StepContext(
        run_id="test-run-001",
        remote_url="https://github.com/example/repo.git",
        feature_branch="feature/my-branch",
        target_branch="main",
        work_dir="/workspace/repo",
        maven_command=maven_command,
        active_maven_profiles=[],
        runner=runner if runner is not None else _ok_runner,
        changed_files=changed_files if changed_files is not None else [],
        extra=extra if extra is not None else {},
    )


def _ok_runner(argv: list[str], cwd: str) -> tuple[int, str, str]:
    """A fake runner that always succeeds."""
    return (0, "ok", "")


def _fail_runner(argv: list[str], cwd: str) -> tuple[int, str, str]:
    """A fake runner that always fails."""
    return (1, "", "fatal: auth")


# ---------------------------------------------------------------------------
# Test 1: ValidationStep is an ABC — cannot be instantiated directly
# ---------------------------------------------------------------------------

class TestValidationStepABC:
    def test_cannot_instantiate_abstract_class(self):
        """ValidationStep is abstract and cannot be instantiated directly."""
        with pytest.raises(TypeError):
            ValidationStep()  # type: ignore[abstract]

    def test_concrete_subclass_without_name_cannot_instantiate(self):
        """A subclass missing the 'name' property cannot be instantiated."""
        class IncompleteStep(ValidationStep):
            def run(self, ctx: StepContext) -> StepResult:
                return StepResult(
                    step_name="incomplete",
                    success=True,
                    output="",
                    duration_seconds=0.0,
                    metadata={},
                )
        with pytest.raises(TypeError):
            IncompleteStep()

    def test_concrete_subclass_without_run_cannot_instantiate(self):
        """A subclass missing 'run' cannot be instantiated."""
        class IncompleteStep(ValidationStep):
            @property
            def name(self) -> str:
                return "incomplete"
        with pytest.raises(TypeError):
            IncompleteStep()


# ---------------------------------------------------------------------------
# Test 2: StepResult dataclass fields are correct
# ---------------------------------------------------------------------------

class TestStepResultDataclass:
    def test_is_a_dataclass(self):
        """StepResult must be a dataclass."""
        assert dataclasses.is_dataclass(StepResult)

    def test_required_fields_exist(self):
        """StepResult must have the five required fields."""
        fields = {f.name for f in dataclasses.fields(StepResult)}
        assert "step_name" in fields
        assert "success" in fields
        assert "output" in fields
        assert "duration_seconds" in fields
        assert "metadata" in fields

    def test_can_construct_with_all_fields(self):
        """StepResult can be constructed with explicit values."""
        sr = StepResult(
            step_name="test-step",
            success=True,
            output="all good",
            duration_seconds=1.23,
            metadata={"exit_code": 0},
        )
        assert sr.step_name == "test-step"
        assert sr.success is True
        assert sr.output == "all good"
        assert sr.duration_seconds == 1.23
        assert sr.metadata == {"exit_code": 0}

    def test_success_can_be_false(self):
        """StepResult.success can be False."""
        sr = StepResult(
            step_name="failing-step",
            success=False,
            output="error details",
            duration_seconds=0.5,
            metadata={},
        )
        assert sr.success is False


# ---------------------------------------------------------------------------
# Test 3: StepContext is a proper dataclass
# ---------------------------------------------------------------------------

class TestStepContextDataclass:
    def test_is_a_dataclass(self):
        """StepContext must be a dataclass."""
        assert dataclasses.is_dataclass(StepContext)

    def test_required_fields_exist(self):
        """StepContext must have all required fields."""
        fields = {f.name for f in dataclasses.fields(StepContext)}
        expected = {
            "run_id",
            "remote_url",
            "feature_branch",
            "target_branch",
            "work_dir",
            "maven_command",
            "active_maven_profiles",
            "runner",
            "changed_files",
            "extra",
        }
        assert expected <= fields

    def test_can_construct(self):
        """StepContext can be constructed with all required values."""
        ctx = _make_context()
        assert ctx.run_id == "test-run-001"
        assert ctx.feature_branch == "feature/my-branch"
        assert ctx.target_branch == "main"
        assert ctx.maven_command == "mvn clean verify"


# ---------------------------------------------------------------------------
# Test 4: GitCloneFetchStep.name
# ---------------------------------------------------------------------------

class TestGitCloneFetchStepName:
    def test_name_is_git_clone_fetch(self):
        """GitCloneFetchStep.name must equal 'git-clone-fetch'."""
        step = GitCloneFetchStep()
        assert step.name == "git-clone-fetch"


# ---------------------------------------------------------------------------
# Test 5: GitCloneFetchStep.run() happy path
# ---------------------------------------------------------------------------

class TestGitCloneFetchStepHappyPath:
    def test_success_returns_true(self):
        """A fake runner returning (0, 'ok', '') causes success=True."""
        step = GitCloneFetchStep()
        ctx = _make_context(runner=_ok_runner)
        result = step.run(ctx)
        assert result.success is True

    def test_metadata_has_cloned_to(self):
        """Success result metadata must include 'cloned_to' key."""
        step = GitCloneFetchStep()
        ctx = _make_context(runner=_ok_runner)
        result = step.run(ctx)
        assert "cloned_to" in result.metadata
        assert result.metadata["cloned_to"] == ctx.work_dir

    def test_step_name_in_result(self):
        """Result step_name must match step.name."""
        step = GitCloneFetchStep()
        ctx = _make_context(runner=_ok_runner)
        result = step.run(ctx)
        assert result.step_name == "git-clone-fetch"

    def test_duration_is_non_negative(self):
        """Duration must be >= 0."""
        step = GitCloneFetchStep()
        ctx = _make_context(runner=_ok_runner)
        result = step.run(ctx)
        assert result.duration_seconds >= 0.0


# ---------------------------------------------------------------------------
# Test 6: GitCloneFetchStep.run() with failing runner
# ---------------------------------------------------------------------------

class TestGitCloneFetchStepFailure:
    def test_fail_runner_returns_false(self):
        """A runner returning (1, '', 'fatal: auth') causes success=False."""
        step = GitCloneFetchStep()
        ctx = _make_context(runner=_fail_runner)
        result = step.run(ctx)
        assert result.success is False

    def test_fail_output_contains_error(self):
        """The output should reflect the stderr on failure."""
        step = GitCloneFetchStep()
        ctx = _make_context(runner=_fail_runner)
        result = step.run(ctx)
        assert "fatal: auth" in result.output

    def test_does_not_raise(self):
        """run() must never raise even on failure."""
        step = GitCloneFetchStep()
        ctx = _make_context(runner=_fail_runner)
        # Should not raise
        result = step.run(ctx)
        assert isinstance(result, StepResult)


# ---------------------------------------------------------------------------
# Test 7: GitMergeCheckStep.run() happy path (no conflicts)
# ---------------------------------------------------------------------------

class TestGitMergeCheckStepHappyPath:
    def _make_merge_runner(self, changed_files: list[str] | None = None) -> Callable:
        """
        Returns a runner that succeeds for all git commands.
        For the diff command, returns the changed_files list as output.
        """
        files = changed_files or ["src/Foo.java", "src/Bar.java"]

        def runner(argv: list[str], cwd: str) -> tuple[int, str, str]:
            # git diff --name-only returns file list
            if "diff" in argv:
                return (0, "\n".join(files), "")
            # merge --abort and everything else succeeds
            return (0, "Merge made by the 'recursive' strategy.", "")

        return runner

    def test_success_is_true(self):
        """Clean merge returns success=True."""
        step = GitMergeCheckStep()
        ctx = _make_context(runner=self._make_merge_runner())
        result = step.run(ctx)
        assert result.success is True

    def test_has_conflicts_is_false(self):
        """Clean merge has_conflicts=False in metadata."""
        step = GitMergeCheckStep()
        ctx = _make_context(runner=self._make_merge_runner())
        result = step.run(ctx)
        assert result.metadata["has_conflicts"] is False

    def test_changed_files_is_populated(self):
        """changed_files list is populated from git diff output."""
        step = GitMergeCheckStep()
        ctx = _make_context(runner=self._make_merge_runner(["src/Foo.java", "src/Bar.java"]))
        result = step.run(ctx)
        assert "changed_files" in result.metadata
        assert "src/Foo.java" in result.metadata["changed_files"]
        assert "src/Bar.java" in result.metadata["changed_files"]

    def test_conflict_files_is_empty(self):
        """conflict_files is empty on a clean merge."""
        step = GitMergeCheckStep()
        ctx = _make_context(runner=self._make_merge_runner())
        result = step.run(ctx)
        assert result.metadata["conflict_files"] == []

    def test_step_name_in_result(self):
        """Result step_name must match step.name."""
        step = GitMergeCheckStep()
        ctx = _make_context(runner=self._make_merge_runner())
        result = step.run(ctx)
        assert result.step_name == "git-merge-check"


# ---------------------------------------------------------------------------
# Test 8: GitMergeCheckStep.run() with conflict in merge stdout
# ---------------------------------------------------------------------------

class TestGitMergeCheckStepConflicts:
    def _make_conflict_runner(self) -> Callable:
        """Returns a runner that simulates a conflicted merge."""
        def runner(argv: list[str], cwd: str) -> tuple[int, str, str]:
            if "merge" in argv and "--no-commit" in argv:
                conflict_out = (
                    "Auto-merging src/Main.java\n"
                    "CONFLICT (content): Merge conflict in src/Main.java\n"
                    "Automatic merge failed; fix conflicts and then commit the result."
                )
                return (1, conflict_out, "")
            if "merge" in argv and "--abort" in argv:
                return (0, "", "")
            if "diff" in argv:
                return (0, "src/Main.java", "")
            return (0, "", "")

        return runner

    def test_success_is_false_on_conflict(self):
        """Conflicted merge returns success=False."""
        step = GitMergeCheckStep()
        ctx = _make_context(runner=self._make_conflict_runner())
        result = step.run(ctx)
        assert result.success is False

    def test_has_conflicts_is_true(self):
        """Conflicted merge sets has_conflicts=True in metadata."""
        step = GitMergeCheckStep()
        ctx = _make_context(runner=self._make_conflict_runner())
        result = step.run(ctx)
        assert result.metadata["has_conflicts"] is True

    def test_conflict_files_populated(self):
        """Conflict file paths are extracted from the merge output."""
        step = GitMergeCheckStep()
        ctx = _make_context(runner=self._make_conflict_runner())
        result = step.run(ctx)
        assert "src/Main.java" in result.metadata["conflict_files"]

    def test_does_not_raise(self):
        """run() must not raise on conflict."""
        step = GitMergeCheckStep()
        ctx = _make_context(runner=self._make_conflict_runner())
        result = step.run(ctx)
        assert isinstance(result, StepResult)


# ---------------------------------------------------------------------------
# Test 9: GitMergeCheckStep.run() verifies merge-abort is always called
# ---------------------------------------------------------------------------

class TestGitMergeCheckAbort:
    def test_abort_called_on_clean_merge(self):
        """merge --abort must be called even when the merge is clean."""
        abort_calls: list[list[str]] = []

        def runner(argv: list[str], cwd: str) -> tuple[int, str, str]:
            if "merge" in argv and "--abort" in argv:
                abort_calls.append(list(argv))
            if "diff" in argv:
                return (0, "src/Foo.java", "")
            return (0, "Merge made by the 'recursive' strategy.", "")

        step = GitMergeCheckStep()
        ctx = _make_context(runner=runner)
        step.run(ctx)

        assert len(abort_calls) == 1
        assert "--abort" in abort_calls[0]

    def test_abort_called_on_conflicted_merge(self):
        """merge --abort must be called even when there are conflicts."""
        abort_calls: list[list[str]] = []

        def runner(argv: list[str], cwd: str) -> tuple[int, str, str]:
            if "merge" in argv and "--abort" in argv:
                abort_calls.append(list(argv))
                return (0, "", "")
            if "merge" in argv and "--no-commit" in argv:
                return (1, "CONFLICT (content): Merge conflict in src/A.java", "")
            if "diff" in argv:
                return (0, "src/A.java", "")
            return (0, "", "")

        step = GitMergeCheckStep()
        ctx = _make_context(runner=runner)
        step.run(ctx)

        assert len(abort_calls) == 1
        assert "--abort" in abort_calls[0]


# ---------------------------------------------------------------------------
# Test 10: MavenBuildStep.can_run() returns False when maven_command is None
# ---------------------------------------------------------------------------

class TestMavenBuildStepCanRunFalse:
    def test_can_run_false_when_no_command(self):
        """can_run() must return False when ctx.maven_command is None."""
        step = MavenBuildStep()
        ctx = _make_context(maven_command=None)
        assert step.can_run(ctx) is False


# ---------------------------------------------------------------------------
# Test 11: MavenBuildStep.can_run() returns True when maven_command is set
# ---------------------------------------------------------------------------

class TestMavenBuildStepCanRunTrue:
    def test_can_run_true_when_command_set(self):
        """can_run() must return True when ctx.maven_command is set."""
        step = MavenBuildStep()
        ctx = _make_context(maven_command="mvn clean verify")
        assert step.can_run(ctx) is True

    def test_can_run_true_with_non_empty_command(self):
        """can_run() returns True for any non-None maven_command."""
        step = MavenBuildStep()
        ctx = _make_context(maven_command="mvn test -Pci")
        assert step.can_run(ctx) is True


# ---------------------------------------------------------------------------
# Test 12: MavenBuildStep.run() success (exit_code=0)
# ---------------------------------------------------------------------------

class TestMavenBuildStepSuccess:
    def test_success_when_exit_code_zero(self):
        """Runner returning exit_code=0 causes success=True."""
        def runner(argv: list[str], cwd: str) -> tuple[int, str, str]:
            return (0, "BUILD SUCCESS", "")

        step = MavenBuildStep()
        ctx = _make_context(maven_command="mvn clean verify", runner=runner)
        result = step.run(ctx)
        assert result.success is True

    def test_exit_code_in_metadata(self):
        """Result metadata must include 'exit_code'."""
        def runner(argv: list[str], cwd: str) -> tuple[int, str, str]:
            return (0, "BUILD SUCCESS", "")

        step = MavenBuildStep()
        ctx = _make_context(maven_command="mvn clean verify", runner=runner)
        result = step.run(ctx)
        assert result.metadata["exit_code"] == 0

    def test_maven_command_in_metadata(self):
        """Result metadata must include 'maven_command'."""
        def runner(argv: list[str], cwd: str) -> tuple[int, str, str]:
            return (0, "BUILD SUCCESS", "")

        step = MavenBuildStep()
        ctx = _make_context(maven_command="mvn clean verify", runner=runner)
        result = step.run(ctx)
        assert result.metadata["maven_command"] == "mvn clean verify"

    def test_step_name_in_result(self):
        """Result step_name must be 'maven-build'."""
        def runner(argv: list[str], cwd: str) -> tuple[int, str, str]:
            return (0, "BUILD SUCCESS", "")

        step = MavenBuildStep()
        ctx = _make_context(maven_command="mvn clean verify", runner=runner)
        result = step.run(ctx)
        assert result.step_name == "maven-build"


# ---------------------------------------------------------------------------
# Test 13: MavenBuildStep.run() failure (exit_code=1)
# ---------------------------------------------------------------------------

class TestMavenBuildStepFailure:
    def test_failure_when_exit_code_nonzero(self):
        """Runner returning exit_code=1 causes success=False."""
        def runner(argv: list[str], cwd: str) -> tuple[int, str, str]:
            return (1, "", "BUILD FAILURE")

        step = MavenBuildStep()
        ctx = _make_context(maven_command="mvn clean verify", runner=runner)
        result = step.run(ctx)
        assert result.success is False

    def test_exit_code_in_metadata_on_failure(self):
        """Failure result metadata must include exit_code=1."""
        def runner(argv: list[str], cwd: str) -> tuple[int, str, str]:
            return (1, "", "BUILD FAILURE")

        step = MavenBuildStep()
        ctx = _make_context(maven_command="mvn clean verify", runner=runner)
        result = step.run(ctx)
        assert result.metadata["exit_code"] == 1

    def test_does_not_raise_on_failure(self):
        """run() must not raise even when the build fails."""
        def runner(argv: list[str], cwd: str) -> tuple[int, str, str]:
            return (1, "", "BUILD FAILURE")

        step = MavenBuildStep()
        ctx = _make_context(maven_command="mvn clean verify", runner=runner)
        result = step.run(ctx)
        assert isinstance(result, StepResult)


# ---------------------------------------------------------------------------
# Test 14: Guard rejection — step returns failure for blocked commands
# ---------------------------------------------------------------------------

class TestGuardRejection:
    def test_clone_fetch_guard_rejection_for_blocked_clone(self):
        """
        If the guard rejects a command, GitCloneFetchStep must return
        StepResult(success=False) with output containing 'guard rejected:'.

        We patch the guard_check name in the git_plugin module directly
        (that is where the import lives), so the mock takes effect.
        """
        import unittest.mock as mock
        from forge_worker.git_guard import GuardResult
        import forge_spi.plugins.git_plugin as git_plugin_module

        with mock.patch.object(
            git_plugin_module,
            "guard_check",
            return_value=GuardResult(allowed=False, reason="blocked for test"),
        ):
            step = GitCloneFetchStep()
            ctx = _make_context(runner=_ok_runner)
            result = step.run(ctx)

        assert result.success is False
        assert "guard rejected" in result.output
        assert "blocked for test" in result.output

    def test_merge_check_guard_rejection(self):
        """GitMergeCheckStep returns failure when guard blocks checkout."""
        import unittest.mock as mock
        from forge_worker.git_guard import GuardResult
        import forge_spi.plugins.git_plugin as git_plugin_module

        with mock.patch.object(
            git_plugin_module,
            "guard_check",
            return_value=GuardResult(allowed=False, reason="blocked for test"),
        ):
            step = GitMergeCheckStep()
            ctx = _make_context(runner=_ok_runner)
            result = step.run(ctx)

        assert result.success is False
        assert "guard rejected" in result.output


# ---------------------------------------------------------------------------
# Test 15: ValidationStep.can_run() default returns True
# ---------------------------------------------------------------------------

class TestValidationStepDefaultCanRun:
    def test_default_can_run_returns_true(self):
        """The default can_run() implementation must return True."""

        class ConcreteStep(ValidationStep):
            @property
            def name(self) -> str:
                return "concrete"

            def run(self, ctx: StepContext) -> StepResult:
                return StepResult(
                    step_name=self.name,
                    success=True,
                    output="",
                    duration_seconds=0.0,
                    metadata={},
                )

        step = ConcreteStep()
        ctx = _make_context()
        assert step.can_run(ctx) is True

    def test_git_clone_fetch_can_run_always_true(self):
        """GitCloneFetchStep does not override can_run, so default True is used."""
        step = GitCloneFetchStep()
        ctx = _make_context()
        assert step.can_run(ctx) is True

    def test_git_merge_check_can_run_always_true(self):
        """GitMergeCheckStep does not override can_run, so default True is used."""
        step = GitMergeCheckStep()
        ctx = _make_context()
        assert step.can_run(ctx) is True
