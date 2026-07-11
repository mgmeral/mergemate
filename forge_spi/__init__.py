"""
forge_spi: Plugin SPI (Service Provider Interface) for MergeMate validation steps.

Provides the minimal contract (ValidationStep ABC), context and result dataclasses,
plus reference implementations for Git and Maven.
"""

from forge_spi.context import StepContext
from forge_spi.result import StepResult
from forge_spi.step import ValidationStep

__all__ = [
    "StepContext",
    "StepResult",
    "ValidationStep",
]
