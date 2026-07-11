"""
forge_analysis/analyzer.py

FailureAnalyzer: stable interface for failure analysis.

Current implementation: heuristic pattern matching.
Future: can be swapped for ML/LLM without changing callers.
"""

from __future__ import annotations

from forge_analysis.failure_summary import FailureSummary
from forge_analysis.patterns import (
    classify_build_failure,
    extract_failed_module,
    find_compilation_errors,
    find_dependency_errors,
    find_test_failures,
)

# Suggested actions per category
_SUGGESTED_ACTIONS: dict[str, str] = {
    "compilation_error": "Fix compilation errors in the affected module and re-run.",
    "test_failure": "Investigate failing tests in the affected module.",
    "dependency_error": "Check that all Maven dependencies are available in your artifact repository.",
    "unknown": "Examine the lifecycle log for more details.",
}


class FailureAnalyzer:
    """
    Stable interface for failure analysis.

    Current implementation: heuristic pattern matching.
    Future: can be swapped for ML/LLM without changing callers.
    """

    def analyze(
        self,
        run_id: str,
        status: str,
        lifecycle_log: list[str],
        has_conflicts: bool | None = None,
        conflict_files: list[str] | None = None,
        error_message: str | None = None,
    ) -> FailureSummary:
        """
        Analyze a validation run and return a structured failure summary.

        Returns a FailureSummary with category="unknown" for non-failure runs
        (status="success"), but still returns a valid object (confidence=0.0,
        no evidence).
        """
        conflict_files = conflict_files or []

        # 1. Merge conflict
        if has_conflicts is True:
            return FailureSummary(
                run_id=run_id,
                category="merge_conflict",
                probable_root_cause=(
                    f"Merge conflict detected between branches. "
                    f"Conflicting files: {conflict_files}"
                ),
                affected_module=None,
                confidence=0.95,
                evidence=list(conflict_files),
                suggested_action=(
                    "Resolve merge conflicts locally before re-running validation."
                ),
            )

        # 2. Infrastructure/error with message
        if status == "error" and error_message:
            return FailureSummary(
                run_id=run_id,
                category="unknown",
                probable_root_cause=f"Validation infrastructure error: {error_message}",
                affected_module=None,
                confidence=0.5,
                evidence=[error_message],
                suggested_action=(
                    "Check infrastructure (Docker, network, SSH key) and retry."
                ),
            )

        # 3. Failure or error with lifecycle log
        if status in ("failure", "error") and lifecycle_log:
            # If there's also an error_message and no useful pattern, prefer
            # infrastructure error classification (status==error only).
            # But if we have log lines, run full pattern matching first.
            category, confidence = classify_build_failure(lifecycle_log)

            # Gather evidence from all relevant pattern matchers
            evidence: list[str] = []
            evidence.extend(find_compilation_errors(lifecycle_log))
            evidence.extend(find_test_failures(lifecycle_log))
            evidence.extend(find_dependency_errors(lifecycle_log))
            # Deduplicate while preserving order
            seen: set[str] = set()
            unique_evidence: list[str] = []
            for item in evidence:
                if item not in seen:
                    seen.add(item)
                    unique_evidence.append(item)

            affected_module = extract_failed_module(lifecycle_log)

            # Build probable_root_cause
            evidence_count = len(unique_evidence)
            probable_root_cause = (
                f"Build failed with category '{category}'. "
                f"Found {evidence_count} relevant log line(s)."
            )

            suggested_action = _SUGGESTED_ACTIONS.get(
                category, _SUGGESTED_ACTIONS["unknown"]
            )

            return FailureSummary(
                run_id=run_id,
                category=category,  # type: ignore[arg-type]
                probable_root_cause=probable_root_cause,
                affected_module=affected_module,
                confidence=confidence,
                evidence=unique_evidence,
                suggested_action=suggested_action,
            )

        # 4. Success or no log — no failure
        return FailureSummary(
            run_id=run_id,
            category="unknown",
            probable_root_cause="No failure detected.",
            affected_module=None,
            confidence=0.0,
            evidence=[],
            suggested_action="",
        )
