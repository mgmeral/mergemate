"""
forge_spi/plugins/git_plugin.py

Git reference implementations of ValidationStep.

Provides two steps:
  - GitCloneFetchStep: clones the remote and fetches the feature branch
  - GitMergeCheckStep: attempts a no-commit merge to detect conflicts
"""

from __future__ import annotations

import time

from forge_worker.git_guard import check as guard_check
from forge_spi.context import StepContext
from forge_spi.result import StepResult
from forge_spi.step import ValidationStep


def _guard_and_run(
    argv: list[str],
    ctx: StepContext,
    cwd: str | None = None,
) -> tuple[bool, str, int, str, str]:
    """
    Guard-check argv, then run it via ctx.runner.

    Returns (guard_ok, guard_reason, rc, stdout, stderr).
    If the guard rejects, rc/stdout/stderr are empty defaults.
    """
    result = guard_check(argv)
    if not result.allowed:
        return False, result.reason, -1, "", ""
    effective_cwd = cwd if cwd is not None else ctx.work_dir
    rc, out, err = ctx.runner(argv, effective_cwd)
    return True, result.reason, rc, out, err


class GitCloneFetchStep(ValidationStep):
    """
    Step 1: Clone the remote repo and fetch the feature branch.

    Commands:
      git clone <remote_url> <work_dir>
      git fetch origin <feature_branch>
    """

    @property
    def name(self) -> str:
        return "git-clone-fetch"

    def run(self, ctx: StepContext) -> StepResult:
        start = time.monotonic()

        # Step A: git clone
        clone_argv = ["git", "clone", ctx.remote_url, ctx.work_dir]
        guard_ok, guard_reason, rc, out, err = _guard_and_run(clone_argv, ctx, cwd=".")
        if not guard_ok:
            return StepResult(
                step_name=self.name,
                success=False,
                output=f"guard rejected: {guard_reason}",
                duration_seconds=time.monotonic() - start,
                metadata={},
            )
        if rc != 0:
            return StepResult(
                step_name=self.name,
                success=False,
                output=err or out,
                duration_seconds=time.monotonic() - start,
                metadata={"exit_code": rc},
            )

        # Step B: git fetch origin <feature_branch>
        fetch_argv = ["git", "fetch", "origin", ctx.feature_branch]
        guard_ok, guard_reason, rc, out, err = _guard_and_run(fetch_argv, ctx)
        if not guard_ok:
            return StepResult(
                step_name=self.name,
                success=False,
                output=f"guard rejected: {guard_reason}",
                duration_seconds=time.monotonic() - start,
                metadata={},
            )
        if rc != 0:
            return StepResult(
                step_name=self.name,
                success=False,
                output=err or out,
                duration_seconds=time.monotonic() - start,
                metadata={"exit_code": rc},
            )

        return StepResult(
            step_name=self.name,
            success=True,
            output=out,
            duration_seconds=time.monotonic() - start,
            metadata={"cloned_to": ctx.work_dir},
        )


class GitMergeCheckStep(ValidationStep):
    """
    Step 2: Attempt a no-commit merge to detect conflicts, then diff.

    Commands:
      git checkout <feature_branch>
      git merge --no-commit origin/<target_branch>
      git diff --name-only HEAD origin/<target_branch>
      git merge --abort   (always, even on clean merge)
    """

    @property
    def name(self) -> str:
        return "git-merge-check"

    def run(self, ctx: StepContext) -> StepResult:  # noqa: C901
        start = time.monotonic()

        # Step A: git checkout <feature_branch>
        checkout_argv = ["git", "checkout", ctx.feature_branch]
        guard_ok, guard_reason, rc, out, err = _guard_and_run(checkout_argv, ctx)
        if not guard_ok:
            return StepResult(
                step_name=self.name,
                success=False,
                output=f"guard rejected: {guard_reason}",
                duration_seconds=time.monotonic() - start,
                metadata={},
            )
        if rc != 0:
            return StepResult(
                step_name=self.name,
                success=False,
                output=err or out,
                duration_seconds=time.monotonic() - start,
                metadata={"exit_code": rc},
            )

        # Step B: git merge --no-commit origin/<target_branch>
        merge_argv = ["git", "merge", "--no-commit", f"origin/{ctx.target_branch}"]
        guard_ok, guard_reason, merge_rc, merge_out, merge_err = _guard_and_run(
            merge_argv, ctx
        )
        if not guard_ok:
            return StepResult(
                step_name=self.name,
                success=False,
                output=f"guard rejected: {guard_reason}",
                duration_seconds=time.monotonic() - start,
                metadata={},
            )

        # Detect conflicts: non-zero rc OR "CONFLICT" in combined output.
        combined = merge_out + "\n" + merge_err
        has_conflicts = merge_rc != 0 or "CONFLICT" in combined

        conflict_files: list[str] = []
        if has_conflicts:
            for line in combined.splitlines():
                if "CONFLICT" in line and "Merge conflict in" in line:
                    parts = line.split("Merge conflict in", 1)
                    if len(parts) == 2:
                        conflict_files.append(parts[1].strip())

        # Step C: git diff --name-only HEAD origin/<target_branch>
        diff_argv = ["git", "diff", "--name-only", "HEAD", f"origin/{ctx.target_branch}"]
        guard_ok, guard_reason, diff_rc, diff_out, diff_err = _guard_and_run(
            diff_argv, ctx
        )
        changed_files: list[str] = []
        if guard_ok and diff_rc == 0:
            changed_files = [
                line.strip() for line in diff_out.splitlines() if line.strip()
            ]

        # Step D: git merge --abort (always, safe to abort a --no-commit merge)
        abort_argv = ["git", "merge", "--abort"]
        _guard_and_run(abort_argv, ctx)

        duration = time.monotonic() - start

        if has_conflicts:
            return StepResult(
                step_name=self.name,
                success=False,
                output=combined.strip(),
                duration_seconds=duration,
                metadata={
                    "has_conflicts": True,
                    "conflict_files": conflict_files,
                    "changed_files": changed_files,
                },
            )

        return StepResult(
            step_name=self.name,
            success=True,
            output=combined.strip(),
            duration_seconds=duration,
            metadata={
                "has_conflicts": False,
                "conflict_files": [],
                "changed_files": changed_files,
            },
        )
