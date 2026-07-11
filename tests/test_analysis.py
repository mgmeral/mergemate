"""
tests/test_analysis.py

Unit tests for forge_analysis: FailureSummary, pattern functions, FailureAnalyzer.
"""

from __future__ import annotations

import os
import sys

_here = os.path.dirname(__file__)
_project_root = os.path.dirname(_here)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

import pytest

from forge_analysis.failure_summary import FailureSummary
from forge_analysis.patterns import (
    classify_build_failure,
    extract_failed_module,
    find_compilation_errors,
    find_conflict_markers,
    find_dependency_errors,
    find_test_failures,
)
from forge_analysis.analyzer import FailureAnalyzer


# ===========================================================================
# 1. FailureSummary is a proper dataclass (all fields accessible)
# ===========================================================================

class TestFailureSummaryDataclass:
    def test_all_fields_accessible(self):
        """FailureSummary is a proper dataclass with all fields accessible."""
        fs = FailureSummary(
            run_id="run-123",
            category="compilation_error",
            probable_root_cause="Compilation failed",
            affected_module="my-module",
            confidence=0.85,
            evidence=["[ERROR] Foo.java:10: error: ';' expected"],
            suggested_action="Fix compilation errors in the affected module and re-run.",
        )
        assert fs.run_id == "run-123"
        assert fs.category == "compilation_error"
        assert fs.probable_root_cause == "Compilation failed"
        assert fs.affected_module == "my-module"
        assert fs.confidence == 0.85
        assert len(fs.evidence) == 1
        assert fs.suggested_action == "Fix compilation errors in the affected module and re-run."


# ===========================================================================
# 2. find_compilation_errors returns lines with 'error:' and 'ERROR'
# ===========================================================================

class TestFindCompilationErrors:
    def test_returns_lines_with_error_colon(self):
        """find_compilation_errors returns lines containing 'error:'."""
        lines = [
            "[ERROR] /src/Foo.java:10: error: ';' expected",
            "Some clean line",
        ]
        result = find_compilation_errors(lines)
        assert any("error:" in line for line in result)

    def test_returns_lines_with_ERROR_uppercase(self):
        """find_compilation_errors returns lines containing 'ERROR'."""
        lines = [
            "[ERROR] BUILD FAILED",
            "Normal output line",
        ]
        result = find_compilation_errors(lines)
        assert any("ERROR" in line for line in result)

    # ===========================================================================
    # 3. find_compilation_errors does NOT return clean lines
    # ===========================================================================

    def test_does_not_return_clean_lines(self):
        """find_compilation_errors does not return lines without error markers."""
        lines = [
            "[INFO] Building project...",
            "[INFO] BUILD SUCCESS",
            "Tests run: 1, Failures: 0",
        ]
        result = find_compilation_errors(lines)
        assert result == []


# ===========================================================================
# 4. find_test_failures returns lines with 'FAILED', 'BUILD FAILURE', and
#    'Tests run: 2, Failures: 1'
# ===========================================================================

class TestFindTestFailures:
    def test_returns_lines_with_FAILED(self):
        """find_test_failures returns lines containing 'FAILED'."""
        lines = [
            "Tests run: 5, Failures: 0, Errors: 0, Skipped: 0, Time elapsed: 0.1s FAILED",
            "Normal output",
        ]
        result = find_test_failures(lines)
        assert any("FAILED" in line for line in result)

    def test_returns_lines_with_BUILD_FAILURE(self):
        """find_test_failures returns lines containing 'BUILD FAILURE'."""
        lines = [
            "[INFO] BUILD FAILURE",
            "[INFO] BUILD SUCCESS",
        ]
        result = find_test_failures(lines)
        assert any("BUILD FAILURE" in line for line in result)
        assert not any("BUILD SUCCESS" in line for line in result)

    def test_returns_lines_with_tests_run_failures_nonzero(self):
        """find_test_failures returns 'Tests run:' lines when Failures > 0."""
        lines = [
            "Tests run: 2, Failures: 1, Errors: 0, Skipped: 0",
            "Tests run: 3, Failures: 0, Errors: 0, Skipped: 0",
        ]
        result = find_test_failures(lines)
        assert len(result) == 1
        assert "Failures: 1" in result[0]


# ===========================================================================
# 5. find_dependency_errors returns lines with 'Could not resolve'
# ===========================================================================

class TestFindDependencyErrors:
    def test_returns_lines_with_could_not_resolve(self):
        """find_dependency_errors returns lines containing 'Could not resolve'."""
        lines = [
            "[ERROR] Could not resolve dependencies for project com.example:app:jar:1.0",
            "[INFO] Building...",
        ]
        result = find_dependency_errors(lines)
        assert any("Could not resolve" in line for line in result)

    def test_does_not_return_clean_lines(self):
        """find_dependency_errors does not return lines without dependency error markers."""
        lines = [
            "[INFO] Downloading: https://repo.example.com/artifact.jar",
            "[INFO] BUILD SUCCESS",
        ]
        result = find_dependency_errors(lines)
        assert result == []


# ===========================================================================
# 6. find_conflict_markers returns lines with '<<<<<<'
# ===========================================================================

class TestFindConflictMarkers:
    def test_returns_lines_with_conflict_start_marker(self):
        """find_conflict_markers returns lines containing '<<<<<<<'."""
        lines = [
            "<<<<<<< HEAD",
            "Some code",
            "=======",
            "Other code",
            ">>>>>>> feature-branch",
        ]
        result = find_conflict_markers(lines)
        assert any("<<<<<<<" in line for line in result)

    def test_returns_all_conflict_markers(self):
        """find_conflict_markers returns lines with all three conflict markers."""
        lines = [
            "<<<<<<< HEAD",
            "=======",
            ">>>>>>> feature-branch",
            "Normal line",
        ]
        result = find_conflict_markers(lines)
        assert len(result) == 3

    def test_does_not_return_clean_lines(self):
        """find_conflict_markers does not return lines without conflict markers."""
        lines = ["Normal line", "Another normal line"]
        result = find_conflict_markers(lines)
        assert result == []


# ===========================================================================
# 7. extract_failed_module returns artifactId from error line
# ===========================================================================

class TestExtractFailedModule:
    def test_extracts_artifact_id_from_error_line(self):
        """extract_failed_module returns the artifactId from a standard Maven error line."""
        lines = [
            "[ERROR] Failed to execute goal org.apache.maven.plugins:maven-compiler-plugin:3.8.1:compile "
            "(default-compile) on project my-module: Compilation failure"
        ]
        result = extract_failed_module(lines)
        assert result == "my-module"

    # ===========================================================================
    # 8. extract_failed_module returns None when no match
    # ===========================================================================

    def test_returns_none_when_no_match(self):
        """extract_failed_module returns None when no matching line is found."""
        lines = [
            "[INFO] Building project...",
            "[ERROR] Some other error",
        ]
        result = extract_failed_module(lines)
        assert result is None

    def test_returns_none_for_empty_log(self):
        """extract_failed_module returns None for empty log."""
        result = extract_failed_module([])
        assert result is None


# ===========================================================================
# 9. classify_build_failure returns ("merge_conflict", 0.95) when conflict markers present
# ===========================================================================

class TestClassifyBuildFailure:
    def test_merge_conflict_when_conflict_markers_present(self):
        """classify_build_failure returns ('merge_conflict', 0.95) when conflict markers found."""
        lines = [
            "<<<<<<< HEAD",
            "int x = 1;",
            "=======",
            "int x = 2;",
            ">>>>>>> feature-branch",
        ]
        category, confidence = classify_build_failure(lines)
        assert category == "merge_conflict"
        assert confidence == 0.95

    # ===========================================================================
    # 10. classify_build_failure returns ("compilation_error", 0.85) when compilation errors present
    # ===========================================================================

    def test_compilation_error_when_compilation_errors_present(self):
        """classify_build_failure returns ('compilation_error', 0.85) when compilation errors found (no conflicts)."""
        lines = [
            "[ERROR] /src/Foo.java:10: error: ';' expected",
            "[INFO] BUILD FAILED",
        ]
        category, confidence = classify_build_failure(lines)
        assert category == "compilation_error"
        assert confidence == 0.85

    # ===========================================================================
    # 11. classify_build_failure returns ("test_failure", 0.80) when test failure lines present
    # ===========================================================================

    def test_test_failure_when_test_failures_present(self):
        """classify_build_failure returns ('test_failure', 0.80) when test failure lines found."""
        lines = [
            "[INFO] Tests run: 3, Failures: 2, Errors: 0, Skipped: 0",
            "[INFO] BUILD FAILURE",
        ]
        category, confidence = classify_build_failure(lines)
        assert category == "test_failure"
        assert confidence == 0.80

    # ===========================================================================
    # 12. classify_build_failure returns ("dependency_error", 0.75) when dependency errors present
    # ===========================================================================

    def test_dependency_error_when_dependency_errors_present(self):
        """classify_build_failure returns ('dependency_error', 0.75) when dependency errors found."""
        lines = [
            "[ERROR] Could not resolve dependencies for project com.example:app:jar:1.0",
        ]
        category, confidence = classify_build_failure(lines)
        assert category == "dependency_error"
        assert confidence == 0.75

    # ===========================================================================
    # 13. classify_build_failure returns ("unknown", 0.3) for clean log
    # ===========================================================================

    def test_unknown_for_clean_log(self):
        """classify_build_failure returns ('unknown', 0.3) for a clean log."""
        lines = [
            "[INFO] Building project...",
            "[INFO] BUILD SUCCESS",
            "[INFO] Total time: 5.0 s",
        ]
        category, confidence = classify_build_failure(lines)
        assert category == "unknown"
        assert confidence == 0.3


# ===========================================================================
# FailureAnalyzer integration tests
# ===========================================================================

class TestFailureAnalyzer:
    def _make_analyzer(self) -> FailureAnalyzer:
        return FailureAnalyzer()

    # ===========================================================================
    # 14. FailureAnalyzer.analyze with has_conflicts=True → category="merge_conflict", confidence=0.95
    # ===========================================================================

    def test_analyze_with_conflicts_returns_merge_conflict(self):
        """FailureAnalyzer.analyze with has_conflicts=True returns category='merge_conflict', confidence=0.95."""
        analyzer = self._make_analyzer()
        result = analyzer.analyze(
            run_id="run-1",
            status="failure",
            lifecycle_log=[],
            has_conflicts=True,
            conflict_files=["src/main/java/Foo.java", "src/main/java/Bar.java"],
        )
        assert result.category == "merge_conflict"
        assert result.confidence == 0.95

    # ===========================================================================
    # 15. FailureAnalyzer.analyze with status="error", error_message set → category="unknown", confidence=0.5
    # ===========================================================================

    def test_analyze_with_error_status_and_message_returns_unknown(self):
        """FailureAnalyzer.analyze with status='error' and error_message returns category='unknown', confidence=0.5."""
        analyzer = self._make_analyzer()
        result = analyzer.analyze(
            run_id="run-2",
            status="error",
            lifecycle_log=[],
            error_message="Docker daemon not responding",
        )
        assert result.category == "unknown"
        assert result.confidence == 0.5

    # ===========================================================================
    # 16. FailureAnalyzer.analyze with compilation error in log → category="compilation_error"
    # ===========================================================================

    def test_analyze_with_compilation_error_in_log(self):
        """FailureAnalyzer.analyze with compilation error in log returns category='compilation_error'."""
        analyzer = self._make_analyzer()
        log = [
            "[ERROR] /src/Foo.java:10: error: ';' expected",
            "[INFO] BUILD FAILED",
        ]
        result = analyzer.analyze(
            run_id="run-3",
            status="failure",
            lifecycle_log=log,
        )
        assert result.category == "compilation_error"

    # ===========================================================================
    # 17. FailureAnalyzer.analyze with test failure in log → category="test_failure"
    # ===========================================================================

    def test_analyze_with_test_failure_in_log(self):
        """FailureAnalyzer.analyze with test failure in log returns category='test_failure'."""
        analyzer = self._make_analyzer()
        log = [
            "Tests run: 5, Failures: 2, Errors: 0, Skipped: 0",
            "BUILD FAILURE",
        ]
        result = analyzer.analyze(
            run_id="run-4",
            status="failure",
            lifecycle_log=log,
        )
        assert result.category == "test_failure"

    # ===========================================================================
    # 18. FailureAnalyzer.analyze with status="success" → category="unknown", confidence=0.0
    # ===========================================================================

    def test_analyze_with_success_status_returns_unknown_zero_confidence(self):
        """FailureAnalyzer.analyze with status='success' returns category='unknown', confidence=0.0."""
        analyzer = self._make_analyzer()
        result = analyzer.analyze(
            run_id="run-5",
            status="success",
            lifecycle_log=["[INFO] BUILD SUCCESS"],
        )
        assert result.category == "unknown"
        assert result.confidence == 0.0

    # ===========================================================================
    # 19. FailureAnalyzer.analyze extracts affected_module from log
    # ===========================================================================

    def test_analyze_extracts_affected_module_from_log(self):
        """FailureAnalyzer.analyze extracts the artifactId from the lifecycle log."""
        analyzer = self._make_analyzer()
        log = [
            "[ERROR] Failed to execute goal org.apache.maven.plugins:maven-compiler-plugin:3.8.1:compile "
            "(default-compile) on project my-module: Compilation failure",
            "[ERROR] /src/Foo.java:10: error: ';' expected",
        ]
        result = analyzer.analyze(
            run_id="run-6",
            status="failure",
            lifecycle_log=log,
        )
        assert result.affected_module == "my-module"

    # ===========================================================================
    # 20. FailureSummary.metadata defaults to empty dict
    # ===========================================================================

    def test_failure_summary_metadata_defaults_to_empty_dict(self):
        """FailureSummary.metadata defaults to an empty dict when not specified."""
        fs = FailureSummary(
            run_id="run-7",
            category="unknown",
            probable_root_cause="No failure detected.",
            affected_module=None,
            confidence=0.0,
            evidence=[],
            suggested_action="",
        )
        assert fs.metadata == {}
        assert isinstance(fs.metadata, dict)
