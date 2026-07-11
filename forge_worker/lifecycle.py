"""
forge_worker/lifecycle.py

Validation Lifecycle — clone → fetch → checkout → merge-check → diff → build.

Every git command is checked through git_guard before execution.
Accepts an injectable runner for testing without real git.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from typing import Callable

from forge_worker.git_guard import check as guard_check


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class GuardViolationError(Exception):
    """Raised when the git guard rejects a command."""
    pass


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class LifecycleConfig:
    remote_url: str
    feature_branch: str
    target_branch: str
    work_dir: str  # directory inside the worker where the repo is cloned


@dataclass
class ValidationResult:
    has_conflicts: bool
    changed_files: list[str]
    conflict_files: list[str]
    maven_command: str | None  # None if conflicts found (skip build)
    lifecycle_log: list[str]   # ordered log of each step


# ---------------------------------------------------------------------------
# Type alias for the injectable runner
# ---------------------------------------------------------------------------
# runner(argv, cwd) -> (returncode, stdout, stderr)
Runner = Callable[[list[str], str], tuple[int, str, str]]


# ---------------------------------------------------------------------------
# Default runner using real subprocess
# ---------------------------------------------------------------------------

def _real_runner(argv: list[str], cwd: str) -> tuple[int, str, str]:
    result = subprocess.run(
        argv,
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    return result.returncode, result.stdout, result.stderr


# ---------------------------------------------------------------------------
# Lifecycle implementation
# ---------------------------------------------------------------------------

class ValidationLifecycle:
    """
    Runs the validation sequence for a feature branch merge-check.

    Parameters
    ----------
    config:
        LifecycleConfig describing the remote, branches, and working directory.
    maven_command:
        The Maven command to run as the build step (e.g. from an ExecutionPlan).
        Pass None to skip the build step.
    runner:
        Optional injectable runner callable. If None, uses real subprocess.
    """

    def __init__(
        self,
        config: LifecycleConfig,
        maven_command: str | None = None,
        runner: Runner | None = None,
    ) -> None:
        self._config = config
        self._maven_command = maven_command
        self._runner: Runner = runner if runner is not None else _real_runner
        self._log: list[str] = []

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _run(self, argv: list[str], cwd: str | None = None) -> tuple[int, str, str]:
        """Guard-check then execute argv, logging the step."""
        result = guard_check(argv)
        if not result.allowed:
            raise GuardViolationError(
                f"Guard rejected command {argv!r}: {result.reason}"
            )
        effective_cwd = cwd if cwd is not None else self._config.work_dir
        self._log.append(f"RUN {' '.join(argv)}")
        return self._runner(argv, effective_cwd)

    # ------------------------------------------------------------------
    # Lifecycle steps
    # ------------------------------------------------------------------

    def _step_clone(self) -> None:
        """Step 1: Clone the remote into work_dir."""
        cfg = self._config
        argv = ["git", "clone", "--depth", "1", cfg.remote_url, cfg.work_dir]
        rc, stdout, stderr = self._run(argv, cwd=".")
        self._log.append(f"clone: rc={rc}")
        if rc != 0:
            raise RuntimeError(f"git clone failed (rc={rc}): {stderr}")

    def _step_fetch(self) -> None:
        """Step 2: Fetch the feature branch from origin."""
        cfg = self._config
        argv = ["git", "fetch", "origin", cfg.feature_branch]
        rc, stdout, stderr = self._run(argv)
        self._log.append(f"fetch: rc={rc}")
        if rc != 0:
            raise RuntimeError(f"git fetch failed (rc={rc}): {stderr}")

    def _step_checkout(self) -> None:
        """Step 3: Check out the feature branch."""
        cfg = self._config
        argv = ["git", "checkout", cfg.feature_branch]
        rc, stdout, stderr = self._run(argv)
        self._log.append(f"checkout: rc={rc}")
        if rc != 0:
            raise RuntimeError(f"git checkout failed (rc={rc}): {stderr}")

    def _step_merge_check(self) -> tuple[bool, list[str]]:
        """
        Step 4: Attempt a no-commit merge to detect conflicts.

        Returns (has_conflicts, conflict_files).
        Always aborts the merge afterwards.
        """
        cfg = self._config
        merge_argv = [
            "git", "merge", "--no-commit", f"origin/{cfg.target_branch}",
        ]
        rc, stdout, stderr = self._run(merge_argv)
        self._log.append(f"merge-check: rc={rc}")

        has_conflicts = False
        conflict_files: list[str] = []

        # git merge --no-commit exits with 0 even on conflict but sets
        # MERGE_HEAD; rc != 0 or "CONFLICT" in output indicates conflict.
        combined = stdout + "\n" + stderr
        if rc != 0 or "CONFLICT" in combined:
            has_conflicts = True
            # Extract conflict file paths from output lines like:
            # "CONFLICT (content): Merge conflict in path/to/file"
            for line in combined.splitlines():
                if "CONFLICT" in line and "Merge conflict in" in line:
                    parts = line.split("Merge conflict in", 1)
                    if len(parts) == 2:
                        conflict_files.append(parts[1].strip())

        # Always abort after the merge-check.
        abort_argv = ["git", "merge", "--abort"]
        abort_rc, _, _ = self._run(abort_argv)
        self._log.append(f"merge-abort: rc={abort_rc}")

        return has_conflicts, conflict_files

    def _step_diff(self) -> list[str]:
        """Step 5: List files changed between HEAD and origin/<target_branch>."""
        cfg = self._config
        argv = [
            "git", "diff", "--name-only",
            "HEAD", f"origin/{cfg.target_branch}",
        ]
        rc, stdout, stderr = self._run(argv)
        self._log.append(f"diff: rc={rc}")
        if rc != 0:
            raise RuntimeError(f"git diff failed (rc={rc}): {stderr}")

        changed_files = [line.strip() for line in stdout.splitlines() if line.strip()]
        return changed_files

    def _step_build(self, maven_command: str) -> None:
        """Step 6: Execute the Maven build command."""
        self._log.append(f"build: {maven_command}")
        # The build step runs the Maven command as provided; this is not a git
        # command so it does not go through the git guard.
        parts = maven_command.split()
        rc, stdout, stderr = self._runner(parts, self._config.work_dir)
        self._log.append(f"build: rc={rc}")
        if rc != 0:
            raise RuntimeError(f"build failed (rc={rc}): {stderr}")

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def run(self) -> ValidationResult:
        """
        Execute the full validation lifecycle in order:
          1. clone
          2. fetch
          3. checkout
          4. merge-check (+ merge-abort)
          5. diff
          6. build (skipped if conflicts)

        Returns a ValidationResult.
        """
        self._log.clear()

        # Step 1
        self._log.append("step: clone")
        self._step_clone()

        # Step 2
        self._log.append("step: fetch")
        self._step_fetch()

        # Step 3
        self._log.append("step: checkout")
        self._step_checkout()

        # Step 4
        self._log.append("step: merge-check")
        has_conflicts, conflict_files = self._step_merge_check()

        # Step 5
        self._log.append("step: diff")
        changed_files = self._step_diff()

        # Step 6
        maven_cmd: str | None = None
        if not has_conflicts and self._maven_command is not None:
            self._log.append("step: build")
            self._step_build(self._maven_command)
            maven_cmd = self._maven_command
        elif has_conflicts:
            self._log.append("step: build skipped (conflicts detected)")
            maven_cmd = None
        else:
            self._log.append("step: build skipped (no maven command)")
            maven_cmd = None

        return ValidationResult(
            has_conflicts=has_conflicts,
            changed_files=changed_files,
            conflict_files=conflict_files,
            maven_command=maven_cmd,
            lifecycle_log=list(self._log),
        )


# ---------------------------------------------------------------------------
# Convenience function
# ---------------------------------------------------------------------------

def run_validation(
    config: LifecycleConfig,
    maven_command: str | None = None,
    runner: Runner | None = None,
) -> ValidationResult:
    """
    Convenience wrapper around ValidationLifecycle.run().

    Parameters
    ----------
    config:
        LifecycleConfig describing remote, branches, and working directory.
    maven_command:
        Optional Maven command to run as the build step.
    runner:
        Optional injectable runner. None = real subprocess.
    """
    lifecycle = ValidationLifecycle(config, maven_command=maven_command, runner=runner)
    return lifecycle.run()
