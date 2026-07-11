"""
forge_spi/step.py

ValidationStep — abstract base class defining the plugin contract.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from forge_spi.context import StepContext
from forge_spi.result import StepResult


class ValidationStep(ABC):
    """
    Minimal contract for a validation step.

    A ValidationStep is stateless — it receives all context via StepContext.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable step name, e.g. 'git-merge-check'."""

    @abstractmethod
    def run(self, ctx: StepContext) -> StepResult:
        """
        Execute the step.

        Must not raise — catch exceptions and return StepResult(success=False, ...).
        """

    def can_run(self, ctx: StepContext) -> bool:
        """
        Optional guard: return False to skip this step.
        Default: always run.
        """
        return True
