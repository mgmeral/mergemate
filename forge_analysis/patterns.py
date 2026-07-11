"""
forge_analysis/patterns.py

Pattern-matching rules for failure analysis.
All pure functions — no side effects, no I/O.
"""

from __future__ import annotations

import re


def find_compilation_errors(log_lines: list[str]) -> list[str]:
    """Extract lines containing 'error:' (javac) or 'ERROR' from Maven output."""
    # Dependency-specific markers that should NOT be classified as compilation errors
    _dependency_markers = ("Could not resolve", "not found", "Artifact")

    results = []
    for line in log_lines:
        if "error:" in line or "ERROR" in line:
            # Exclude lines that are clearly about dependency resolution
            if any(marker in line for marker in _dependency_markers):
                continue
            results.append(line)
    return results


def find_test_failures(log_lines: list[str]) -> list[str]:
    """Extract lines containing 'FAILED', 'Tests run:' with failures > 0, or 'BUILD FAILURE'."""
    results = []
    for line in log_lines:
        if "FAILED" in line or "BUILD FAILURE" in line:
            results.append(line)
            continue
        # Match "Tests run: N, Failures: M" where M > 0
        if "Tests run:" in line:
            # Look for Failures: followed by a non-zero number
            match = re.search(r"Failures:\s*(\d+)", line)
            if match and int(match.group(1)) > 0:
                results.append(line)
                continue
            # Also check Errors: > 0
            match = re.search(r"Errors:\s*(\d+)", line)
            if match and int(match.group(1)) > 0:
                results.append(line)
    return results


def find_dependency_errors(log_lines: list[str]) -> list[str]:
    """Extract lines about missing artifacts: 'Could not resolve', 'Artifact', 'not found'."""
    results = []
    for line in log_lines:
        if "Could not resolve" in line or "not found" in line:
            results.append(line)
            continue
        if "Artifact" in line and ("missing" in line or "not found" in line or "Could not" in line):
            results.append(line)
    return results


def find_conflict_markers(log_lines: list[str]) -> list[str]:
    """Extract lines containing '<<<<<<', '>>>>>>>', '======='."""
    results = []
    for line in log_lines:
        if "<<<<<<<" in line or ">>>>>>>" in line or "=======" in line:
            results.append(line)
    return results


def extract_failed_module(log_lines: list[str]) -> str | None:
    """
    Try to extract the Maven module name from lines like:
    '[ERROR] Failed to execute goal ... in project <artifactId>'
    Returns the artifactId string or None.
    """
    pattern = re.compile(r"\[ERROR\].*Failed to execute goal.*on project\s+(\S+)")
    for line in log_lines:
        match = pattern.search(line)
        if match:
            # Strip trailing punctuation (e.g., colon at end)
            artifact_id = match.group(1).rstrip(":;,.")
            return artifact_id
    return None


def classify_build_failure(log_lines: list[str]) -> tuple[str, float]:
    """
    Returns (category, confidence) based on pattern matching:
    - If conflict markers found: ("merge_conflict", 0.95)
    - Elif compilation errors found: ("compilation_error", 0.85)
    - Elif test failure lines found: ("test_failure", 0.80)
    - Elif dependency errors found: ("dependency_error", 0.75)
    - Else: ("unknown", 0.3)
    """
    if find_conflict_markers(log_lines):
        return ("merge_conflict", 0.95)
    if find_compilation_errors(log_lines):
        return ("compilation_error", 0.85)
    if find_test_failures(log_lines):
        return ("test_failure", 0.80)
    if find_dependency_errors(log_lines):
        return ("dependency_error", 0.75)
    return ("unknown", 0.3)
