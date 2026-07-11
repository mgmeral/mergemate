"""
forge_spi/plugins/maven_plugin.py

Maven reference implementation of ValidationStep.

Provides:
  - MavenBuildStep: runs the Maven build command from ctx.maven_command
"""

from __future__ import annotations

import time

from forge_spi.context import StepContext
from forge_spi.result import StepResult
from forge_spi.step import ValidationStep


class MavenBuildStep(ValidationStep):
    """
    Runs the Maven build command supplied via StepContext.maven_command.

    Skipped entirely when maven_command is None (can_run returns False).
    """

    @property
    def name(self) -> str:
        return "maven-build"

    def can_run(self, ctx: StepContext) -> bool:
        """Skip this step when no maven command has been computed."""
        return ctx.maven_command is not None

    def run(self, ctx: StepContext) -> StepResult:
        start = time.monotonic()

        # Split the command string into argv tokens.
        argv = ctx.maven_command.split()  # type: ignore[union-attr]

        try:
            rc, out, err = ctx.runner(argv, ctx.work_dir)
        except Exception as exc:
            return StepResult(
                step_name=self.name,
                success=False,
                output=str(exc),
                duration_seconds=time.monotonic() - start,
                metadata={"exit_code": -1, "maven_command": ctx.maven_command},
            )

        combined = out + err
        return StepResult(
            step_name=self.name,
            success=(rc == 0),
            output=combined,
            duration_seconds=time.monotonic() - start,
            metadata={"exit_code": rc, "maven_command": ctx.maven_command},
        )
