"""
forge_worker: Worker Safety Spine for MergeMate.

Provides the git guard (allow-list enforcement) and the validation lifecycle
(clone → fetch → checkout → merge-check → diff → build).
"""

from forge_worker.git_guard import GuardResult, check
from forge_worker.lifecycle import (
    GuardViolationError,
    LifecycleConfig,
    ValidationResult,
)

__all__ = [
    "GuardResult",
    "check",
    "GuardViolationError",
    "LifecycleConfig",
    "ValidationResult",
]
