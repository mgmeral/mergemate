"""
forge_spi/context.py

StepContext — everything a validation step needs to do its job.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable


@dataclass
class StepContext:
    """Everything a validation step needs to do its job."""

    run_id: str
    remote_url: str
    feature_branch: str
    target_branch: str
    work_dir: str                          # working directory inside the container
    maven_command: str | None              # from the ExecutionPlan; None if not yet computed
    active_maven_profiles: list[str]
    runner: Callable[[list[str], str], tuple[int, str, str]]  # (argv, cwd) → (rc, out, err)
    changed_files: list[str]               # populated after the git diff step
    extra: dict                            # plugin-specific extras, extensible
