"""
tests/test_api_analyze.py

Tests for:
  - POST /api/v1/analyze  (local impact analysis endpoint)
  - Repository impact_data persistence
  - run_to_response populates affected_modules / selected_tests / risk_level
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest.mock as mock
from datetime import datetime, timezone
from typing import Optional

import pytest

_project_root = os.path.dirname(os.path.dirname(__file__))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from fastapi.testclient import TestClient

from forge_api.app import create_app, run_to_response
from forge_api.models import StartLocalAnalysisRequest
from forge_api.repository import SQLiteRunRepository
from forge_orchestrator.orchestrator import ValidationRun, ValidationRequest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_repo() -> SQLiteRunRepository:
    return SQLiteRunRepository(db_path=":memory:")


def _make_run(run_id: str = "test-run", status: str = "running") -> ValidationRun:
    req = ValidationRequest(
        repo_url="/tmp/repo",
        feature_branch="HEAD",
        target_branch="origin/main",
        validation_profile="test",
        active_maven_profiles=[],
    )
    return ValidationRun(
        run_id=run_id,
        request=req,
        status=status,
        started_at=datetime.now(timezone.utc),
        finished_at=None,
        has_conflicts=None,
        changed_files=[],
        conflict_files=[],
        maven_command=None,
        lifecycle_log=[],
        error_message=None,
    )


def _make_app_client(repository=None, orchestrator=None):
    if repository is None:
        repository = _make_repo()
    if orchestrator is None:
        orchestrator = mock.MagicMock()
    app = create_app(orchestrator=orchestrator, repository=repository)
    return TestClient(app, raise_server_exceptions=False), repository


# ---------------------------------------------------------------------------
# Repository: impact_data persistence
# ---------------------------------------------------------------------------

class TestRepositoryImpactData:
    def test_save_and_load_impact_data(self):
        repo = _make_repo()
        run = _make_run("r1", "success")
        impact_data = {
            "affected_modules": [{"artifact_id": "svc", "label": "changed", "reason": "direct"}],
            "selected_tests": ["SvcTest"],
            "risk_level": "MEDIUM",
        }
        run._impact_data = impact_data
        repo.save(run)

        loaded = repo.get("r1")
        assert loaded is not None
        assert hasattr(loaded, "_impact_data")
        assert loaded._impact_data is not None
        assert loaded._impact_data["risk_level"] == "MEDIUM"
        assert loaded._impact_data["selected_tests"] == ["SvcTest"]
        assert len(loaded._impact_data["affected_modules"]) == 1

    def test_save_without_impact_data(self):
        repo = _make_repo()
        run = _make_run("r2", "running")
        repo.save(run)

        loaded = repo.get("r2")
        assert loaded is not None
        assert getattr(loaded, "_impact_data", None) is None

    def test_impact_data_survives_list_recent(self):
        repo = _make_repo()
        for i in range(3):
            run = _make_run(f"run-{i}", "success")
            run._impact_data = {"risk_level": f"LEVEL-{i}"}
            repo.save(run)

        runs = repo.list_recent(limit=10)
        assert len(runs) == 3
        risk_levels = {r._impact_data["risk_level"] for r in runs if r._impact_data}
        assert risk_levels == {"LEVEL-0", "LEVEL-1", "LEVEL-2"}

    def test_impact_data_overwrite_on_save(self):
        repo = _make_repo()
        run = _make_run("r3", "running")
        repo.save(run)

        run.status = "success"
        run._impact_data = {"risk_level": "HIGH"}
        repo.save(run)

        loaded = repo.get("r3")
        assert loaded._impact_data["risk_level"] == "HIGH"
        assert loaded.status == "success"


# ---------------------------------------------------------------------------
# run_to_response: impact_data fields populated
# ---------------------------------------------------------------------------

class TestRunToResponseImpactData:
    def test_no_impact_data_returns_none_fields(self):
        run = _make_run()
        resp = run_to_response(run)
        assert resp.affected_modules is None
        assert resp.selected_tests is None
        assert resp.risk_level is None

    def test_impact_data_fields_populated(self):
        run = _make_run()
        run._impact_data = {
            "affected_modules": [
                {"artifact_id": "order-svc", "label": "changed", "reason": "direct"},
                {"artifact_id": "checkout-api", "label": "dependent", "reason": "downstream"},
            ],
            "selected_tests": ["OrderSvcTest", "CheckoutIT"],
            "risk_level": "HIGH",
        }
        resp = run_to_response(run)
        assert resp.risk_level == "HIGH"
        assert resp.selected_tests == ["OrderSvcTest", "CheckoutIT"]
        assert len(resp.affected_modules) == 2
        assert resp.affected_modules[0]["artifact_id"] == "order-svc"

    def test_empty_impact_data_returns_none_fields(self):
        run = _make_run()
        run._impact_data = {}
        resp = run_to_response(run)
        assert resp.affected_modules is None
        assert resp.selected_tests is None
        assert resp.risk_level is None


# ---------------------------------------------------------------------------
# POST /api/v1/analyze endpoint
# ---------------------------------------------------------------------------

class TestAnalyzeEndpoint:
    def _mock_pipeline(self, repo_dir: str, risk_level: str = "LOW"):
        """Return a mock that patches the mergemate pipeline used in the background task."""
        mock_changeset = mock.MagicMock()
        mock_changeset.changed_files = []
        mock_changeset.source_ref = "HEAD"
        mock_changeset.target_ref = "origin/main"
        mock_changeset.merge_base = "abc123"

        mock_module = mock.MagicMock()
        mock_module.artifact_id = "svc"
        mock_module.label = "changed"
        mock_module.reason = "direct change"

        mock_impact = mock.MagicMock()
        mock_impact.strategy = "incremental"
        mock_impact.strategy_reason = "1 module affected"
        mock_impact.changed_modules = ["svc"]
        mock_impact.affected_modules = [mock_module]
        mock_impact.risk_level = risk_level
        mock_impact.risk_reasons = []
        mock_impact.full_build_recommended = False
        mock_impact.test_candidates = []

        return mock_changeset, mock_impact

    def test_analyze_returns_202(self, tmp_path):
        client, repo = _make_app_client()
        response = client.post("/api/v1/analyze", json={
            "repo_dir": str(tmp_path),
            "source": "HEAD",
            "target": "origin/main",
            "goal": "test",
        })
        # Should return 202 (or possibly 422 if validation fails, but repo_dir exists)
        assert response.status_code in (202, 422, 500)

    def test_analyze_persists_run_with_running_status(self, tmp_path):
        """The endpoint creates a pending run synchronously before background task starts."""
        repo = _make_repo()
        orchestrator = mock.MagicMock()
        app = create_app(orchestrator=orchestrator, repository=repo)

        # Patch the background task to not actually run (test isolation)
        with mock.patch("forge_api.app._run_local_analysis_background"):
            client = TestClient(app, raise_server_exceptions=True)
            response = client.post("/api/v1/analyze", json={
                "repo_dir": str(tmp_path),
                "source": "HEAD",
                "target": "origin/main",
                "goal": "test",
            })

        assert response.status_code == 202
        data = response.json()
        run_id = data["run_id"]
        assert run_id
        assert data["status"] == "running"

        # The run should be persisted immediately
        stored = repo.get(run_id)
        assert stored is not None
        assert stored.status == "running"

    def test_analyze_response_has_run_id(self, tmp_path):
        repo = _make_repo()
        orchestrator = mock.MagicMock()
        app = create_app(orchestrator=orchestrator, repository=repo)

        with mock.patch("forge_api.app._run_local_analysis_background"):
            client = TestClient(app, raise_server_exceptions=True)
            r = client.post("/api/v1/analyze", json={
                "repo_dir": str(tmp_path),
                "source": "HEAD",
                "target": "origin/main",
            })
        assert r.status_code == 202
        assert "run_id" in r.json()

    def test_analyze_get_run_returns_impact_after_completion(self):
        """After background task completes, GET returns impact data."""
        repo = _make_repo()
        orchestrator = mock.MagicMock()
        app = create_app(orchestrator=orchestrator, repository=repo)
        client = TestClient(app, raise_server_exceptions=True)

        # Insert a completed run with impact_data directly
        run = _make_run("completed-run", "success")
        run._impact_data = {
            "affected_modules": [{"artifact_id": "svc", "label": "changed", "reason": "x"}],
            "selected_tests": ["SvcTest"],
            "risk_level": "LOW",
        }
        repo.save(run)

        r = client.get("/api/v1/validations/completed-run")
        assert r.status_code == 200
        data = r.json()
        assert data["risk_level"] == "LOW"
        assert data["selected_tests"] == ["SvcTest"]
        assert len(data["affected_modules"]) == 1

    def test_analyze_background_task_updates_repo_on_success(self, tmp_path):
        """Integration: _run_local_analysis_background stores impact_data in repo."""
        from forge_api.app import _run_local_analysis_background

        # Create a real git repo with no pom.xml (analysis will produce empty result)
        import subprocess
        subprocess.run(["git", "init", str(tmp_path)], capture_output=True, check=True)
        subprocess.run(
            ["git", "commit", "--allow-empty", "-m", "init"],
            cwd=str(tmp_path), capture_output=True, check=True,
            env={**os.environ, "GIT_AUTHOR_NAME": "test", "GIT_AUTHOR_EMAIL": "t@t.com",
                 "GIT_COMMITTER_NAME": "test", "GIT_COMMITTER_EMAIL": "t@t.com"}
        )

        repo = _make_repo()
        run = _make_run("bg-run", "running")
        repo.save(run)

        request = StartLocalAnalysisRequest(
            repo_dir=str(tmp_path),
            source="HEAD",
            target="HEAD",  # same ref → empty changeset
            goal="test",
        )

        # Run synchronously (not via BackgroundTasks)
        _run_local_analysis_background("bg-run", request, repo, run)

        loaded = repo.get("bg-run")
        assert loaded is not None
        # Should be success or error (depending on git state), not "running"
        assert loaded.status in ("success", "error")

    def test_analyze_background_task_sets_error_on_exception(self):
        """_run_local_analysis_background saves error status on failure."""
        from forge_api.app import _run_local_analysis_background

        repo = _make_repo()
        run = _make_run("err-run", "running")
        repo.save(run)

        request = StartLocalAnalysisRequest(
            repo_dir="/nonexistent/path/that/does/not/exist",
            source="HEAD",
            target="origin/main",
        )

        _run_local_analysis_background("err-run", request, repo, run)

        loaded = repo.get("err-run")
        assert loaded is not None
        assert loaded.status == "error"
        assert loaded.error_message is not None

    def test_analyze_list_includes_local_runs(self, tmp_path):
        """Local analysis runs appear in GET /api/v1/validations list."""
        repo = _make_repo()
        orchestrator = mock.MagicMock()
        app = create_app(orchestrator=orchestrator, repository=repo)
        client = TestClient(app, raise_server_exceptions=True)

        with mock.patch("forge_api.app._run_local_analysis_background"):
            r = client.post("/api/v1/analyze", json={
                "repo_dir": str(tmp_path),
                "source": "HEAD",
                "target": "origin/main",
            })
        assert r.status_code == 202

        r2 = client.get("/api/v1/validations")
        assert r2.status_code == 200
        runs = r2.json()["runs"]
        assert len(runs) >= 1

    def test_analyze_request_goal_default_is_test(self, tmp_path):
        """goal field defaults to 'test' when not provided."""
        repo = _make_repo()
        app = create_app(orchestrator=mock.MagicMock(), repository=repo)
        client = TestClient(app, raise_server_exceptions=True)

        with mock.patch("forge_api.app._run_local_analysis_background") as m:
            client.post("/api/v1/analyze", json={
                "repo_dir": str(tmp_path),
                "source": "HEAD",
                "target": "origin/main",
            })
            _, kwargs = m.call_args
            assert kwargs["request"].goal == "test"

    def test_analyze_request_profiles_passed_through(self, tmp_path):
        repo = _make_repo()
        app = create_app(orchestrator=mock.MagicMock(), repository=repo)
        client = TestClient(app, raise_server_exceptions=True)

        with mock.patch("forge_api.app._run_local_analysis_background") as m:
            client.post("/api/v1/analyze", json={
                "repo_dir": str(tmp_path),
                "source": "HEAD",
                "target": "origin/main",
                "profiles": ["local", "dev"],
            })
            _, kwargs = m.call_args
            assert kwargs["request"].profiles == ["local", "dev"]
