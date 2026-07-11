"""
tests/test_orchestrator.py

Unit tests for forge_orchestrator: Worker, Orchestrator, and reaper.

No real Docker daemon required — all Docker SDK calls are mocked.
"""

from __future__ import annotations

import os
import sys
import threading
import uuid
from datetime import datetime
from unittest.mock import MagicMock, call, patch

import pytest

_here = os.path.dirname(__file__)
_project_root = os.path.dirname(_here)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from forge_orchestrator.worker import Worker, WorkerConfig, WORKER_LABEL
from forge_orchestrator.orchestrator import (
    Orchestrator,
    ValidationRequest,
    ValidationRun,
)
from forge_orchestrator.reaper import reap_orphans, start_reaper_thread


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

def _make_worker_config() -> WorkerConfig:
    return WorkerConfig(
        image="mergemate-worker:latest",
        remote_url="git@github.com:example/repo.git",
        ssh_key_path="/home/user/.ssh/id_rsa",
        work_dir="/workspace",
    )


def _make_request() -> ValidationRequest:
    return ValidationRequest(
        repo_url="git@github.com:example/repo.git",
        feature_branch="feature/my-branch",
        target_branch="main",
    )


def _make_mock_container(
    exec_exit_code: int = 0,
    exec_stdout: bytes = b"output",
    exec_stderr: bytes = b"",
) -> MagicMock:
    """Return a mock Docker container with sensible defaults."""
    container = MagicMock()
    container.id = "abc123def456" * 2  # 24-char fake id

    exec_result = MagicMock()
    exec_result.exit_code = exec_exit_code
    exec_result.output = (exec_stdout, exec_stderr)
    container.exec_run.return_value = exec_result

    return container


# ===========================================================================
# 1. Worker.start() — correct label, mounts, and user
# ===========================================================================

class TestWorkerStart:
    def test_start_calls_containers_run_with_correct_label(self):
        """start() must label the container with WORKER_LABEL=true."""
        mock_container = _make_mock_container()

        with patch("forge_orchestrator.worker.docker") as mock_docker:
            mock_client = MagicMock()
            mock_docker.from_env.return_value = mock_client
            mock_client.containers.run.return_value = mock_container

            cfg = _make_worker_config()
            worker = Worker(cfg)
            worker.start()

            _, kwargs = mock_client.containers.run.call_args
            assert kwargs["labels"] == {WORKER_LABEL: "true"}

    def test_start_mounts_ssh_key_read_only(self):
        """start() must mount the SSH key as read-only at /home/worker/.ssh/id_rsa."""
        mock_container = _make_mock_container()

        with patch("forge_orchestrator.worker.docker") as mock_docker:
            mock_client = MagicMock()
            mock_docker.from_env.return_value = mock_client
            mock_client.containers.run.return_value = mock_container

            cfg = _make_worker_config()
            worker = Worker(cfg)
            worker.start()

            _, kwargs = mock_client.containers.run.call_args
            volumes = kwargs["volumes"]
            assert cfg.ssh_key_path in volumes
            mount = volumes[cfg.ssh_key_path]
            assert mount["bind"] == "/home/worker/.ssh/id_rsa"
            assert mount["mode"] == "ro"

    def test_start_sets_correct_user(self):
        """start() must run the container as user 'worker'."""
        mock_container = _make_mock_container()

        with patch("forge_orchestrator.worker.docker") as mock_docker:
            mock_client = MagicMock()
            mock_docker.from_env.return_value = mock_client
            mock_client.containers.run.return_value = mock_container

            cfg = _make_worker_config()
            worker = Worker(cfg)
            worker.start()

            _, kwargs = mock_client.containers.run.call_args
            assert kwargs["user"] == "worker"

    def test_start_returns_container_id(self):
        """start() must return the container id string."""
        mock_container = _make_mock_container()
        mock_container.id = "deadbeef1234"

        with patch("forge_orchestrator.worker.docker") as mock_docker:
            mock_client = MagicMock()
            mock_docker.from_env.return_value = mock_client
            mock_client.containers.run.return_value = mock_container

            cfg = _make_worker_config()
            worker = Worker(cfg)
            cid = worker.start()

            assert cid == "deadbeef1234"

    def test_start_uses_detach_true_remove_false(self):
        """Container must be created with detach=True, remove=False."""
        mock_container = _make_mock_container()

        with patch("forge_orchestrator.worker.docker") as mock_docker:
            mock_client = MagicMock()
            mock_docker.from_env.return_value = mock_client
            mock_client.containers.run.return_value = mock_container

            cfg = _make_worker_config()
            worker = Worker(cfg)
            worker.start()

            _, kwargs = mock_client.containers.run.call_args
            assert kwargs["detach"] is True
            assert kwargs["remove"] is False


# ===========================================================================
# 2. Worker.stop() — calls stop + remove, never raises
# ===========================================================================

class TestWorkerStop:
    def test_stop_calls_container_stop_and_remove(self):
        """stop() must call container.stop() then container.remove()."""
        mock_container = _make_mock_container()

        with patch("forge_orchestrator.worker.docker") as mock_docker:
            mock_client = MagicMock()
            mock_docker.from_env.return_value = mock_client
            mock_client.containers.run.return_value = mock_container

            cfg = _make_worker_config()
            worker = Worker(cfg)
            worker.start()
            worker.stop()

            mock_container.stop.assert_called_once()
            mock_container.remove.assert_called_once()

    def test_stop_never_raises_even_if_stop_throws(self):
        """stop() must not propagate exceptions from container.stop()."""
        mock_container = _make_mock_container()
        mock_container.stop.side_effect = RuntimeError("cannot stop")

        with patch("forge_orchestrator.worker.docker") as mock_docker:
            mock_client = MagicMock()
            mock_docker.from_env.return_value = mock_client
            mock_client.containers.run.return_value = mock_container

            cfg = _make_worker_config()
            worker = Worker(cfg)
            worker.start()

            # Must not raise
            worker.stop()

    def test_stop_never_raises_even_if_remove_throws(self):
        """stop() must not propagate exceptions from container.remove()."""
        mock_container = _make_mock_container()
        mock_container.remove.side_effect = RuntimeError("cannot remove")

        with patch("forge_orchestrator.worker.docker") as mock_docker:
            mock_client = MagicMock()
            mock_docker.from_env.return_value = mock_client
            mock_client.containers.run.return_value = mock_container

            cfg = _make_worker_config()
            worker = Worker(cfg)
            worker.start()

            # Must not raise
            worker.stop()

    def test_stop_does_nothing_if_not_started(self):
        """stop() on an un-started worker must be a no-op (no error)."""
        with patch("forge_orchestrator.worker.docker"):
            cfg = _make_worker_config()
            worker = Worker(cfg)
            worker.stop()  # should not raise


# ===========================================================================
# 3. Worker.exec() — argv list, not shell; stdout/stderr decoded
# ===========================================================================

class TestWorkerExec:
    def test_exec_calls_exec_run_with_argv_list(self):
        """exec() must pass argv as a list to container.exec_run (not a shell string)."""
        mock_container = _make_mock_container(exec_stdout=b"hello", exec_stderr=b"")

        with patch("forge_orchestrator.worker.docker") as mock_docker:
            mock_client = MagicMock()
            mock_docker.from_env.return_value = mock_client
            mock_client.containers.run.return_value = mock_container

            cfg = _make_worker_config()
            worker = Worker(cfg)
            worker.start()

            argv = ["git", "clone", "https://example.com/repo.git", "/workspace"]
            worker.exec(argv)

            mock_container.exec_run.assert_called_once_with(
                cmd=argv,
                demux=True,
            )

    def test_exec_decodes_stdout_stderr(self):
        """exec() must decode bytes stdout/stderr to str and return (exit_code, stdout, stderr)."""
        mock_container = _make_mock_container(
            exec_exit_code=0,
            exec_stdout=b"hello stdout",
            exec_stderr=b"hello stderr",
        )

        with patch("forge_orchestrator.worker.docker") as mock_docker:
            mock_client = MagicMock()
            mock_docker.from_env.return_value = mock_client
            mock_client.containers.run.return_value = mock_container

            cfg = _make_worker_config()
            worker = Worker(cfg)
            worker.start()

            rc, stdout, stderr = worker.exec(["echo", "hello"])

            assert rc == 0
            assert stdout == "hello stdout"
            assert stderr == "hello stderr"

    def test_exec_handles_none_output(self):
        """exec() must handle when output tuple has None entries (empty streams)."""
        mock_container = MagicMock()
        exec_result = MagicMock()
        exec_result.exit_code = 0
        exec_result.output = (None, None)
        mock_container.exec_run.return_value = exec_result

        with patch("forge_orchestrator.worker.docker") as mock_docker:
            mock_client = MagicMock()
            mock_docker.from_env.return_value = mock_client
            mock_client.containers.run.return_value = mock_container

            cfg = _make_worker_config()
            worker = Worker(cfg)
            worker.start()

            rc, stdout, stderr = worker.exec(["true"])

            assert rc == 0
            assert stdout == ""
            assert stderr == ""

    def test_exec_returns_nonzero_exit_code(self):
        """exec() must return the actual exit code from exec_run."""
        mock_container = _make_mock_container(
            exec_exit_code=1,
            exec_stdout=b"",
            exec_stderr=b"error occurred",
        )

        with patch("forge_orchestrator.worker.docker") as mock_docker:
            mock_client = MagicMock()
            mock_docker.from_env.return_value = mock_client
            mock_client.containers.run.return_value = mock_container

            cfg = _make_worker_config()
            worker = Worker(cfg)
            worker.start()

            rc, stdout, stderr = worker.exec(["false"])

            assert rc == 1
            assert stderr == "error occurred"


# ===========================================================================
# 4. Worker context manager — guaranteed teardown
# ===========================================================================

class TestWorkerContextManager:
    def test_exit_calls_stop_on_normal_exit(self):
        """__exit__ must call stop() on clean exit."""
        mock_container = _make_mock_container()

        with patch("forge_orchestrator.worker.docker") as mock_docker:
            mock_client = MagicMock()
            mock_docker.from_env.return_value = mock_client
            mock_client.containers.run.return_value = mock_container

            cfg = _make_worker_config()
            worker = Worker(cfg)

            with worker:
                pass

            mock_container.stop.assert_called_once()
            mock_container.remove.assert_called_once()

    def test_exit_calls_stop_even_when_exception_raised(self):
        """__exit__ must call stop() even if an exception occurs inside the with block."""
        mock_container = _make_mock_container()

        with patch("forge_orchestrator.worker.docker") as mock_docker:
            mock_client = MagicMock()
            mock_docker.from_env.return_value = mock_client
            mock_client.containers.run.return_value = mock_container

            cfg = _make_worker_config()
            worker = Worker(cfg)

            with pytest.raises(ValueError, match="simulated failure"):
                with worker:
                    raise ValueError("simulated failure")

            # stop() still called despite the exception
            mock_container.stop.assert_called_once()
            mock_container.remove.assert_called_once()

    def test_enter_returns_worker_instance(self):
        """__enter__ must return the Worker instance itself."""
        mock_container = _make_mock_container()

        with patch("forge_orchestrator.worker.docker") as mock_docker:
            mock_client = MagicMock()
            mock_docker.from_env.return_value = mock_client
            mock_client.containers.run.return_value = mock_container

            cfg = _make_worker_config()
            worker = Worker(cfg)

            with worker as w:
                assert w is worker


# ===========================================================================
# 5. Orchestrator.run() — success / failure / error paths
# ===========================================================================

class TestOrchestratorRun:
    """
    All Docker and lifecycle calls are mocked so no real Docker host is needed.
    """

    def _make_mock_lifecycle_result(
        self,
        has_conflicts: bool = False,
        changed_files: list[str] | None = None,
        conflict_files: list[str] | None = None,
        maven_command: str | None = "mvn clean verify",
    ):
        from forge_worker.lifecycle import ValidationResult
        return ValidationResult(
            has_conflicts=has_conflicts,
            changed_files=changed_files or ["src/Foo.java"],
            conflict_files=conflict_files or [],
            maven_command=maven_command,
            lifecycle_log=["step: clone", "step: fetch", "step: checkout",
                           "step: merge-check", "step: diff"],
        )

    def test_success_run_returns_status_success(self):
        """A clean run (no conflicts, build succeeds) returns status='success'."""
        lifecycle_result = self._make_mock_lifecycle_result(has_conflicts=False)

        mock_container = _make_mock_container(exec_exit_code=0)

        with patch("forge_orchestrator.worker.docker") as mock_docker, \
             patch("forge_orchestrator.orchestrator.ValidationLifecycle") as mock_lc_cls, \
             patch("forge_orchestrator.orchestrator.planner_plan") as mock_plan:

            # Docker setup
            mock_client = MagicMock()
            mock_docker.from_env.return_value = mock_client
            mock_client.containers.run.return_value = mock_container

            # Lifecycle returns a clean result
            mock_lc = MagicMock()
            mock_lc.run.return_value = lifecycle_result
            mock_lc_cls.return_value = mock_lc

            # Planner returns a plan
            mock_exec_plan = MagicMock()
            mock_exec_plan.maven_command = "mvn clean verify"
            mock_plan.return_value = mock_exec_plan

            # Worker exec for Maven build succeeds
            exec_result = MagicMock()
            exec_result.exit_code = 0
            exec_result.output = (b"BUILD SUCCESS", b"")
            mock_container.exec_run.return_value = exec_result

            orchestrator = Orchestrator(_make_worker_config())
            run = orchestrator.run(_make_request())

        assert run.status == "success"
        assert run.has_conflicts is False
        assert run.changed_files == ["src/Foo.java"]
        assert run.finished_at is not None

    def test_failure_run_when_conflicts_detected(self):
        """A run with conflicts returns status='failure'."""
        lifecycle_result = self._make_mock_lifecycle_result(
            has_conflicts=True,
            conflict_files=["src/Conflict.java"],
        )

        mock_container = _make_mock_container()

        with patch("forge_orchestrator.worker.docker") as mock_docker, \
             patch("forge_orchestrator.orchestrator.ValidationLifecycle") as mock_lc_cls, \
             patch("forge_orchestrator.orchestrator.planner_plan") as mock_plan:

            mock_client = MagicMock()
            mock_docker.from_env.return_value = mock_client
            mock_client.containers.run.return_value = mock_container

            mock_lc = MagicMock()
            mock_lc.run.return_value = lifecycle_result
            mock_lc_cls.return_value = mock_lc

            orchestrator = Orchestrator(_make_worker_config())
            run = orchestrator.run(_make_request())

        assert run.status == "failure"
        assert run.has_conflicts is True
        assert "src/Conflict.java" in run.conflict_files
        assert run.maven_command is None
        assert run.finished_at is not None
        # Planner should not be called when there are conflicts
        mock_plan.assert_not_called()

    def test_error_run_when_lifecycle_raises(self):
        """An exception from the lifecycle returns status='error' with error_message set."""
        mock_container = _make_mock_container()

        with patch("forge_orchestrator.worker.docker") as mock_docker, \
             patch("forge_orchestrator.orchestrator.ValidationLifecycle") as mock_lc_cls:

            mock_client = MagicMock()
            mock_docker.from_env.return_value = mock_client
            mock_client.containers.run.return_value = mock_container

            mock_lc = MagicMock()
            mock_lc.run.side_effect = RuntimeError("git clone failed")
            mock_lc_cls.return_value = mock_lc

            orchestrator = Orchestrator(_make_worker_config())
            run = orchestrator.run(_make_request())

        assert run.status == "error"
        assert run.error_message is not None
        assert "git clone failed" in run.error_message
        assert run.finished_at is not None

    def test_error_run_when_worker_start_raises(self):
        """An exception from Worker.start() (Docker failure) returns status='error'."""
        with patch("forge_orchestrator.worker.docker") as mock_docker:
            mock_client = MagicMock()
            mock_docker.from_env.return_value = mock_client
            mock_client.containers.run.side_effect = RuntimeError("Docker unavailable")

            orchestrator = Orchestrator(_make_worker_config())
            run = orchestrator.run(_make_request())

        assert run.status == "error"
        assert run.error_message is not None
        assert "Docker unavailable" in run.error_message

    def test_run_id_is_valid_uuid4(self):
        """run_id must be a valid UUID4 string."""
        lifecycle_result = self._make_mock_lifecycle_result(has_conflicts=False)
        mock_container = _make_mock_container(exec_exit_code=0)

        with patch("forge_orchestrator.worker.docker") as mock_docker, \
             patch("forge_orchestrator.orchestrator.ValidationLifecycle") as mock_lc_cls, \
             patch("forge_orchestrator.orchestrator.planner_plan") as mock_plan:

            mock_client = MagicMock()
            mock_docker.from_env.return_value = mock_client
            mock_client.containers.run.return_value = mock_container

            mock_lc = MagicMock()
            mock_lc.run.return_value = lifecycle_result
            mock_lc_cls.return_value = mock_lc

            mock_exec_plan = MagicMock()
            mock_exec_plan.maven_command = "mvn clean verify"
            mock_plan.return_value = mock_exec_plan

            exec_result = MagicMock()
            exec_result.exit_code = 0
            exec_result.output = (b"BUILD SUCCESS", b"")
            mock_container.exec_run.return_value = exec_result

            orchestrator = Orchestrator(_make_worker_config())
            run = orchestrator.run(_make_request())

        # Validate it's a proper UUID4
        parsed = uuid.UUID(run.run_id, version=4)
        assert str(parsed) == run.run_id

    def test_started_at_and_finished_at_are_set(self):
        """started_at and finished_at must be datetime objects and finished >= started."""
        lifecycle_result = self._make_mock_lifecycle_result(has_conflicts=False)
        mock_container = _make_mock_container(exec_exit_code=0)

        with patch("forge_orchestrator.worker.docker") as mock_docker, \
             patch("forge_orchestrator.orchestrator.ValidationLifecycle") as mock_lc_cls, \
             patch("forge_orchestrator.orchestrator.planner_plan") as mock_plan:

            mock_client = MagicMock()
            mock_docker.from_env.return_value = mock_client
            mock_client.containers.run.return_value = mock_container

            mock_lc = MagicMock()
            mock_lc.run.return_value = lifecycle_result
            mock_lc_cls.return_value = mock_lc

            mock_exec_plan = MagicMock()
            mock_exec_plan.maven_command = "mvn clean verify"
            mock_plan.return_value = mock_exec_plan

            exec_result = MagicMock()
            exec_result.exit_code = 0
            exec_result.output = (b"BUILD SUCCESS", b"")
            mock_container.exec_run.return_value = exec_result

            orchestrator = Orchestrator(_make_worker_config())
            run = orchestrator.run(_make_request())

        assert isinstance(run.started_at, datetime)
        assert isinstance(run.finished_at, datetime)
        assert run.finished_at >= run.started_at

    def test_worker_is_torn_down_after_exception(self):
        """Worker.stop() must be called even when an exception occurs during validation."""
        mock_container = _make_mock_container()

        with patch("forge_orchestrator.worker.docker") as mock_docker, \
             patch("forge_orchestrator.orchestrator.ValidationLifecycle") as mock_lc_cls:

            mock_client = MagicMock()
            mock_docker.from_env.return_value = mock_client
            mock_client.containers.run.return_value = mock_container

            mock_lc = MagicMock()
            mock_lc.run.side_effect = RuntimeError("unexpected failure")
            mock_lc_cls.return_value = mock_lc

            orchestrator = Orchestrator(_make_worker_config())
            run = orchestrator.run(_make_request())

        # Worker must have been torn down (stop + remove called)
        mock_container.stop.assert_called()
        mock_container.remove.assert_called()
        assert run.status == "error"

    def test_error_run_when_maven_build_fails(self):
        """A non-zero Maven exit code returns status='error'."""
        lifecycle_result = self._make_mock_lifecycle_result(has_conflicts=False)
        mock_container = MagicMock()
        mock_container.id = "containerid"

        with patch("forge_orchestrator.worker.docker") as mock_docker, \
             patch("forge_orchestrator.orchestrator.ValidationLifecycle") as mock_lc_cls, \
             patch("forge_orchestrator.orchestrator.planner_plan") as mock_plan:

            mock_client = MagicMock()
            mock_docker.from_env.return_value = mock_client
            mock_client.containers.run.return_value = mock_container

            mock_lc = MagicMock()
            mock_lc.run.return_value = lifecycle_result
            mock_lc_cls.return_value = mock_lc

            mock_exec_plan = MagicMock()
            mock_exec_plan.maven_command = "mvn clean verify"
            mock_plan.return_value = mock_exec_plan

            # Maven build fails
            exec_result = MagicMock()
            exec_result.exit_code = 1
            exec_result.output = (b"", b"BUILD FAILURE")
            mock_container.exec_run.return_value = exec_result

            orchestrator = Orchestrator(_make_worker_config())
            run = orchestrator.run(_make_request())

        assert run.status == "error"
        assert run.error_message is not None


# ===========================================================================
# 6. reap_orphans() — finds containers by label, calls remove()
# ===========================================================================

class TestReapOrphans:
    def test_reap_removes_labelled_containers(self):
        """reap_orphans() must call remove(force=True) on each labelled container."""
        mock_container_1 = MagicMock()
        mock_container_1.id = "aaa111"
        mock_container_2 = MagicMock()
        mock_container_2.id = "bbb222"

        mock_client = MagicMock()
        mock_client.containers.list.return_value = [mock_container_1, mock_container_2]

        removed = reap_orphans(docker_client=mock_client)

        mock_client.containers.list.assert_called_once_with(
            all=True,
            filters={"label": f"{WORKER_LABEL}=true"},
        )
        mock_container_1.remove.assert_called_once_with(force=True)
        mock_container_2.remove.assert_called_once_with(force=True)
        assert set(removed) == {"aaa111", "bbb222"}

    def test_reap_dry_run_returns_ids_without_removing(self):
        """dry_run=True must return container IDs without calling remove()."""
        mock_container_1 = MagicMock()
        mock_container_1.id = "ccc333"
        mock_container_2 = MagicMock()
        mock_container_2.id = "ddd444"

        mock_client = MagicMock()
        mock_client.containers.list.return_value = [mock_container_1, mock_container_2]

        removed = reap_orphans(docker_client=mock_client, dry_run=True)

        # remove() must NOT be called in dry_run mode
        mock_container_1.remove.assert_not_called()
        mock_container_2.remove.assert_not_called()
        assert set(removed) == {"ccc333", "ddd444"}

    def test_reap_returns_empty_list_when_no_orphans(self):
        """reap_orphans() with no matching containers returns an empty list."""
        mock_client = MagicMock()
        mock_client.containers.list.return_value = []

        removed = reap_orphans(docker_client=mock_client)

        assert removed == []

    def test_reap_continues_on_remove_failure(self):
        """reap_orphans() must not raise if one container fails to be removed."""
        mock_container_ok = MagicMock()
        mock_container_ok.id = "eee555"

        mock_container_fail = MagicMock()
        mock_container_fail.id = "fff666"
        mock_container_fail.remove.side_effect = RuntimeError("permission denied")

        mock_client = MagicMock()
        mock_client.containers.list.return_value = [mock_container_fail, mock_container_ok]

        # Must not raise
        removed = reap_orphans(docker_client=mock_client)

        # Only the successful one is in the returned list
        assert "eee555" in removed
        assert "fff666" not in removed

    def test_reap_uses_docker_from_env_when_no_client_provided(self):
        """reap_orphans() without a client calls docker.from_env()."""
        mock_client = MagicMock()
        mock_client.containers.list.return_value = []

        with patch("forge_orchestrator.reaper.docker_sdk") as mock_sdk:
            mock_sdk.from_env.return_value = mock_client
            reap_orphans()

        mock_sdk.from_env.assert_called_once()


# ===========================================================================
# 7. start_reaper_thread() — returns a running daemon thread
# ===========================================================================

class TestStartReaperThread:
    def test_returns_running_daemon_thread(self):
        """start_reaper_thread() must return a Thread that is alive and a daemon."""
        mock_client = MagicMock()
        mock_client.containers.list.return_value = []

        thread = start_reaper_thread(interval_s=3600, docker_client=mock_client)

        assert isinstance(thread, threading.Thread)
        assert thread.is_alive()
        assert thread.daemon is True

    def test_thread_has_expected_name(self):
        """The reaper thread name should contain 'mergemate-reaper'."""
        mock_client = MagicMock()
        mock_client.containers.list.return_value = []

        thread = start_reaper_thread(interval_s=3600, docker_client=mock_client)

        assert "mergemate-reaper" in thread.name
