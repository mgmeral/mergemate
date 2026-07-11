"""
forge_analysis

Failure analysis package for MergeMate.
Provides structured failure summaries from heuristic pattern matching.
"""

from forge_analysis.failure_summary import FailureSummary
from forge_analysis.analyzer import FailureAnalyzer

__all__ = ["FailureSummary", "FailureAnalyzer"]
