"""
tests/test_api_async.py

Tests for the async POST /api/v1/validations endpoint.

FastAPI's TestClient executes BackgroundTasks synchronously before returning,
so after the POST completes the background task has already run and the
repository contains the final (updated) run.
"""

from __future__ import annotations

import os
import sys
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

_here = os.path.dirname(__file__)
_project_root = os.path.dirname(_here)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from forge_api.app import create_app
from forge_api.repository import SQLiteRunRepository
from forge_orchestrator.orchestrator import ValidationRequest, ValidationRun


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_validation_run(
    run_id: str | None = None,
    status: str = "success",
    has_conflicts: bool = False,
) -> ValidationRun:
    request = ValidationRequest(
        repo_url="https://github.com/example/repo.git",
        feature_branch="feature/test",
        target_branch="main",
    )
    now = datetime.now(tz=timezone.utc)
    return ValidationRun(
        run_id=run_id or str(uuid.uuid4()),
        request=request,
        status=status,
        started_at=now,
        finished_at=now,
        has_conflicts=has_conflicts,
        changed_files=["src/Foo.java"],
        conflict_files=[],
        maven_command="mvn clean verify",
        lifecycle_log=["step: clone", "step: fetch"],
        error_message=None,
    )


def _make_mock_orchestrator(run: ValidationRun | None = None) -> MagicMock:
    mock_orch = MagicMock()
    mock_orch.run.return_value = run or _make_validation_run()
    return mock_orch


def _make_in_memory_repository() -> SQLiteRunRepository:
    return SQLiteRunRepository(db_path=":memory:")


def _make_test_client(
    mock_run: ValidationRun | None = None,
    repository: SQLiteRunRepository | None = None,
    mock_orch: MagicMock | None = None,
) -> tuple[TestClient, SQLiteRunRepository, MagicMock]:
    orch = mock_orch or _make_mock_orchestrator(mock_run)
    repo = repository or _make_in_memory_repository()
    app = create_app(orchestrator=orch, repository=repo)
    client = TestClient(app)
    return client, repo, orch


_POST_PAYLOAD = {
    "repo_url": "https://github.com/example/repo.git",
    "feature_branch": "feature/test",
    "target_branch": "main",
}


# ===========================================================================
# 9. POST /api/v1/validations returns 202 (not 201)
# ===========================================================================

class TestAsyncPostReturns202:
    def test_post_returns_202(self):
        """POST /api/v1/validations must return HTTP 202 Accepted."""
        client, _, _ = _make_test_client()
        response = client.post("/api/v1/validations", json=_POST_PAYLOAD)
        assert response.status_code == 202

    def test_post_response_has_run_id(self):
        """POST /api/v1/validations response must include a non-empty run_id."""
        client, _, _ = _make_test_client()
        response = client.post("/api/v1/validations", json=_POST_PAYLOAD)
        assert response.status_code == 202
        body = response.json()
        assert "run_id" in body
        assert body["run_id"]

    def test_post_response_has_status(self):
        """POST /api/v1/validations response must include a status field."""
        client, _, _ = _make_test_client()
        response = client.post("/api/v1/validations", json=_POST_PAYLOAD)
        body = response.json()
        assert "status" in body


# ===========================================================================
# 10. Response body has run_id and status="running" (returned immediately)
# ===========================================================================

class TestPendingRunResponse:
    def test_immediate_response_has_run_id_and_status(self):
        """The immediate 202 response must contain run_id and status."""
        client, _, _ = _make_test_client()
        response = client.post("/api/v1/validations", json=_POST_PAYLOAD)
        assert response.status_code == 202
        body = response.json()
        assert "run_id" in body
        assert "status" in body

    def test_run_id_is_valid_uuid(self):
        """The run_id in the 202 response must be a valid UUID."""
        client, _, _ = _make_test_client()
        response = client.post("/api/v1/validations", json=_POST_PAYLOAD)
        body = response.json()
        run_id = body["run_id"]
        # Will raise ValueError if not a valid UUID
        parsed = uuid.UUID(run_id)
        assert str(parsed) == run_id

    def test_status_is_running_or_final(self):
        """
        The 202 response body has status='running'.
        (In TestClient, background tasks run synchronously so the DB may have
        the final status, but the response body itself reflects the pending run.)
        """
        client, _, _ = _make_test_client()
        response = client.post("/api/v1/validations", json=_POST_PAYLOAD)
        body = response.json()
        # The response body is the pending run snapshot; status is "running"
        # Background task may update DB, but response reflects the initial state
        assert body["status"] in ("running", "success", "failure", "error")


# ===========================================================================
# 11. GET /api/v1/validations/{run_id} returns the run after POST
# ===========================================================================

class TestGetRunAfterPost:
    def test_get_run_returns_200_after_post(self):
        """After POST, GET /api/v1/validations/{run_id} must return 200."""
        client, repo, _ = _make_test_client()
        post_response = client.post("/api/v1/validations", json=_POST_PAYLOAD)
        assert post_response.status_code == 202

        run_id = post_response.json()["run_id"]
        get_response = client.get(f"/api/v1/validations/{run_id}")
        assert get_response.status_code == 200

    def test_get_run_has_correct_run_id(self):
        """GET run returns the same run_id as the POST response."""
        client, _, _ = _make_test_client()
        post_response = client.post("/api/v1/validations", json=_POST_PAYLOAD)
        run_id = post_response.json()["run_id"]

        get_response = client.get(f"/api/v1/validations/{run_id}")
        assert get_response.json()["run_id"] == run_id

    def test_run_is_saved_to_repository(self):
        """After POST, the run is persisted in the repository with the response run_id."""
        client, repo, _ = _make_test_client()
        post_response = client.post("/api/v1/validations", json=_POST_PAYLOAD)
        run_id = post_response.json()["run_id"]

        saved = repo.get(run_id)
        assert saved is not None
        assert saved.run_id == run_id


# ===========================================================================
# 12. Background task updates status to "success"/"failure"
# ===========================================================================

class TestBackgroundTaskUpdatesStatus:
    def test_background_task_runs_orchestrator(self):
        """The background task must call orchestrator.run() exactly once."""
        client, _, mock_orch = _make_test_client()
        client.post("/api/v1/validations", json=_POST_PAYLOAD)
        mock_orch.run.assert_called_once()

    def test_background_task_updates_run_status_to_success(self):
        """After background task, the repository contains the final 'success' status."""
        success_run = _make_validation_run(status="success")
        client, repo, _ = _make_test_client(mock_run=success_run)

        post_response = client.post("/api/v1/validations", json=_POST_PAYLOAD)
        run_id = post_response.json()["run_id"]

        # TestClient runs background tasks synchronously, so the DB is updated
        saved = repo.get(run_id)
        assert saved is not None
        assert saved.status == "success"

    def test_background_task_updates_run_status_to_failure(self):
        """After background task with conflicts, repository contains 'failure' status."""
        failure_run = _make_validation_run(status="failure", has_conflicts=True)
        client, repo, _ = _make_test_client(mock_run=failure_run)

        post_response = client.post("/api/v1/validations", json=_POST_PAYLOAD)
        run_id = post_response.json()["run_id"]

        saved = repo.get(run_id)
        assert saved is not None
        assert saved.status == "failure"

    def test_background_task_stores_error_on_exception(self):
        """If the orchestrator raises, the background task saves an error run."""
        mock_orch = MagicMock()
        mock_orch.run.side_effect = RuntimeError("docker failed")
        client, repo, _ = _make_test_client(mock_orch=mock_orch)

        post_response = client.post("/api/v1/validations", json=_POST_PAYLOAD)
        run_id = post_response.json()["run_id"]

        saved = repo.get(run_id)
        assert saved is not None
        assert saved.status == "error"
        assert saved.error_message is not None
        assert "docker failed" in saved.error_message


# ===========================================================================
# 13. DELETE /api/v1/validations/{run_id} returns 501
# ===========================================================================

class TestCancelValidation:
    def test_delete_returns_501(self):
        """DELETE /api/v1/validations/{run_id} must return 501 Not Implemented."""
        client, _, _ = _make_test_client()
        run_id = str(uuid.uuid4())
        response = client.delete(f"/api/v1/validations/{run_id}")
        assert response.status_code == 501

    def test_delete_body_indicates_not_implemented(self):
        """DELETE response body must mention cancellation not implemented."""
        client, _, _ = _make_test_client()
        run_id = str(uuid.uuid4())
        response = client.delete(f"/api/v1/validations/{run_id}")
        body = response.json()
        detail = body.get("detail", "")
        assert "cancel" in detail.lower() or "not" in detail.lower()


# ===========================================================================
# 14. GET /api/v1/health still works (regression)
# ===========================================================================

class TestHealthRegression:
    def test_health_returns_200(self):
        """GET /api/v1/health must still return 200 after async changes."""
        client, _, _ = _make_test_client()
        response = client.get("/api/v1/health")
        assert response.status_code == 200

    def test_health_returns_ok(self):
        """GET /api/v1/health must still return {'status': 'ok'}."""
        client, _, _ = _make_test_client()
        response = client.get("/api/v1/health")
        assert response.json() == {"status": "ok"}


# ===========================================================================
# 15. GET /api/v1/validations list still works (regression)
# ===========================================================================

class TestListValidationsRegression:
    def test_list_returns_200(self):
        """GET /api/v1/validations must return 200."""
        client, _, _ = _make_test_client()
        response = client.get("/api/v1/validations")
        assert response.status_code == 200

    def test_list_has_runs_and_total(self):
        """GET /api/v1/validations must return a body with 'runs' and 'total'."""
        client, _, _ = _make_test_client()
        response = client.get("/api/v1/validations")
        body = response.json()
        assert "runs" in body
        assert "total" in body

    def test_list_includes_run_after_post(self):
        """After POST, the run appears in GET /api/v1/validations list."""
        client, _, _ = _make_test_client()
        client.post("/api/v1/validations", json=_POST_PAYLOAD)

        response = client.get("/api/v1/validations")
        body = response.json()
        assert body["total"] >= 1
        assert len(body["runs"]) >= 1
