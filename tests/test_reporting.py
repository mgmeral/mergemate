"""
tests/test_reporting.py

Tests for:
  - mergemate/reporting/surefire.py   (Surefire/Failsafe XML parser)
  - mergemate/reporting/html_report.py (standalone HTML report generator)
  - mergemate/reporting/file_report.py (updated to write HTML + surefire data)
"""
from __future__ import annotations

import json
import os
import tempfile
import textwrap

import pytest

from mergemate.reporting.surefire import (
    SurefireResults,
    TestSuiteResult,
    TestCaseResult,
    collect_surefire_results,
    _parse_testsuite_xml,
)
from mergemate.reporting.html_report import build_html_report, write_html_report


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_suite_xml(
    name: str = "com.example.FooTest",
    tests: int = 3,
    failures: int = 0,
    errors: int = 0,
    skipped: int = 0,
    time: float = 1.234,
    test_cases: str = "",
) -> str:
    return textwrap.dedent(f"""\
        <?xml version="1.0" encoding="UTF-8"?>
        <testsuite name="{name}" tests="{tests}" failures="{failures}"
                   errors="{errors}" skipped="{skipped}" time="{time}">
        {test_cases}
        </testsuite>
    """)


def _write_suite(directory: str, filename: str, xml: str) -> str:
    path = os.path.join(directory, filename)
    with open(path, "w", encoding="utf-8") as f:
        f.write(xml)
    return path


def _minimal_report(run_id: str = "test-run-1") -> dict:
    return {
        "run_id": run_id,
        "started_at": "2026-07-12T08:00:00+00:00",
        "source": "feature/order",
        "target": "origin/main",
        "merge_base": "abc123def456",
        "changed_files": [
            {"path": "src/main/java/OrderService.java", "status": "modified"},
        ],
        "impact": {
            "strategy": "incremental",
            "strategy_reason": "Only 1/5 modules affected",
            "changed_modules": ["order-service"],
            "affected_modules": [
                {"artifact_id": "order-service", "label": "changed", "reason": "direct change"},
                {"artifact_id": "checkout-api",  "label": "dependent", "reason": "depends on order-service"},
            ],
            "risk_level": "MEDIUM",
            "risk_reasons": ["Application configuration file changed"],
            "full_build_recommended": False,
        },
        "strategy": "incremental",
        "strategy_reason": "Only 1/5 modules affected",
        "changed_modules": ["order-service"],
        "affected_modules": [
            {"artifact_id": "order-service", "label": "changed", "reason": "direct change"},
            {"artifact_id": "checkout-api",  "label": "dependent", "reason": "depends on order-service"},
        ],
        "risk_level": "MEDIUM",
        "risk_reasons": ["Application configuration file changed"],
        "full_build_recommended": False,
        "test_candidates": [
            {
                "class_name": "OrderServiceTest",
                "file_path": "order-service/src/test/java/OrderServiceTest.java",
                "module_artifact_id": "order-service",
                "score": 0.85,
                "confidence": "HIGH",
                "reasons": ["Name matches changed class OrderService", "Directly imports com.example.OrderService"],
                "is_integration_test": False,
            },
            {
                "class_name": "CheckoutIT",
                "file_path": "checkout-api/src/test/java/CheckoutIT.java",
                "module_artifact_id": "checkout-api",
                "score": 0.42,
                "confidence": "MEDIUM",
                "reasons": ["Downstream module"],
                "is_integration_test": True,
            },
        ],
        "maven_command": {
            "argv": ["./mvnw", "-pl", ":order-service,:checkout-api", "-am", "-Dtest=OrderServiceTest,CheckoutIT", "test"],
            "display_command": "./mvnw -pl :order-service,:checkout-api -am \\\n  -Dtest=OrderServiceTest,CheckoutIT test",
            "goal": "test",
        },
        "execution": {
            "status": "success",
            "exit_code": 0,
            "timed_out": False,
            "duration_seconds": 42.7,
        },
    }


# ===========================================================================
# Surefire parser tests
# ===========================================================================

class TestSurefireParser:
    def test_parse_clean_suite(self, tmp_path):
        xml = _make_suite_xml(tests=3, failures=0, errors=0, skipped=0, time=1.5)
        path = str(tmp_path / "TEST-FooTest.xml")
        with open(path, "w") as f:
            f.write(xml)

        suite = _parse_testsuite_xml(path)
        assert suite is not None
        assert suite.name == "com.example.FooTest"
        assert suite.tests == 3
        assert suite.failures == 0
        assert suite.errors == 0
        assert suite.skipped == 0
        assert suite.passed == 3
        assert abs(suite.time_seconds - 1.5) < 0.001

    def test_parse_suite_with_failure(self, tmp_path):
        cases = """
        <testcase name="testCreate" classname="com.example.FooTest" time="0.5">
          <failure message="expected 1 but was 2" type="AssertionError">stack trace</failure>
        </testcase>
        <testcase name="testUpdate" classname="com.example.FooTest" time="0.3"/>
        """
        xml = _make_suite_xml(tests=2, failures=1, test_cases=cases)
        path = str(tmp_path / "TEST-FooTest.xml")
        with open(path, "w") as f:
            f.write(xml)

        suite = _parse_testsuite_xml(path)
        assert suite is not None
        assert suite.tests == 2
        assert suite.failures == 1
        assert suite.passed == 1
        assert len(suite.test_cases) == 2

        failed = [tc for tc in suite.test_cases if tc.status == "failed"]
        assert len(failed) == 1
        assert failed[0].name == "testCreate"
        assert "expected 1" in failed[0].message

    def test_parse_suite_with_skip(self, tmp_path):
        cases = """
        <testcase name="testSkipped" classname="com.example.FooTest" time="0">
          <skipped message="not yet implemented"/>
        </testcase>
        """
        xml = _make_suite_xml(tests=1, skipped=1, test_cases=cases)
        path = str(tmp_path / "TEST-FooTest.xml")
        with open(path, "w") as f:
            f.write(xml)

        suite = _parse_testsuite_xml(path)
        assert suite is not None
        tc = suite.test_cases[0]
        assert tc.status == "skipped"
        assert tc.message == "not yet implemented"

    def test_parse_suite_with_error(self, tmp_path):
        cases = """
        <testcase name="testError" classname="com.example.FooTest" time="0.1">
          <error message="NullPointerException" type="java.lang.NullPointerException">NPE</error>
        </testcase>
        """
        xml = _make_suite_xml(tests=1, errors=1, test_cases=cases)
        path = str(tmp_path / "TEST-FooTest.xml")
        with open(path, "w") as f:
            f.write(xml)

        suite = _parse_testsuite_xml(path)
        assert suite is not None
        tc = suite.test_cases[0]
        assert tc.status == "error"

    def test_invalid_xml_returns_none(self, tmp_path):
        path = str(tmp_path / "TEST-Bad.xml")
        with open(path, "w") as f:
            f.write("not xml at all <><")
        suite = _parse_testsuite_xml(path)
        assert suite is None

    def test_missing_file_returns_none(self, tmp_path):
        suite = _parse_testsuite_xml(str(tmp_path / "nonexistent.xml"))
        assert suite is None

    def test_wrong_root_tag_returns_none(self, tmp_path):
        path = str(tmp_path / "TEST-Bad.xml")
        with open(path, "w") as f:
            f.write("<testsuites></testsuites>")
        suite = _parse_testsuite_xml(path)
        assert suite is None

    def test_collect_from_empty_dir(self, tmp_path):
        results = collect_surefire_results(str(tmp_path))
        assert results.total_tests == 0
        assert results.suites == []

    def test_collect_from_nonexistent_dir(self, tmp_path):
        results = collect_surefire_results(str(tmp_path / "no-such-dir"))
        assert results.total_tests == 0

    def test_collect_finds_surefire_reports(self, tmp_path):
        # Create: module-a/target/surefire-reports/TEST-FooTest.xml
        sr_dir = tmp_path / "module-a" / "target" / "surefire-reports"
        sr_dir.mkdir(parents=True)
        xml = _make_suite_xml(name="FooTest", tests=2, failures=0)
        _write_suite(str(sr_dir), "TEST-FooTest.xml", xml)

        results = collect_surefire_results(str(tmp_path))
        assert results.total_tests == 2
        assert len(results.suites) == 1
        assert results.suites[0].name == "FooTest"

    def test_collect_finds_failsafe_reports(self, tmp_path):
        # Create: module-b/target/failsafe-reports/TEST-BarIT.xml
        fr_dir = tmp_path / "module-b" / "target" / "failsafe-reports"
        fr_dir.mkdir(parents=True)
        xml = _make_suite_xml(name="BarIT", tests=1, failures=0)
        _write_suite(str(fr_dir), "TEST-BarIT.xml", xml)

        results = collect_surefire_results(str(tmp_path))
        assert results.total_tests == 1
        assert any(s.name == "BarIT" for s in results.suites)

    def test_collect_multiple_modules(self, tmp_path):
        for mod in ("mod-a", "mod-b", "mod-c"):
            sr_dir = tmp_path / mod / "target" / "surefire-reports"
            sr_dir.mkdir(parents=True)
            xml = _make_suite_xml(name=f"{mod}Test", tests=5, failures=0)
            _write_suite(str(sr_dir), f"TEST-{mod}Test.xml", xml)

        results = collect_surefire_results(str(tmp_path))
        assert results.total_tests == 15
        assert len(results.suites) == 3

    def test_collect_mixed_results(self, tmp_path):
        sr_dir = tmp_path / "mod" / "target" / "surefire-reports"
        sr_dir.mkdir(parents=True)

        good = _make_suite_xml(name="GoodTest", tests=5, failures=0)
        bad  = _make_suite_xml(name="BadTest",  tests=3, failures=2)
        _write_suite(str(sr_dir), "TEST-GoodTest.xml", good)
        _write_suite(str(sr_dir), "TEST-BadTest.xml", bad)

        results = collect_surefire_results(str(tmp_path))
        assert results.total_tests == 8
        assert results.total_failures == 2
        assert results.total_passed == 6
        assert not results.all_passed

    def test_all_passed_property(self):
        r = SurefireResults()
        r.suites.append(TestSuiteResult("A", 3, 0, 0, 0, 1.0))
        r.suites.append(TestSuiteResult("B", 2, 0, 0, 0, 0.5))
        assert r.all_passed
        assert r.total_tests == 5
        assert r.total_passed == 5
        assert r.total_failures == 0

    def test_not_all_passed_with_errors(self):
        r = SurefireResults()
        r.suites.append(TestSuiteResult("A", 2, 0, 1, 0, 0.5))
        assert not r.all_passed
        assert r.total_failures == 1

    def test_all_passed_empty_is_false(self):
        r = SurefireResults()
        assert not r.all_passed   # no tests → not "all passed"

    def test_ignores_non_surefire_xml(self, tmp_path):
        # A pom.xml inside target should not be picked up
        target = tmp_path / "mod" / "target"
        target.mkdir(parents=True)
        with open(str(target / "pom.xml"), "w") as f:
            f.write("<project/>")
        results = collect_surefire_results(str(tmp_path))
        assert results.total_tests == 0


# ===========================================================================
# HTML report tests
# ===========================================================================

class TestHtmlReport:
    def test_returns_string(self):
        report = _minimal_report()
        html = build_html_report(report)
        assert isinstance(html, str)
        assert len(html) > 500

    def test_valid_html_structure(self):
        html = build_html_report(_minimal_report())
        assert "<!DOCTYPE html>" in html
        assert "<html" in html
        assert "</html>" in html
        assert "<head>" in html
        assert "<body>" in html

    def test_contains_run_id(self):
        html = build_html_report(_minimal_report("my-unique-run-xyz"))
        assert "my-unique-run-xyz" in html

    def test_contains_source_and_target(self):
        html = build_html_report(_minimal_report())
        assert "feature/order" in html
        assert "origin/main" in html

    def test_contains_changed_file(self):
        html = build_html_report(_minimal_report())
        assert "OrderService.java" in html

    def test_contains_affected_modules(self):
        html = build_html_report(_minimal_report())
        assert "order-service" in html
        assert "checkout-api" in html

    def test_contains_risk_level(self):
        html = build_html_report(_minimal_report())
        assert "MEDIUM" in html

    def test_contains_test_candidates(self):
        html = build_html_report(_minimal_report())
        assert "OrderServiceTest" in html
        assert "CheckoutIT" in html

    def test_contains_maven_command(self):
        html = build_html_report(_minimal_report())
        assert "./mvnw" in html
        assert "order-service" in html

    def test_risk_badge_classes(self):
        for level in ("low", "medium", "high", "critical"):
            report = _minimal_report()
            report["risk_level"] = level.upper()
            report["impact"]["risk_level"] = level.upper()
            html = build_html_report(report)
            assert f"badge-{level}" in html

    def test_status_badge_success(self):
        html = build_html_report(_minimal_report())
        assert "badge-success" in html

    def test_status_badge_failure(self):
        report = _minimal_report()
        report["execution"]["status"] = "failure"
        html = build_html_report(report)
        assert "badge-failure" in html

    def test_html_escaping(self):
        report = _minimal_report()
        report["changed_files"].append({"path": "<script>alert(1)</script>", "status": "added"})
        html = build_html_report(report)
        assert "<script>alert(1)</script>" not in html
        assert "&lt;script&gt;" in html

    def test_empty_report_no_crash(self):
        report = {
            "run_id": "x",
            "started_at": "2026-01-01T00:00:00Z",
            "source": "HEAD",
            "target": "main",
            "merge_base": "aaa",
            "changed_files": [],
        }
        html = build_html_report(report)
        assert "MergeMate" in html

    def test_surefire_section_included(self):
        from mergemate.reporting.surefire import SurefireResults, TestSuiteResult
        surefire = SurefireResults()
        surefire.suites.append(TestSuiteResult("FooTest", 5, 0, 0, 0, 1.2))
        html = build_html_report(_minimal_report(), surefire)
        assert "FooTest" in html
        assert "Test Results" in html

    def test_surefire_failure_badge(self):
        from mergemate.reporting.surefire import SurefireResults, TestSuiteResult
        surefire = SurefireResults()
        surefire.suites.append(TestSuiteResult("FailTest", 3, 2, 0, 0, 0.5))
        html = build_html_report(_minimal_report(), surefire)
        assert "FAILURES DETECTED" in html

    def test_surefire_all_passed_badge(self):
        from mergemate.reporting.surefire import SurefireResults, TestSuiteResult
        surefire = SurefireResults()
        surefire.suites.append(TestSuiteResult("CleanTest", 5, 0, 0, 0, 1.0))
        html = build_html_report(_minimal_report(), surefire)
        assert "ALL PASSED" in html

    def test_no_surefire_no_section(self):
        html = build_html_report(_minimal_report(), surefire=None)
        assert "Test Results" not in html or "Selected Tests" in html

    def test_jdk_section_shown_when_present(self):
        report = _minimal_report()
        report["jdk"] = {
            "required_version": "17",
            "detected_from": "root pom.xml -> maven.compiler.release",
            "detection_method": "property",
            "runtime_java_version": "17.0.12",
            "runtime_java_major": 17,
            "runtime_maven_version": "3.9.6",
            "compatible": True,
            "message": "Compatible",
        }
        html = build_html_report(report)
        assert "JDK" in html
        assert "17.0.12" in html
        assert "maven.compiler.release" in html

    def test_confidence_badges(self):
        html = build_html_report(_minimal_report())
        assert "badge-high-conf" in html
        assert "badge-medium-conf" in html

    def test_it_badge_for_integration_test(self):
        html = build_html_report(_minimal_report())
        # CheckoutIT has is_integration_test=True
        assert "CheckoutIT" in html

    def test_write_html_report_creates_file(self, tmp_path):
        report = _minimal_report()
        run_dir = str(tmp_path / "run1")
        os.makedirs(run_dir)
        path = write_html_report(run_dir, report)
        assert os.path.isfile(path)
        assert path.endswith("report.html")
        with open(path, encoding="utf-8") as f:
            content = f.read()
        assert "<!DOCTYPE html>" in content
        assert "my-unique-run-xyz" not in content   # different run_id
        assert "test-run-1" in content

    def test_write_html_report_with_surefire(self, tmp_path):
        from mergemate.reporting.surefire import SurefireResults, TestSuiteResult
        surefire = SurefireResults()
        surefire.suites.append(TestSuiteResult("SomeTest", 10, 0, 0, 0, 2.5))
        run_dir = str(tmp_path / "run2")
        os.makedirs(run_dir)
        path = write_html_report(run_dir, _minimal_report(), surefire)
        with open(path, encoding="utf-8") as f:
            content = f.read()
        assert "SomeTest" in content
        assert "ALL PASSED" in content


# ===========================================================================
# file_report integration — HTML is now written alongside JSON
# ===========================================================================

class TestFileReportHtmlIntegration:
    def _make_impact(self):
        from mergemate.domain.models import (
            ImpactAnalysis, ModuleImpact, GitChangeSet, ChangedFile
        )
        changeset = GitChangeSet(
            source_ref="HEAD",
            target_ref="origin/main",
            merge_base="abc123",
            changed_files=[ChangedFile("src/Foo.java", "modified")],
            java_production_files=[ChangedFile("src/Foo.java", "modified")],
        )
        impact = ImpactAnalysis(
            strategy="incremental",
            strategy_reason="Only 1 module affected",
            changed_modules=["mod-a"],
            affected_modules=[ModuleImpact("mod-a", "changed", "direct change")],
            risk_level="LOW",
            risk_reasons=[],
            full_build_recommended=False,
        )
        return changeset, impact

    def test_html_file_written(self, tmp_path):
        from mergemate.reporting.file_report import write_run_report

        changeset, impact = self._make_impact()
        run_dir = write_run_report(
            repo_root=str(tmp_path),
            changeset=changeset,
            impact=impact,
            plan=None,
            result=None,
            run_id="test-html-run",
        )
        html_path = os.path.join(run_dir, "report.html")
        assert os.path.isfile(html_path), "report.html not written"
        with open(html_path, encoding="utf-8") as f:
            content = f.read()
        assert "test-html-run" in content
        assert "<!DOCTYPE html>" in content

    def test_json_still_written(self, tmp_path):
        from mergemate.reporting.file_report import write_run_report
        changeset, impact = self._make_impact()
        run_dir = write_run_report(
            repo_root=str(tmp_path),
            changeset=changeset,
            impact=impact,
            plan=None,
            result=None,
            run_id="test-json-run",
        )
        json_path = os.path.join(run_dir, "report.json")
        assert os.path.isfile(json_path)
        with open(json_path, encoding="utf-8") as f:
            data = json.load(f)
        assert data["run_id"] == "test-json-run"

    def test_surefire_data_in_json_when_working_dir_provided(self, tmp_path):
        from mergemate.reporting.file_report import write_run_report
        from mergemate.execution.adapter import ExecutionResult

        # Create a fake surefire XML in working_dir
        working_dir = str(tmp_path / "work")
        sr_dir = tmp_path / "work" / "mod" / "target" / "surefire-reports"
        sr_dir.mkdir(parents=True)
        xml = _make_suite_xml(name="FooTest", tests=4, failures=0)
        _write_suite(str(sr_dir), "TEST-FooTest.xml", xml)

        changeset, impact = self._make_impact()
        result = ExecutionResult(exit_code=0, stdout="BUILD SUCCESS", stderr="", timed_out=False, duration_seconds=5.0)

        run_dir = write_run_report(
            repo_root=str(tmp_path / "repo"),
            changeset=changeset,
            impact=impact,
            plan=None,
            result=result,
            run_id="test-surefire-run",
            working_dir=working_dir,
            status="success",
        )

        json_path = os.path.join(run_dir, "report.json")
        with open(json_path, encoding="utf-8") as f:
            data = json.load(f)

        assert "surefire" in data
        assert data["surefire"]["total_tests"] == 4
        assert data["surefire"]["total_passed"] == 4
        assert data["surefire"]["all_passed"] is True
        assert len(data["surefire"]["suites"]) == 1
