import subprocess
import time
import os
from mergemate.execution.adapter import ExecutionAdapter, ExecutionResult
from mergemate.git.worktree import TemporaryWorktree


class LocalWorktreeAdapter(ExecutionAdapter):
    """
    Default execution adapter.
    Creates a temporary git worktree, runs commands there,
    cleans up on exit. Uses the user's local Maven, JDK, .m2.
    """

    def __init__(self, repo_dir: str):
        self.repo_dir = repo_dir
        self._worktree: TemporaryWorktree | None = None
        self._worktree_path: str | None = None

    def prepare(self, project_dir: str, source_ref: str) -> str:
        self._worktree = TemporaryWorktree(project_dir, source_ref)
        self._worktree_path = self._worktree.__enter__()
        return self._worktree_path

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
        if self._worktree:
            self._worktree.__exit__(None, None, None)
            self._worktree = None
            self._worktree_path = None
