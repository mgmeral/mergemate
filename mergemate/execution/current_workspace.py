import subprocess
import time
import os
from mergemate.execution.adapter import ExecutionAdapter, ExecutionResult


class CurrentWorkspaceAdapter(ExecutionAdapter):
    """
    Runs commands directly in the current working directory.
    WARNING: Does not isolate from the user's working copy.
    Use only when explicitly requested.
    """

    def __init__(self):
        self._working_dir: str | None = None

    def prepare(self, project_dir: str, source_ref: str) -> str:
        self._working_dir = project_dir
        return project_dir

    def execute(self, argv, working_dir, timeout_s=3600, env=None) -> ExecutionResult:
        start = time.monotonic()
        effective_env = {**os.environ, **(env or {})}
        try:
            result = subprocess.run(
                argv,
                cwd=working_dir,
                capture_output=True,
                text=True,
                timeout=timeout_s,
                env=effective_env,
            )
            duration = time.monotonic() - start
            return ExecutionResult(
                exit_code=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
                timed_out=False,
                duration_seconds=duration,
            )
        except subprocess.TimeoutExpired as e:
            duration = time.monotonic() - start
            return ExecutionResult(
                exit_code=-1,
                stdout=e.stdout or "",
                stderr=e.stderr or "",
                timed_out=True,
                duration_seconds=duration,
            )

    def cleanup(self) -> None:
        pass   # nothing to clean up
