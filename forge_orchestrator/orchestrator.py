"""
forge_orchestrator/orchestrator.py

Orchestrator: wires Worker (Slice 3) to ValidationLifecycle (Slice 2) and
the BuildPlanner (Slice 1) to produce a complete ValidationRun.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal

from forge_orchestrator.worker import Worker, WorkerConfig
from forge_planner.planner import plan as planner_plan
from forge_worker.lifecycle import LifecycleConfig, ValidationLifecycle

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Request / Result dataclasses
# ---------------------------------------------------------------------------

@dataclass
class ValidationRequest:
    repo_url: str
    feature_branch: str
    target_branch: str
    validation_profile: str = "default"  # reserved for future use
    active_maven_profiles: list[str] = field(default_factory=list)


@dataclass
class ValidationRun:
    run_id: str                  # uuid4 string
    request: ValidationRequest
    status: Literal["pending", "running", "success", "failure", "error"]
    started_at: datetime
    finished_at: datetime | None
    has_conflicts: bool | None
    changed_files: list[str]
    conflict_files: list[str]
    maven_command: str | None
    lifecycle_log: list[str]
    error_message: str | None


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

class Orchestrator:
    """
    Runs a full validation end-to-end inside an ephemeral Docker worker.

    Responsibilities
    ----------------
    1. Create an ephemeral Worker (context manager — guaranteed teardown).
    2. Wire its exec() method as the runner for ValidationLifecycle.
    3. Pass changed_files to the BuildPlanner to get the Maven command.
    4. Return a complete ValidationRun.
    """

    def __init__(self, worker_config: WorkerConfig) -> None:
        self._worker_config = worker_config

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self, request: ValidationRequest) -> ValidationRun:
        """
        Run a full validation and return a ValidationRun.

        On any exception the status is "error" and the error is captured in
        error_message. The worker is always torn down (context manager).
        """
        run_id = str(uuid.uuid4())
        started_at = datetime.now(tz=timezone.utc)

        run = ValidationRun(
            run_id=run_id,
            request=request,
            status="running",
            started_at=started_at,
            finished_at=None,
            has_conflicts=None,
            changed_files=[],
            conflict_files=[],
            maven_command=None,
            lifecycle_log=[],
            error_message=None,
        )

        try:
            with Worker(self._worker_config) as worker:
                run = self._execute(run, request, worker)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Orchestrator.run raised an unexpected error: %s", exc)
            run.status = "error"
            run.error_message = str(exc)
            run.finished_at = datetime.now(tz=timezone.utc)

        return run

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _execute(
        self,
        run: ValidationRun,
        request: ValidationRequest,
        worker: Worker,
    ) -> ValidationRun:
        """Run the lifecycle + planner inside an already-started worker."""

        # Build the runner adapter: lifecycle expects (argv, cwd) → (rc, out, err)
        # but cwd is ignored inside the container (it uses its own work_dir).
        def docker_runner(argv: list[str], cwd: str) -> tuple[int, str, str]:  # noqa: ARG001
            return worker.exec(argv)

        cfg = LifecycleConfig(
            remote_url=request.repo_url,
            feature_branch=request.feature_branch,
            target_branch=request.target_branch,
            work_dir=self._worker_config.work_dir,
        )

        try:
            lifecycle = ValidationLifecycle(
                config=cfg,
                maven_command=None,  # we'll determine the command after diff
                runner=docker_runner,
            )
            result = lifecycle.run()
        except Exception as exc:
            run.status = "error"
            run.error_message = str(exc)
            run.finished_at = datetime.now(tz=timezone.utc)
            return run

        run.has_conflicts = result.has_conflicts
        run.changed_files = result.changed_files
        run.conflict_files = result.conflict_files
        run.lifecycle_log = result.lifecycle_log

        if result.has_conflicts:
            run.status = "failure"
            run.maven_command = None
            run.finished_at = datetime.now(tz=timezone.utc)
            return run

        # No conflicts: run the build planner, then the Maven command
        try:
            execution_plan = planner_plan(
                repo_root=self._worker_config.work_dir,
                changed_files=result.changed_files,
                active_profiles=request.active_maven_profiles or None,
            )
            maven_command = execution_plan.maven_command
        except Exception as exc:
            logger.warning(
                "Planner failed (falling back to full build): %s", exc
            )
            maven_command = "mvn clean verify"

        run.maven_command = maven_command

        # Execute the Maven build via the worker
        try:
            parts = maven_command.split()
            rc, stdout, stderr = worker.exec(parts)
            run.lifecycle_log.append(f"build: {maven_command}")
            run.lifecycle_log.append(f"build: rc={rc}")
            if rc != 0:
                raise RuntimeError(f"Maven build failed (rc={rc}): {stderr}")
        except Exception as exc:
            run.status = "error"
            run.error_message = str(exc)
            run.finished_at = datetime.now(tz=timezone.utc)
            return run

        run.status = "success"
        run.finished_at = datetime.now(tz=timezone.utc)
        return run
