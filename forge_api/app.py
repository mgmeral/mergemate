"""
forge_api/app.py

FastAPI application factory for the MergeMate REST API.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse

from forge_api.models import (
    StartValidationRequest,
    ValidationListResponse,
    ValidationRunResponse,
)
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

def run_to_response(run: ValidationRun) -> ValidationRunResponse:
    """Convert a ValidationRun domain object to the API response model."""
    # Retrieve execution_plan if stored as a private attribute
    execution_plan: Optional[dict] = None
    if hasattr(run, "_execution_plan"):
        execution_plan = run._execution_plan  # type: ignore[attr-defined]

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
    )


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

    @app.post("/api/v1/validations", status_code=201, response_model=ValidationRunResponse)
    def start_validation(request: StartValidationRequest):
        """
        Start a validation run.

        Runs validation synchronously, persists the result, and returns the run.
        """
        try:
            validation_request = ValidationRequest(
                repo_url=request.repo_url,
                feature_branch=request.feature_branch,
                target_branch=request.target_branch,
                validation_profile=request.validation_profile,
                active_maven_profiles=request.active_maven_profiles,
            )
            run = app.state.orchestrator.run(validation_request)
            app.state.repository.save(run)
            return run_to_response(run)
        except Exception as exc:
            logger.exception("Error in POST /api/v1/validations: %s", exc)
            raise HTTPException(
                status_code=500,
                detail={"detail": "internal server error", "error": str(exc)},
            )

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
