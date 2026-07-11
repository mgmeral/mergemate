"""
forge_spi/result.py

StepResult — the outcome of a single validation step.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class StepResult:
    """The outcome of a single validation step."""

    step_name: str
    success: bool
    output: str                  # combined stdout/stderr or summary
    duration_seconds: float
    metadata: dict               # step-specific structured data

    # Well-known metadata keys (optional, used by UI/analysis):
    # "changed_files": list[str]
    # "conflict_files": list[str]
    # "has_conflicts": bool
    # "exit_code": int
    # "maven_command": str
