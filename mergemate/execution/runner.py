"""
Command runner — runs a MavenCommand via an ExecutionAdapter and captures output.
"""
from __future__ import annotations

from mergemate.domain.models import MavenCommand
from mergemate.execution.adapter import ExecutionAdapter, ExecutionResult


class CommandRunner:
    """
    Runs a MavenCommand via an ExecutionAdapter.
    Optionally streams stdout to terminal while also capturing it.
    """

    def __init__(
        self,
        adapter: ExecutionAdapter,
        stream_output: bool = True,
    ):
        self.adapter = adapter
        self.stream_output = stream_output

    def run(
        self,
        command: MavenCommand,
        working_dir: str,
        timeout_s: int = 3600,
        env: dict | None = None,
    ) -> ExecutionResult:
        """
        Run the Maven command.
        If stream_output=True, print each line as it arrives (best-effort via subprocess).

        Note: current ExecutionAdapter.execute() captures output then returns.
        For now, just call adapter.execute() and optionally print stdout/stderr after.
        Real streaming can be added later.
        """
        result = self.adapter.execute(
            argv=command.argv,
            working_dir=working_dir,
            timeout_s=timeout_s,
            env=env,
        )

        if self.stream_output and result.stdout:
            print(result.stdout, end="")

        return result
