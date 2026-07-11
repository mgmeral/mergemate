"""
Phase 4 tests for MergeMate.

Tests for:
- maven/command_builder.py
- execution/runner.py
- reporting/file_report.py
- domain/models.py (ValidationExecution, determine_status)
"""
from __future__ import annotations

import json
import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest

from mergemate.domain.models import (
    ImpactAnalysis,
    ModuleImpact,
    GitChangeSet,
    ChangedFile,
    MavenCommand,
    ValidationPlan,
    ValidationExecution,
    determine_status,
    TestCandidate,
)
from mergemate.execution.adapter import ExecutionResult
from mergemate.maven.command_builder import (
    build_maven_command,
    _pl_arg,
    _format_display_command,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_incremental_impact(changed=("order-service",), dependents=("checkout-api",)) -> ImpactAnalysis:
    affected = []
    for mid in changed:
        affected.append(ModuleImpact(artifact_id=mid, label="changed", reason="Has changed files"))
    for mid in dependents:
        affected.append(ModuleImpact(artifact_id=mid, label="dependent", reason="Depends on changed"))
    return ImpactAnalysis(
        strategy="incremental",
        strategy_reason="2 changed modules",
        changed_modules=list(changed),
        affected_modules=affected,
        risk_level="MEDIUM",
        risk_reasons=[],
        full_build_recommended=False,
    )


def _make_full_impact() -> ImpactAnalysis:
    return ImpactAnalysis(
        strategy="full",
        strategy_reason="Risk rules triggered full build",
        changed_modules=["order-service"],
        affected_modules=[
            ModuleImpact(artifact_id="order-service", label="changed", reason="Full build"),
        ],
        risk_level="HIGH",
        risk_reasons=["POM file changed"],
        full_build_recommended=True,
    )


def _make_changeset() -> GitChangeSet:
    return GitChangeSet(
        source_ref="HEAD",
        target_ref="main",
        merge_base="abc1234",
        changed_files=[ChangedFile(path="order-service/src/main/java/OrderService.java", status="modified")],
        java_production_files=[ChangedFile(path="order-service/src/main/java/OrderService.java", status="modified")],
    )


# ---------------------------------------------------------------------------
# Command builder tests
# ---------------------------------------------------------------------------

class TestBuildMavenCommandCompile:
    """Test 1: compile with incremental -> -DskipTests in argv"""

    def test_compile_incremental_has_skip_tests(self, tmp_path):
        impact = _make_incremental_impact()
        cmd = build_maven_command(str(tmp_path), impact, "compile")
        assert "-DskipTests" in cmd.argv

    def test_compile_incremental_has_pl_flag(self, tmp_path):
        impact = _make_incremental_impact(changed=["order-service"], dependents=["checkout-api"])
        cmd = build_maven_command(str(tmp_path), impact, "compile")
        argv_str = " ".join(cmd.argv)
        assert "-pl" in argv_str

    def test_compile_goal_in_argv(self, tmp_path):
        impact = _make_incremental_impact()
        cmd = build_maven_command(str(tmp_path), impact, "compile")
        assert "compile" in cmd.argv


class TestBuildMavenCommandTest:
    """Test 2: test with incremental -> 'test' in argv"""

    def test_test_incremental_has_test_goal(self, tmp_path):
        impact = _make_incremental_impact()
        cmd = build_maven_command(str(tmp_path), impact, "test")
        assert "test" in cmd.argv

    def test_test_no_skip_tests(self, tmp_path):
        impact = _make_incremental_impact()
        cmd = build_maven_command(str(tmp_path), impact, "test")
        assert "-DskipTests" not in cmd.argv

    def test_test_with_candidates_adds_dtest(self, tmp_path):
        impact = _make_incremental_impact()
        candidates = [
            TestCandidate(
                class_name="OrderServiceTest",
                file_path="order-service/src/test/java/OrderServiceTest.java",
                module_artifact_id="order-service",
                score=0.9,
                confidence="HIGH",
                reasons=["Name match"],
                is_integration_test=False,
            )
        ]
        cmd = build_maven_command(str(tmp_path), impact, "test", test_candidates=candidates)
        argv_str = " ".join(cmd.argv)
        assert "-Dtest=OrderServiceTest" in argv_str


class TestBuildMavenCommandVerify:
    """Test 3: verify incremental -> 'verify', no -DskipTests"""

    def test_verify_has_verify_goal(self, tmp_path):
        impact = _make_incremental_impact()
        cmd = build_maven_command(str(tmp_path), impact, "verify")
        assert "verify" in cmd.argv

    def test_verify_no_skip_tests(self, tmp_path):
        impact = _make_incremental_impact()
        cmd = build_maven_command(str(tmp_path), impact, "verify")
        assert "-DskipTests" not in cmd.argv


class TestBuildMavenCommandFullBuild:
    """Test 4: full build -> no -pl in argv"""

    def test_full_build_no_pl(self, tmp_path):
        impact = _make_full_impact()
        cmd = build_maven_command(str(tmp_path), impact, "test")
        assert "-pl" not in cmd.argv

    def test_force_full_no_pl(self, tmp_path):
        impact = _make_incremental_impact()
        cmd = build_maven_command(str(tmp_path), impact, "test", force_full=True)
        assert "-pl" not in cmd.argv


class TestPlArg:
    """Test 5: _pl_arg sorts and formats correctly"""

    def test_single_module(self):
        assert _pl_arg(["a"]) == ":a"

    def test_multiple_sorted(self):
        result = _pl_arg(["b", "a"])
        assert result == ":a,:b"

    def test_two_modules(self):
        result = _pl_arg(["order-service", "checkout-api"])
        assert result == ":checkout-api,:order-service"


class TestTestCandidatesInCommand:
    """Test 6: test candidates provided -> -Dtest=TestA,TestB in argv"""

    def test_multiple_candidates(self, tmp_path):
        impact = _make_incremental_impact()
        candidates = [
            TestCandidate(
                class_name="TestA",
                file_path="module/src/test/java/TestA.java",
                module_artifact_id="order-service",
                score=0.9,
                confidence="HIGH",
                reasons=[],
                is_integration_test=False,
            ),
            TestCandidate(
                class_name="TestB",
                file_path="module/src/test/java/TestB.java",
                module_artifact_id="order-service",
                score=0.8,
                confidence="HIGH",
                reasons=[],
                is_integration_test=False,
            ),
        ]
        cmd = build_maven_command(str(tmp_path), impact, "test", test_candidates=candidates)
        argv_str = " ".join(cmd.argv)
        assert "TestA" in argv_str
        assert "TestB" in argv_str

    def test_integration_tests_excluded_from_dtest(self, tmp_path):
        impact = _make_incremental_impact()
        candidates = [
            TestCandidate(
                class_name="OrderServiceIT",
                file_path="module/src/test/java/OrderServiceIT.java",
                module_artifact_id="order-service",
                score=0.9,
                confidence="HIGH",
                reasons=[],
                is_integration_test=True,  # integration test
            ),
        ]
        cmd = build_maven_command(str(tmp_path), impact, "test", test_candidates=candidates)
        argv_str = " ".join(cmd.argv)
        # IT tests should not go into -Dtest=
        assert "-Dtest=" not in argv_str


class TestFormatDisplayCommand:
    """Test 7: _format_display_command wraps long lines"""

    def test_short_command_no_wrap(self):
        argv = ["./mvnw", "test"]
        result = _format_display_command(argv)
        assert result == "./mvnw test"
        assert "\\" not in result

    def test_long_command_wraps(self):
        # Build a command that exceeds 80 chars
        argv = ["./mvnw", "-pl", ":order-service,:checkout-api,:payment-service,:shipping-service", "-am", "test"]
        result = _format_display_command(argv)
        # Should contain backslash if long enough
        if len(" ".join(argv)) > 80:
            assert "\\" in result

    def test_wrapping_produces_continuation(self):
        # Force a long command
        long_module_list = ":a" * 40  # very long -pl arg
        argv = ["./mvnw", "-pl", long_module_list, "-am", "test"]
        result = _format_display_command(argv)
        assert "\\" in result


# ---------------------------------------------------------------------------
# Runner tests (mock adapter)
# ---------------------------------------------------------------------------

class TestCommandRunner:
    """Tests 8-10: CommandRunner behavior"""

    def _make_mock_adapter(self, exit_code=0, stdout="BUILD SUCCESS", stderr="", timed_out=False, duration=5.0):
        adapter = MagicMock()
        adapter.execute.return_value = ExecutionResult(
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            timed_out=timed_out,
            duration_seconds=duration,
        )
        return adapter

    def test_run_calls_adapter_execute(self, tmp_path):
        """Test 8: CommandRunner.run() calls adapter.execute() with correct argv"""
        from mergemate.execution.runner import CommandRunner

        adapter = self._make_mock_adapter()
        runner = CommandRunner(adapter=adapter, stream_output=False)

        cmd = MavenCommand(argv=["mvn", "test"], display_command="mvn test", goal="test")
        result = runner.run(cmd, str(tmp_path))

        adapter.execute.assert_called_once_with(
            argv=["mvn", "test"],
            working_dir=str(tmp_path),
            timeout_s=3600,
            env=None,
        )

    def test_run_returns_execution_result(self, tmp_path):
        """Test 9: Returns ExecutionResult with exit_code from adapter"""
        from mergemate.execution.runner import CommandRunner

        adapter = self._make_mock_adapter(exit_code=0)
        runner = CommandRunner(adapter=adapter, stream_output=False)

        cmd = MavenCommand(argv=["mvn", "test"], display_command="mvn test", goal="test")
        result = runner.run(cmd, str(tmp_path))

        assert isinstance(result, ExecutionResult)
        assert result.exit_code == 0

    def test_run_returns_timeout_result(self, tmp_path):
        """Test 10: Timeout result: ExecutionResult.timed_out=True"""
        from mergemate.execution.runner import CommandRunner

        adapter = self._make_mock_adapter(exit_code=-1, timed_out=True)
        runner = CommandRunner(adapter=adapter, stream_output=False)

        cmd = MavenCommand(argv=["mvn", "test"], display_command="mvn test", goal="test")
        result = runner.run(cmd, str(tmp_path))

        assert result.timed_out is True

    def test_run_with_custom_timeout(self, tmp_path):
        """Verify timeout is passed to adapter.execute"""
        from mergemate.execution.runner import CommandRunner

        adapter = self._make_mock_adapter()
        runner = CommandRunner(adapter=adapter, stream_output=False)

        cmd = MavenCommand(argv=["mvn", "test"], display_command="mvn test", goal="test")
        runner.run(cmd, str(tmp_path), timeout_s=900)

        _, kwargs = adapter.execute.call_args
        assert kwargs["timeout_s"] == 900 or adapter.execute.call_args[0][2] == 900 or \
               adapter.execute.call_args.kwargs.get("timeout_s", adapter.execute.call_args.args[2] if len(adapter.execute.call_args.args) > 2 else None) == 900


# ---------------------------------------------------------------------------
# File report tests
# ---------------------------------------------------------------------------

class TestWriteRunReport:
    """Tests 11-15: write_run_report behavior"""

    def _make_impact(self) -> ImpactAnalysis:
        return _make_incremental_impact()

    def _make_plan(self, impact: ImpactAnalysis) -> ValidationPlan:
        cmd = MavenCommand(argv=["mvn", "test"], display_command="mvn test", goal="test")
        return ValidationPlan(impact=impact, maven_command=cmd, profile="test")

    def test_creates_report_json(self, tmp_path):
        """Test 11: write_run_report() creates .mergemate/runs/<run-id>/report.json"""
        from mergemate.reporting.file_report import write_run_report

        changeset = _make_changeset()
        impact = self._make_impact()

        run_id = "test-run-001"
        report_dir = write_run_report(
            repo_root=str(tmp_path),
            changeset=changeset,
            impact=impact,
            plan=None,
            result=None,
            run_id=run_id,
        )

        expected_json = os.path.join(str(tmp_path), ".mergemate", "runs", run_id, "report.json")
        assert os.path.isfile(expected_json)
        assert report_dir == os.path.join(str(tmp_path), ".mergemate", "runs", run_id)

    def test_report_json_contains_required_fields(self, tmp_path):
        """Test 12: report.json contains run_id, strategy, changed_files"""
        from mergemate.reporting.file_report import write_run_report

        changeset = _make_changeset()
        impact = self._make_impact()

        run_id = "test-run-002"
        report_dir = write_run_report(
            repo_root=str(tmp_path),
            changeset=changeset,
            impact=impact,
            plan=None,
            result=None,
            run_id=run_id,
        )

        report_path = os.path.join(report_dir, "report.json")
        with open(report_path, "r") as f:
            report = json.load(f)

        assert report["run_id"] == run_id
        assert "strategy" in report
        assert "changed_files" in report

    def test_stdout_log_written_when_result_has_stdout(self, tmp_path):
        """Test 13: stdout.log written when result has stdout"""
        from mergemate.reporting.file_report import write_run_report

        changeset = _make_changeset()
        impact = self._make_impact()
        result = ExecutionResult(
            exit_code=0,
            stdout="[INFO] BUILD SUCCESS",
            stderr="",
            timed_out=False,
            duration_seconds=10.0,
        )

        run_id = "test-run-003"
        report_dir = write_run_report(
            repo_root=str(tmp_path),
            changeset=changeset,
            impact=impact,
            plan=None,
            result=result,
            run_id=run_id,
        )

        stdout_path = os.path.join(report_dir, "stdout.log")
        assert os.path.isfile(stdout_path)
        content = open(stdout_path).read()
        assert "BUILD SUCCESS" in content

    def test_stderr_log_written_when_result_has_stderr(self, tmp_path):
        """Test 14: stderr.log written when result has stderr"""
        from mergemate.reporting.file_report import write_run_report

        changeset = _make_changeset()
        impact = self._make_impact()
        result = ExecutionResult(
            exit_code=1,
            stdout="",
            stderr="[ERROR] BUILD FAILURE",
            timed_out=False,
            duration_seconds=5.0,
        )

        run_id = "test-run-004"
        report_dir = write_run_report(
            repo_root=str(tmp_path),
            changeset=changeset,
            impact=impact,
            plan=None,
            result=result,
            run_id=run_id,
        )

        stderr_path = os.path.join(report_dir, "stderr.log")
        assert os.path.isfile(stderr_path)
        content = open(stderr_path).read()
        assert "BUILD FAILURE" in content

    def test_returns_run_directory_path(self, tmp_path):
        """Test 15: Returns the run directory path"""
        from mergemate.reporting.file_report import write_run_report

        changeset = _make_changeset()
        impact = self._make_impact()

        run_id = "test-run-005"
        report_dir = write_run_report(
            repo_root=str(tmp_path),
            changeset=changeset,
            impact=impact,
            plan=None,
            result=None,
            run_id=run_id,
        )

        assert isinstance(report_dir, str)
        assert run_id in report_dir
        assert os.path.isdir(report_dir)

    def test_no_stdout_log_when_empty(self, tmp_path):
        """stdout.log should not be created when stdout is empty"""
        from mergemate.reporting.file_report import write_run_report

        changeset = _make_changeset()
        impact = self._make_impact()
        result = ExecutionResult(exit_code=0, stdout="", stderr="", timed_out=False, duration_seconds=1.0)

        run_id = "test-run-006"
        report_dir = write_run_report(
            repo_root=str(tmp_path),
            changeset=changeset,
            impact=impact,
            plan=None,
            result=result,
            run_id=run_id,
        )

        stdout_path = os.path.join(report_dir, "stdout.log")
        assert not os.path.isfile(stdout_path)

    def test_auto_generates_run_id(self, tmp_path):
        """run_id is auto-generated if not provided"""
        from mergemate.reporting.file_report import write_run_report

        changeset = _make_changeset()
        impact = self._make_impact()

        report_dir = write_run_report(
            repo_root=str(tmp_path),
            changeset=changeset,
            impact=impact,
            plan=None,
            result=None,
        )

        assert os.path.isdir(report_dir)
        # Check report.json contains a run_id
        report_path = os.path.join(report_dir, "report.json")
        with open(report_path) as f:
            data = json.load(f)
        assert "run_id" in data
        assert len(data["run_id"]) > 0


# ---------------------------------------------------------------------------
# Status determination tests
# ---------------------------------------------------------------------------

class TestDetermineStatus:
    """Tests 16-19: determine_status() logic"""

    def _make_cmd(self) -> MavenCommand:
        return MavenCommand(argv=["mvn", "test"], display_command="mvn test", goal="test")

    def test_exit_code_0_is_success(self):
        """Test 16: exit_code=0 -> success"""
        status = determine_status(
            exit_code=0,
            timed_out=False,
            maven_command=self._make_cmd(),
        )
        assert status == "success"

    def test_exit_code_nonzero_is_failure(self):
        """Test 17: exit_code=1 (Maven failure) -> failure"""
        status = determine_status(
            exit_code=1,
            timed_out=False,
            maven_command=self._make_cmd(),
        )
        assert status == "failure"

    def test_timed_out_is_timeout(self):
        """Test 18: timed_out=True -> timeout"""
        status = determine_status(
            exit_code=-1,
            timed_out=True,
            maven_command=self._make_cmd(),
        )
        assert status == "timeout"

    def test_no_maven_command_is_skipped(self):
        """Test 19: No maven command -> skipped"""
        status = determine_status(
            exit_code=None,
            timed_out=False,
            maven_command=None,
        )
        assert status == "skipped"

    def test_error_message_with_no_exit_code_is_error(self):
        """Internal exception -> error"""
        status = determine_status(
            exit_code=None,
            timed_out=False,
            maven_command=self._make_cmd(),
            error_message="git worktree failed",
        )
        assert status == "error"

    def test_exit_code_2_is_failure(self):
        """Non-zero exit codes are failures, not errors"""
        status = determine_status(
            exit_code=2,
            timed_out=False,
            maven_command=self._make_cmd(),
        )
        assert status == "failure"


# ---------------------------------------------------------------------------
# ValidationExecution dataclass tests
# ---------------------------------------------------------------------------

class TestValidationExecution:
    """Test 20: Dataclass has all required fields"""

    def test_all_required_fields_present(self):
        """ValidationExecution has all required fields"""
        from mergemate.domain.models import ValidationExecution

        cmd = MavenCommand(argv=["mvn", "test"], display_command="mvn test", goal="test")
        exec_obj = ValidationExecution(
            run_id="test-123",
            status="success",
            started_at="2026-01-01T00:00:00Z",
            finished_at="2026-01-01T00:00:42Z",
            exit_code=0,
            duration_seconds=42.0,
            maven_command=cmd,
            stdout_path="/tmp/runs/test-123/stdout.log",
            stderr_path=None,
            report_dir="/tmp/runs/test-123",
            error_message=None,
            timed_out=False,
        )

        assert exec_obj.run_id == "test-123"
        assert exec_obj.status == "success"
        assert exec_obj.exit_code == 0
        assert exec_obj.duration_seconds == 42.0
        assert exec_obj.timed_out is False
        assert exec_obj.maven_command is cmd
        assert exec_obj.stdout_path == "/tmp/runs/test-123/stdout.log"
        assert exec_obj.stderr_path is None
        assert exec_obj.report_dir == "/tmp/runs/test-123"
        assert exec_obj.error_message is None

    def test_default_timed_out_is_false(self):
        cmd = MavenCommand(argv=["mvn", "test"], display_command="mvn test", goal="test")
        exec_obj = ValidationExecution(
            run_id="x",
            status="success",
            started_at="2026-01-01T00:00:00Z",
            finished_at=None,
            exit_code=0,
            duration_seconds=0.0,
            maven_command=cmd,
            stdout_path=None,
            stderr_path=None,
            report_dir=None,
            error_message=None,
        )
        assert exec_obj.timed_out is False

    def test_timeout_status_fields(self):
        exec_obj = ValidationExecution(
            run_id="timeout-run",
            status="timeout",
            started_at="2026-01-01T00:00:00Z",
            finished_at="2026-01-01T00:30:00Z",
            exit_code=-1,
            duration_seconds=1800.0,
            maven_command=None,
            stdout_path=None,
            stderr_path=None,
            report_dir=None,
            error_message="Process killed after timeout",
            timed_out=True,
        )
        assert exec_obj.timed_out is True
        assert exec_obj.status == "timeout"
