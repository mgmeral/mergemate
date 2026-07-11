"""
tests/test_api.py

Unit tests for forge_api: FastAPI endpoints and SQLiteRunRepository.

Tests do NOT require a running Docker host — the Orchestrator is mocked.
Repository tests use an in-memory SQLite database.
"""

from __future__ import annotations

import os
import sys
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

_here = os.path.dirname(__file__)
_project_root = os.path.dirname(_here)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from forge_api.app import create_app, run_to_response
from forge_api.models import StartValidationRequest, ValidationRunResponse, ValidationListResponse
from forge_api.repository import SQLiteRunRepository
from forge_orchestrator.orchestrator import ValidationRequest, ValidationRun


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

def _make_validation_run(
    run_id: str | None = None,
    status: str = "success",
    has_conflicts: bool = False,
    changed_files: list[str] | None = None,
    conflict_files: list[str] | None = None,
    maven_command: str | None = "mvn clean verify",
    lifecycle_log: list[str] | None = None,
    error_message: str | None = None,
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
) -> ValidationRun:
    """Create a ValidationRun for testing."""
    request = ValidationRequest(
        repo_url="https://github.com/example/repo.git",
        feature_branch="feature/test-branch",
        target_branch="main",
        validation_profile="default",
        active_maven_profiles=[],
    )
    now = datetime.now(tz=timezone.utc)
    return ValidationRun(
        run_id=run_id or str(uuid.uuid4()),
        request=request,
        status=status,
        started_at=started_at or now,
        finished_at=finished_at or now,
        has_conflicts=has_conflicts,
        changed_files=changed_files or ["src/main/java/Foo.java"],
        conflict_files=conflict_files or [],
        maven_command=maven_command,
        lifecycle_log=lifecycle_log or ["step: clone", "step: fetch", "step: diff"],
        error_message=error_message,
    )


def _make_mock_orchestrator(run: ValidationRun | None = None) -> MagicMock:
    """Create a mock Orchestrator that returns the given run."""
    mock_orch = MagicMock()
    mock_orch.run.return_value = run or _make_validation_run()
    return mock_orch


def _make_in_memory_repository() -> SQLiteRunRepository:
    """Create a SQLiteRunRepository backed by an in-memory database."""
    return SQLiteRunRepository(db_path=":memory:")


def _make_test_client(
    mock_run: ValidationRun | None = None,
    repository: SQLiteRunRepository | None = None,
) -> TestClient:
    """Create a TestClient with a mocked orchestrator and optional repository."""
    mock_orch = _make_mock_orchestrator(mock_run)
    repo = repository or _make_in_memory_repository()
    app = create_app(orchestrator=mock_orch, repository=repo)
    return TestClient(app)


# ===========================================================================
# 1. POST /api/v1/validations — start a validation (async), returns 202
# ===========================================================================

class TestStartValidation:
    def test_post_validations_returns_202(self):
        """POST /api/v1/validations returns HTTP 202 Accepted (async)."""
        client = _make_test_client()
        response = client.post("/api/v1/validations", json={
            "repo_url": "https://github.com/example/repo.git",
            "feature_branch": "feature/new-thing",
            "target_branch": "main",
        })
        assert response.status_code == 202

    def test_post_validations_body_has_run_id(self):
        """POST /api/v1/validations response body includes run_id."""
        run_id = str(uuid.uuid4())
        run = _make_validation_run(run_id=run_id, status="success")
        client = _make_test_client(mock_run=run)

        response = client.post("/api/v1/validations", json={
            "repo_url": "https://github.com/example/repo.git",
            "feature_branch": "feature/test",
            "target_branch": "main",
        })
        assert response.status_code == 202
        body = response.json()
        # The run_id in the response is a pre-assigned uuid (not the mock's run_id)
        assert "run_id" in body
        assert body["run_id"]  # non-empty

    def test_post_validations_body_has_status_running(self):
        """POST /api/v1/validations response body has status='running' immediately."""
        run = _make_validation_run(status="success")
        client = _make_test_client(mock_run=run)

        response = client.post("/api/v1/validations", json={
            "repo_url": "https://github.com/example/repo.git",
            "feature_branch": "feature/test",
            "target_branch": "main",
        })
        assert response.status_code == 202
        body = response.json()
        # The pending run has status="running"; background task updates it to "success"
        # In TestClient, background tasks run synchronously so the DB has the final result,
        # but the response body reflects the pending run returned before the task.
        assert body["status"] in ("running", "success")

    def test_post_validations_passes_request_to_orchestrator(self):
        """POST /api/v1/validations calls orchestrator.run with the correct ValidationRequest."""
        mock_orch = _make_mock_orchestrator()
        repo = _make_in_memory_repository()
        app = create_app(orchestrator=mock_orch, repository=repo)
        client = TestClient(app)

        client.post("/api/v1/validations", json={
            "repo_url": "https://github.com/example/repo.git",
            "feature_branch": "feature/my-branch",
            "target_branch": "develop",
            "validation_profile": "ci",
            "active_maven_profiles": ["integration"],
        })

        mock_orch.run.assert_called_once()
        vr: ValidationRequest = mock_orch.run.call_args[0][0]
        assert vr.repo_url == "https://github.com/example/repo.git"
        assert vr.feature_branch == "feature/my-branch"
        assert vr.target_branch == "develop"
        assert vr.validation_profile == "ci"
        assert vr.active_maven_profiles == ["integration"]

    def test_post_validations_run_persisted_in_repository(self):
        """POST /api/v1/validations persists the run to the repository."""
        repo = _make_in_memory_repository()
        client = _make_test_client(repository=repo)

        response = client.post("/api/v1/validations", json={
            "repo_url": "https://github.com/example/repo.git",
            "feature_branch": "feature/test",
            "target_branch": "main",
        })

        # The response body contains the run_id that was persisted
        run_id = response.json()["run_id"]
        saved = repo.get(run_id)
        assert saved is not None
        assert saved.run_id == run_id

    def test_post_validations_all_required_fields_present(self):
        """POST /api/v1/validations response has all required fields."""
        client = _make_test_client()
        response = client.post("/api/v1/validations", json={
            "repo_url": "https://github.com/example/repo.git",
            "feature_branch": "feature/test",
            "target_branch": "main",
        })
        body = response.json()
        expected_fields = [
            "run_id", "status", "started_at", "finished_at",
            "has_conflicts", "changed_files", "conflict_files",
            "maven_command", "lifecycle_log", "error_message", "execution_plan",
        ]
        for field in expected_fields:
            assert field in body, f"Missing field: {field}"


# ===========================================================================
# 2. GET /api/v1/validations/{run_id} — existing run returns 200
# ===========================================================================

class TestGetValidation:
    def test_get_existing_run_returns_200(self):
        """GET /api/v1/validations/{run_id} for an existing run returns 200."""
        run_id = str(uuid.uuid4())
        run = _make_validation_run(run_id=run_id)
        repo = _make_in_memory_repository()
        repo.save(run)
        client = _make_test_client(repository=repo)

        response = client.get(f"/api/v1/validations/{run_id}")
        assert response.status_code == 200

    def test_get_existing_run_returns_correct_data(self):
        """GET /api/v1/validations/{run_id} returns the correct run data."""
        run_id = str(uuid.uuid4())
        run = _make_validation_run(
            run_id=run_id,
            status="failure",
            has_conflicts=True,
            conflict_files=["src/Conflict.java"],
        )
        repo = _make_in_memory_repository()
        repo.save(run)
        client = _make_test_client(repository=repo)

        response = client.get(f"/api/v1/validations/{run_id}")
        body = response.json()
        assert body["run_id"] == run_id
        assert body["status"] == "failure"
        assert body["has_conflicts"] is True
        assert "src/Conflict.java" in body["conflict_files"]


# ===========================================================================
# 3. GET /api/v1/validations/{run_id} — missing run returns 404
# ===========================================================================

class TestGetValidationNotFound:
    def test_get_missing_run_returns_404(self):
        """GET /api/v1/validations/{run_id} for a non-existent run returns 404."""
        client = _make_test_client()
        fake_id = str(uuid.uuid4())
        response = client.get(f"/api/v1/validations/{fake_id}")
        assert response.status_code == 404

    def test_get_missing_run_detail_message(self):
        """GET /api/v1/validations/{run_id} for a missing run has detail message."""
        client = _make_test_client()
        fake_id = str(uuid.uuid4())
        response = client.get(f"/api/v1/validations/{fake_id}")
        body = response.json()
        assert "run not found" in body.get("detail", "").lower()


# ===========================================================================
# 4. GET /api/v1/validations — returns list
# ===========================================================================

class TestListValidations:
    def test_list_validations_returns_200(self):
        """GET /api/v1/validations returns HTTP 200."""
        client = _make_test_client()
        response = client.get("/api/v1/validations")
        assert response.status_code == 200

    def test_list_validations_returns_list_structure(self):
        """GET /api/v1/validations returns a JSON object with 'runs' and 'total'."""
        client = _make_test_client()
        response = client.get("/api/v1/validations")
        body = response.json()
        assert "runs" in body
        assert "total" in body
        assert isinstance(body["runs"], list)
        assert isinstance(body["total"], int)

    def test_list_validations_includes_saved_runs(self):
        """GET /api/v1/validations includes runs that have been saved."""
        repo = _make_in_memory_repository()
        run1 = _make_validation_run()
        run2 = _make_validation_run()
        repo.save(run1)
        repo.save(run2)
        client = _make_test_client(repository=repo)

        response = client.get("/api/v1/validations")
        body = response.json()
        assert body["total"] == 2
        assert len(body["runs"]) == 2

    def test_list_validations_respects_limit_param(self):
        """GET /api/v1/validations?limit=N respects the limit query parameter."""
        repo = _make_in_memory_repository()
        for _ in range(5):
            repo.save(_make_validation_run())
        client = _make_test_client(repository=repo)

        response = client.get("/api/v1/validations?limit=2")
        body = response.json()
        assert len(body["runs"]) == 2

    def test_list_validations_empty_when_no_runs(self):
        """GET /api/v1/validations returns empty list when no runs exist."""
        client = _make_test_client()
        response = client.get("/api/v1/validations")
        body = response.json()
        assert body["total"] == 0
        assert body["runs"] == []


# ===========================================================================
# 5. GET /api/v1/health — health check
# ===========================================================================

class TestHealthCheck:
    def test_health_returns_200(self):
        """GET /api/v1/health returns HTTP 200."""
        client = _make_test_client()
        response = client.get("/api/v1/health")
        assert response.status_code == 200

    def test_health_returns_status_ok(self):
        """GET /api/v1/health returns {'status': 'ok'}."""
        client = _make_test_client()
        response = client.get("/api/v1/health")
        body = response.json()
        assert body == {"status": "ok"}


# ===========================================================================
# 6. SQLiteRunRepository — in-memory tests for save/get/list_recent
# ===========================================================================

class TestSQLiteRunRepository:
    def test_save_and_get_round_trip(self):
        """save() then get() returns the same run."""
        repo = _make_in_memory_repository()
        run = _make_validation_run(status="success")
        repo.save(run)

        retrieved = repo.get(run.run_id)
        assert retrieved is not None
        assert retrieved.run_id == run.run_id
        assert retrieved.status == "success"

    def test_save_and_get_preserves_all_fields(self):
        """save() then get() preserves all ValidationRun fields."""
        repo = _make_in_memory_repository()
        run = _make_validation_run(
            status="failure",
            has_conflicts=True,
            changed_files=["src/A.java", "src/B.java"],
            conflict_files=["src/A.java"],
            maven_command=None,
            lifecycle_log=["step: clone", "step: merge-check"],
            error_message=None,
        )
        repo.save(run)

        retrieved = repo.get(run.run_id)
        assert retrieved is not None
        assert retrieved.status == "failure"
        assert retrieved.has_conflicts is True
        assert set(retrieved.changed_files) == {"src/A.java", "src/B.java"}
        assert retrieved.conflict_files == ["src/A.java"]
        assert retrieved.maven_command is None
        assert len(retrieved.lifecycle_log) == 2

    def test_save_updates_existing_run(self):
        """save() with an existing run_id updates the record."""
        repo = _make_in_memory_repository()
        run = _make_validation_run(status="running")
        repo.save(run)

        # Update status
        run.status = "success"
        repo.save(run)

        retrieved = repo.get(run.run_id)
        assert retrieved is not None
        assert retrieved.status == "success"

    def test_list_recent_returns_all_runs(self):
        """list_recent() returns all saved runs."""
        repo = _make_in_memory_repository()
        run1 = _make_validation_run()
        run2 = _make_validation_run()
        run3 = _make_validation_run()
        repo.save(run1)
        repo.save(run2)
        repo.save(run3)

        results = repo.list_recent()
        assert len(results) == 3

    def test_list_recent_preserves_timezone(self):
        """save() and get() preserve timezone-aware datetimes."""
        repo = _make_in_memory_repository()
        now = datetime.now(tz=timezone.utc)
        run = _make_validation_run(started_at=now)
        repo.save(run)

        retrieved = repo.get(run.run_id)
        assert retrieved is not None
        assert retrieved.started_at.tzinfo is not None


# ===========================================================================
# 7. SQLiteRunRepository — get non-existent run_id returns None
# ===========================================================================

class TestSQLiteRunRepositoryGetNonExistent:
    def test_get_nonexistent_run_returns_none(self):
        """get() with a run_id that doesn't exist returns None."""
        repo = _make_in_memory_repository()
        result = repo.get(str(uuid.uuid4()))
        assert result is None

    def test_get_after_empty_db_returns_none(self):
        """get() on an empty database returns None."""
        repo = _make_in_memory_repository()
        result = repo.get("nonexistent-id")
        assert result is None


# ===========================================================================
# 8. SQLiteRunRepository — list_recent returns newest first, respects limit
# ===========================================================================

class TestSQLiteRunRepositoryListRecent:
    def test_list_recent_returns_newest_first(self):
        """list_recent() returns runs in descending order by started_at."""
        repo = _make_in_memory_repository()

        from datetime import timedelta
        base_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

        run_old = _make_validation_run(
            run_id=str(uuid.uuid4()),
            started_at=base_time,
            finished_at=base_time + timedelta(minutes=5),
        )
        run_new = _make_validation_run(
            run_id=str(uuid.uuid4()),
            started_at=base_time + timedelta(hours=1),
            finished_at=base_time + timedelta(hours=1, minutes=5),
        )
        run_middle = _make_validation_run(
            run_id=str(uuid.uuid4()),
            started_at=base_time + timedelta(minutes=30),
            finished_at=base_time + timedelta(minutes=35),
        )

        repo.save(run_old)
        repo.save(run_middle)
        repo.save(run_new)

        results = repo.list_recent(limit=10)
        assert len(results) == 3
        # Newest first
        assert results[0].run_id == run_new.run_id
        assert results[1].run_id == run_middle.run_id
        assert results[2].run_id == run_old.run_id

    def test_list_recent_respects_limit(self):
        """list_recent(limit=N) returns at most N runs."""
        repo = _make_in_memory_repository()

        for _ in range(10):
            repo.save(_make_validation_run())

        results = repo.list_recent(limit=3)
        assert len(results) == 3

    def test_list_recent_empty_when_no_runs(self):
        """list_recent() returns empty list when no runs have been saved."""
        repo = _make_in_memory_repository()
        results = repo.list_recent()
        assert results == []

    def test_list_recent_with_limit_larger_than_count(self):
        """list_recent(limit=100) returns all runs when fewer than 100 exist."""
        repo = _make_in_memory_repository()
        for _ in range(5):
            repo.save(_make_validation_run())

        results = repo.list_recent(limit=100)
        assert len(results) == 5
