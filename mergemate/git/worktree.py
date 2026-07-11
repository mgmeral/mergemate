import subprocess
import tempfile
import os
import shutil
from contextlib import contextmanager


class WorktreeError(Exception):
    pass


class TemporaryWorktree:
    """
    Creates a temporary git worktree at a temp directory, checked out to source_ref.

    Usage:
        with TemporaryWorktree(repo_dir, "HEAD") as worktree_path:
            # do work in worktree_path
        # cleaned up automatically
    """

    def __init__(self, repo_dir: str, source_ref: str):
        self.repo_dir = os.path.abspath(repo_dir)
        self.source_ref = source_ref
        self._worktree_path: str | None = None

    def __enter__(self) -> str:
        """Create the worktree. Returns the path to the worktree directory."""
        tmp = tempfile.mkdtemp(prefix="mergemate-wt-")
        try:
            subprocess.run(
                ["git", "worktree", "add", "--detach", tmp, self.source_ref],
                cwd=self.repo_dir,
                check=True,
                capture_output=True,
                text=True,
            )
            self._worktree_path = tmp
            return tmp
        except subprocess.CalledProcessError as e:
            shutil.rmtree(tmp, ignore_errors=True)
            raise WorktreeError(f"Failed to create worktree: {e.stderr}") from e

    def __exit__(self, *_) -> None:
        """Always clean up — even on exception."""
        self._cleanup()

    def _cleanup(self) -> None:
        if self._worktree_path is None:
            return
        path = self._worktree_path
        self._worktree_path = None
        try:
            subprocess.run(
                ["git", "worktree", "remove", "--force", path],
                cwd=self.repo_dir,
                capture_output=True,
                text=True,
            )
        except Exception:
            pass
        shutil.rmtree(path, ignore_errors=True)


@contextmanager
def temporary_worktree(repo_dir: str, source_ref: str):
    """Context manager wrapper for TemporaryWorktree."""
    wt = TemporaryWorktree(repo_dir, source_ref)
    path = wt.__enter__()
    try:
        yield path
    finally:
        wt.__exit__(None, None, None)
