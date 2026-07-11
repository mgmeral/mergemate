"""
forge_api/app.py

FastAPI application factory for the MergeMate API.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse

from forge_api.models import (
    StartValidationRequest,
    ValidationListResponse,
    ValidationRunResponse,
)
from forge_analysis.analyzer import FailureAnalyzer
from forge_api.repository import SQLiteRunRepository, ValidationRunRepository
from forge_orchestrator.orchestrator import (
    Orchestrator,
    ValidationRequest,
    ValidationRun,
)
from forge_orchestrator.worker import WorkerConfig

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Conversion helper
# ---------------------------------------------------------------------------

_failure_analyzer = FailureAnalyzer()


def run_to_response(run: ValidationRun) -> ValidationRunResponse:
    """Convert a ValidationRun domain object to the API response model."""
    # Retrieve execution_plan if stored as a private attribute
    execution_plan: Optional[dict] = None
    if hasattr(run, "_execution_plan"):
        execution_plan = run._execution_plan  # type: ignore[attr-defined]

    # Compute failure analysis on the fly (not persisted)
    failure_summary = _failure_analyzer.analyze(
        run_id=run.run_id,
        status=run.status,
        lifecycle_log=run.lifecycle_log,
        has_conflicts=run.has_conflicts,
        conflict_files=run.conflict_files,
        error_message=run.error_message,
    )
    import dataclasses
    failure_analysis: Optional[dict] = dataclasses.asdict(failure_summary)

    return ValidationRunResponse(
        run_id=run.run_id,
        status=run.status,
        started_at=run.started_at,
        finished_at=run.finished_at,
        has_conflicts=run.has_conflicts,
        changed_files=run.changed_files,
        conflict_files=run.conflict_files,
        maven_command=run.maven_command,
        lifecycle_log=run.lifecycle_log,
        error_message=run.error_message,
        execution_plan=execution_plan,
        failure_analysis=failure_analysis,
    )


# ---------------------------------------------------------------------------
# Pending / error run helpers
# ---------------------------------------------------------------------------

def _create_pending_run(
    run_id: str,
    request: StartValidationRequest,
    started_at: datetime,
) -> ValidationRun:
    """Construct a ValidationRun with status='running' as an initial placeholder."""
    validation_request = ValidationRequest(
        repo_url=request.repo_url,
        feature_branch=request.feature_branch,
        target_branch=request.target_branch,
        validation_profile=request.validation_profile,
        active_maven_profiles=request.active_maven_profiles,
    )
    return ValidationRun(
        run_id=run_id,
        request=validation_request,
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


def _create_error_run(
    run_id: str,
    request: StartValidationRequest,
    error_message: str,
    started_at: Optional[datetime] = None,
) -> ValidationRun:
    """Construct a ValidationRun with status='error'."""
    validation_request = ValidationRequest(
        repo_url=request.repo_url,
        feature_branch=request.feature_branch,
        target_branch=request.target_branch,
        validation_profile=request.validation_profile,
        active_maven_profiles=request.active_maven_profiles,
    )
    now = datetime.now(timezone.utc)
    return ValidationRun(
        run_id=run_id,
        request=validation_request,
        status="error",
        started_at=started_at or now,
        finished_at=now,
        has_conflicts=None,
        changed_files=[],
        conflict_files=[],
        maven_command=None,
        lifecycle_log=[],
        error_message=error_message,
    )


def _run_validation_background(
    run_id: str,
    request: StartValidationRequest,
    orchestrator: Orchestrator,
    repository: ValidationRunRepository,
) -> None:
    """Background task: run the full validation and update the repository."""
    try:
        validation_request = ValidationRequest(
            repo_url=request.repo_url,
            feature_branch=request.feature_branch,
            target_branch=request.target_branch,
            validation_profile=request.validation_profile,
            active_maven_profiles=request.active_maven_profiles,
        )
        run = orchestrator.run(validation_request)
        # Preserve the pre-assigned run_id so callers can poll by it
        run.run_id = run_id
        repository.save(run)
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "Background validation task failed for run_id=%s: %s", run_id, exc
        )
        error_run = _create_error_run(run_id, request, str(exc))
        try:
            repository.save(error_run)
        except Exception:  # noqa: BLE001
            logger.exception("Failed to save error run for run_id=%s", run_id)


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------

def create_app(
    orchestrator: Optional[Orchestrator] = None,
    repository: Optional[ValidationRunRepository] = None,
    worker_config: Optional[WorkerConfig] = None,
) -> FastAPI:
    """
    Factory function for the FastAPI application.

    Pass orchestrator/repository for testing. In production, they are created
    from environment variables.
    """
    import os

    # Resolve orchestrator
    if orchestrator is None:
        if worker_config is None:
            worker_config = WorkerConfig(
                image=os.environ.get("MERGEMATE_WORKER_IMAGE", "mergemate-worker:latest"),
                remote_url="",  # will be overridden per request
                ssh_key_path=os.path.expanduser(
                    os.environ.get("MERGEMATE_SSH_KEY_PATH", "~/.ssh/id_rsa")
                ),
            )
        orchestrator = Orchestrator(worker_config)

    # Resolve repository
    if repository is None:
        db_path = os.environ.get("MERGEMATE_DB_PATH", "mergemate.db")
        repository = SQLiteRunRepository(db_path=db_path)

    app = FastAPI(
        title="MergeMate API",
        description="REST API for triggering and monitoring merge validation runs.",
        version="1.0.0",
    )

    # Store as app state so routes can access them
    app.state.orchestrator = orchestrator
    app.state.repository = repository

    # -----------------------------------------------------------------------
    # Routes
    # -----------------------------------------------------------------------

    @app.get("/api/v1/health")
    def health_check():
        """Health check endpoint."""
        return {"status": "ok"}

    @app.post("/api/v1/validations", status_code=202, response_model=ValidationRunResponse)
    def start_validation(
        request: StartValidationRequest,
        background_tasks: BackgroundTasks,
    ):
        """
        Start a validation run asynchronously.

        Returns immediately with status='running' and a run_id.
        Poll GET /api/v1/validations/{run_id} for completion.
        """
        run_id = str(uuid.uuid4())
        started_at = datetime.now(timezone.utc)

        # Create a pending run immediately and persist it so callers can poll
        pending_run = _create_pending_run(run_id, request, started_at)
        app.state.repository.save(pending_run)

        # Schedule the actual validation in the background
        background_tasks.add_task(
            _run_validation_background,
            run_id=run_id,
            request=request,
            orchestrator=app.state.orchestrator,
            repository=app.state.repository,
        )

        return run_to_response(pending_run)

    @app.delete("/api/v1/validations/{run_id}")
    def cancel_validation(run_id: str):
        """Cancel a running validation. Currently returns 501 Not Implemented."""
        raise HTTPException(status_code=501, detail="cancellation not yet implemented")

    @app.get("/api/v1/validations/{run_id}", response_model=ValidationRunResponse)
    def get_validation(run_id: str):
        """Retrieve a validation run by ID."""
        try:
            run = app.state.repository.get(run_id)
            if run is None:
                raise HTTPException(status_code=404, detail="run not found")
            return run_to_response(run)
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("Error in GET /api/v1/validations/%s: %s", run_id, exc)
            raise HTTPException(
                status_code=500,
                detail={"detail": "internal server error", "error": str(exc)},
            )

    @app.get("/api/v1/validations", response_model=ValidationListResponse)
    def list_validations(limit: int = Query(default=50, ge=1, le=200)):
        """List recent validation runs."""
        try:
            runs = app.state.repository.list_recent(limit=limit)
            responses = [run_to_response(run) for run in runs]
            return ValidationListResponse(runs=responses, total=len(responses))
        except Exception as exc:
            logger.exception("Error in GET /api/v1/validations: %s", exc)
            raise HTTPException(
                status_code=500,
                detail={"detail": "internal server error", "error": str(exc)},
            )

    return app
