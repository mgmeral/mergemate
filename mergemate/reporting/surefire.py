"""
Surefire/Failsafe XML report parser.

Collects Maven test results from target/surefire-reports/ and
target/failsafe-reports/ directories after a Maven run.
"""
from __future__ import annotations

import os
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field


@dataclass
class TestCaseResult:
    name: str
    classname: str
    time_seconds: float
    status: str          # "passed", "failed", "error", "skipped"
    message: str | None = None   # failure/error message


@dataclass
class TestSuiteResult:
    name: str
    tests: int
    failures: int
    errors: int
    skipped: int
    time_seconds: float
    test_cases: list[TestCaseResult] = field(default_factory=list)

    @property
    def passed(self) -> int:
        return self.tests - self.failures - self.errors - self.skipped


@dataclass
class SurefireResults:
    suites: list[TestSuiteResult] = field(default_factory=list)

    @property
    def total_tests(self) -> int:
        return sum(s.tests for s in self.suites)

    @property
    def total_failures(self) -> int:
        return sum(s.failures + s.errors for s in self.suites)

    @property
    def total_skipped(self) -> int:
        return sum(s.skipped for s in self.suites)

    @property
    def total_passed(self) -> int:
        return sum(s.passed for s in self.suites)

    @property
    def total_time(self) -> float:
        return sum(s.time_seconds for s in self.suites)

    @property
    def all_passed(self) -> bool:
        return self.total_failures == 0 and self.total_tests > 0


def collect_surefire_results(working_dir: str) -> SurefireResults:
    """
    Walk working_dir looking for surefire/failsafe report XML files.

    Searches:
      <module>/target/surefire-reports/TEST-*.xml
      <module>/target/failsafe-reports/TEST-*.xml
    """
    results = SurefireResults()
    if not os.path.isdir(working_dir):
        return results

    report_dirs = _find_report_dirs(working_dir)
    for report_dir in report_dirs:
        _parse_report_dir(report_dir, results)

    return results


def _find_report_dirs(root: str) -> list[str]:
    """Find all surefire-reports and failsafe-reports directories under root."""
    found: list[str] = []
    try:
        for dirpath, dirnames, _ in os.walk(root):
            # Skip common non-source directories to keep walk fast
            dirnames[:] = [
                d for d in dirnames
                if d not in {".git", ".mergemate", "node_modules", ".idea"}
            ]
            base = os.path.basename(dirpath)
            if base in ("surefire-reports", "failsafe-reports"):
                # Must be under a 'target' directory
                parent = os.path.basename(os.path.dirname(dirpath))
                if parent == "target":
                    found.append(dirpath)
    except PermissionError:
        pass
    return found


def _parse_report_dir(report_dir: str, results: SurefireResults) -> None:
    """Parse all TEST-*.xml files in report_dir into results."""
    try:
        entries = os.listdir(report_dir)
    except PermissionError:
        return

    for filename in entries:
        if filename.startswith("TEST-") and filename.endswith(".xml"):
            path = os.path.join(report_dir, filename)
            suite = _parse_testsuite_xml(path)
            if suite is not None:
                results.suites.append(suite)


def _parse_testsuite_xml(path: str) -> TestSuiteResult | None:
    """Parse a single surefire/failsafe TEST-*.xml file."""
    try:
        tree = ET.parse(path)
    except (ET.ParseError, OSError):
        return None

    root = tree.getroot()
    if root.tag != "testsuite":
        return None

    def _int(attr: str) -> int:
        try:
            return int(root.get(attr, "0") or "0")
        except ValueError:
            return 0

    def _float(attr: str) -> float:
        try:
            return float(root.get(attr, "0") or "0")
        except ValueError:
            return 0.0

    suite = TestSuiteResult(
        name=root.get("name", "unknown"),
        tests=_int("tests"),
        failures=_int("failures"),
        errors=_int("errors"),
        skipped=_int("skipped"),
        time_seconds=_float("time"),
    )

    for tc in root.findall("testcase"):
        suite.test_cases.append(_parse_testcase(tc))

    return suite


def _parse_testcase(tc: ET.Element) -> TestCaseResult:
    name = tc.get("name", "")
    classname = tc.get("classname", "")
    try:
        time_seconds = float(tc.get("time", "0") or "0")
    except ValueError:
        time_seconds = 0.0

    failure = tc.find("failure")
    error = tc.find("error")
    skipped = tc.find("skipped")

    if failure is not None:
        status = "failed"
        message = failure.get("message") or (failure.text or "").strip()[:200]
    elif error is not None:
        status = "error"
        message = error.get("message") or (error.text or "").strip()[:200]
    elif skipped is not None:
        status = "skipped"
        message = skipped.get("message")
    else:
        status = "passed"
        message = None

    return TestCaseResult(
        name=name,
        classname=classname,
        time_seconds=time_seconds,
        status=status,
        message=message,
    )
