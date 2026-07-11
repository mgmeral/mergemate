"""
forge_analysis/failure_summary.py

FailureSummary dataclass: the stable interface for structured failure analysis.

This is the public contract — the heuristic implementation behind it can be
replaced by ML/LLM analysis later without changing callers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass
class FailureSummary:
    """
    Structured failure analysis output.

    This is the stable interface — the heuristic implementation behind it
    can be replaced by ML/LLM analysis later without changing callers.
    """

    run_id: str
    category: Literal[
        "merge_conflict",
        "build_failure",
        "test_failure",
        "compilation_error",
        "dependency_error",
        "unknown",
    ]
    probable_root_cause: str       # human-readable explanation
    affected_module: str | None    # artifactId if identifiable, else None
    confidence: float              # 0.0 – 1.0
    evidence: list[str]            # snippets from logs that led to this conclusion
    suggested_action: str          # one concrete next step for the developer
    metadata: dict = field(default_factory=dict)  # extra structured data
