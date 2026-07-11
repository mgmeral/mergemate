"""
tests/test_docker_adapter.py

Unit tests for mergemate.execution.docker_adapter.DockerExecutionAdapter.

All Docker SDK calls are mocked — no real Docker daemon required.
"""

from __future__ import annotations

import os
import sys
import threading
from unittest.mock import MagicMock, patch, call

import pytest

_here = os.path.dirname(__file__)
_project_root = os.path.dirname(_here)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from mergemate.execution.adapter import ExecutionAdapter, ExecutionResult
from mergemate.execution.docker_adapter import DockerExecutionAdapter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_adapter(**kwargs) -> DockerExecutionAdapter:
    """Create a DockerExecutionAdapter with sensible test defaults."""
    defaults = {
        "image": "mergemate-worker:latest",
        "ssh_key_path": "/nonexistent/id_rsa",  # no SSH key mount in tests
    }
    defaults.update(kwargs)
    return DockerExecutionAdapter(**defaults)


def _make_mock_container(
    exec_exit_code: int = 0,
    exec_stdout: bytes = b"output",
    exec_stderr: bytes = b"",
) -> MagicMock:
    """Return a mock Docker container with exec_run returning (exit_code, (stdout, stderr))."""
    container = MagicMock()
    container.id = "testcontainerid1234"
    container.exec_run.return_value = (exec_exit_code, (exec_stdout, exec_stderr))
    return container


def _make_mock_docker_client(container: MagicMock) -> MagicMock:
    """Return a mock docker client whose containers.run() returns the given container."""
    client = MagicMock()
    client.containers.run.return_value = container
    return client


# ===========================================================================
# 1. prepare() calls containers.run with correct label, mounts, WORK_DIR
# ===========================================================================

class TestPrepare:
    def test_prepare_calls_containers_run_with_label(self):
        """prepare() must label the container with mergemate.worker=true."""
        container = _make_mock_container()
        mock_client = _make_mock_docker_client(container)

        adapter = _make_adapter()
        with patch("mergemate.execution.docker_adapter.DockerExecutionAdapter._get_docker_client",
                   return_value=mock_client):
            adapter.prepare("/some/project", "feature/branch")

        _, kwargs = mock_client.containers.run.call_args
        assert kwargs["labels"] == {"mergemate.worker": "true"}

    def test_prepare_detach_true_remove_false(self):
        """prepare() must create container with detach=True, remove=False."""
        container = _make_mock_container()
        mock_client = _make_mock_docker_client(container)

        adapter = _make_adapter()
        with patch("mergemate.execution.docker_adapter.DockerExecutionAdapter._get_docker_client",
                   return_value=mock_client):
            adapter.prepare("/some/project", "feature/branch")

        _, kwargs = mock_client.containers.run.call_args
        assert kwargs["detach"] is True
        assert kwargs["remove"] is False

    def test_prepare_returns_work_dir(self):
        """prepare() must return WORK_DIR (/workspace)."""
        container = _make_mock_container()
        mock_client = _make_mock_docker_client(container)

        adapter = _make_adapter()
        with patch("mergemate.execution.docker_adapter.DockerExecutionAdapter._get_docker_client",
                   return_value=mock_client):
            result = adapter.prepare("/some/project", "feature/branch")

        assert result == DockerExecutionAdapter.WORK_DIR
        assert result == "/workspace"

    def test_prepare_mounts_ssh_key_when_file_exists(self, tmp_path):
        """prepare() mounts the SSH key at /home/worker/.ssh/id_rsa (read-only) when it exists."""
        ssh_key = tmp_path / "id_rsa"
        ssh_key.write_text("fake-key")

        container = _make_mock_container()
        mock_client = _make_mock_docker_client(container)

        adapter = DockerExecutionAdapter(
            image="mergemate-worker:latest",
            ssh_key_path=str(ssh_key),
        )
        with patch("mergemate.execution.docker_adapter.DockerExecutionAdapter._get_docker_client",
                   return_value=mock_client):
            adapter.prepare("/some/project", "feature/branch")

        _, kwargs = mock_client.containers.run.call_args
        volumes = kwargs["volumes"]
        assert str(ssh_key) in volumes
        mount = volumes[str(ssh_key)]
        assert mount["bind"] == "/home/worker/.ssh/id_rsa"
        assert mount["mode"] == "ro"

    def test_prepare_no_ssh_mount_when_file_missing(self):
        """prepare() does NOT mount SSH key when the path does not exist."""
        container = _make_mock_container()
        mock_client = _make_mock_docker_client(container)

        adapter = _make_adapter(ssh_key_path="/does/not/exist/id_rsa")
        with patch("mergemate.execution.docker_adapter.DockerExecutionAdapter._get_docker_client",
                   return_value=mock_client):
            adapter.prepare("/some/project", "feature/branch")

        _, kwargs = mock_client.containers.run.call_args
        volumes = kwargs.get("volumes", {})
        assert "/does/not/exist/id_rsa" not in volumes


# ===========================================================================
# 2. execute() calls exec_run with argv list (not shell string)
# ===========================================================================

class TestExecute:
    def _prepared_adapter(self, container: MagicMock) -> DockerExecutionAdapter:
        """Return an adapter whose prepare() has been called."""
        mock_client = _make_mock_docker_client(container)
        adapter = _make_adapter()
        with patch("mergemate.execution.docker_adapter.DockerExecutionAdapter._get_docker_client",
                   return_value=mock_client):
            adapter.prepare("/project", "feature/x")
        # Inject mock container directly so exec_run calls go to it
        adapter._container = container
        return adapter

    def test_execute_calls_exec_run_with_argv_list(self):
        """execute() must pass argv as a list to exec_run (not a shell string)."""
        container = _make_mock_container(exec_stdout=b"hello", exec_stderr=b"")
        adapter = self._prepared_adapter(container)

        argv = ["git", "clone", "https://example.com/repo.git", "/workspace/repo"]
        adapter.execute(argv, working_dir="/workspace")

        container.exec_run.assert_called_once_with(
            cmd=argv,
            workdir="/workspace",
            demux=True,
            stdout=True,
            stderr=True,
        )

    def test_execute_decodes_stdout_from_bytes(self):
        """execute() must decode bytes stdout to str."""
        container = _make_mock_container(exec_stdout=b"hello stdout", exec_stderr=b"")
        adapter = self._prepared_adapter(container)

        result = adapter.execute(["echo", "hello"], working_dir="/workspace")

        assert isinstance(result.stdout, str)
        assert result.stdout == "hello stdout"

    def test_execute_decodes_stderr_from_bytes(self):
        """execute() must decode bytes stderr to str."""
        container = _make_mock_container(exec_stdout=b"", exec_stderr=b"some error")
        adapter = self._prepared_adapter(container)

        result = adapter.execute(["false"], working_dir="/workspace")

        assert isinstance(result.stderr, str)
        assert result.stderr == "some error"

    def test_execute_handles_none_stdout_stderr(self):
        """execute() must handle None stdout/stderr from exec_run gracefully."""
        container = MagicMock()
        container.exec_run.return_value = (0, (None, None))

        adapter = _make_adapter()
        adapter._container = container

        result = adapter.execute(["true"], working_dir="/workspace")

        assert result.exit_code == 0
        assert result.stdout == ""
        assert result.stderr == ""

    def test_execute_returns_correct_exit_code(self):
        """execute() must return the actual exit code from exec_run."""
        container = _make_mock_container(exec_exit_code=42, exec_stdout=b"", exec_stderr=b"err")
        adapter = self._prepared_adapter(container)

        result = adapter.execute(["failing-cmd"], working_dir="/workspace")

        assert result.exit_code == 42

    def test_execute_raises_when_not_prepared(self):
        """execute() raises RuntimeError if prepare() has not been called."""
        adapter = _make_adapter()

        with pytest.raises(RuntimeError, match="prepare"):
            adapter.execute(["git", "status"], working_dir="/workspace")

    def test_execute_returns_execution_result(self):
        """execute() must return an ExecutionResult instance."""
        container = _make_mock_container()
        adapter = self._prepared_adapter(container)

        result = adapter.execute(["ls"], working_dir="/workspace")

        assert isinstance(result, ExecutionResult)


# ===========================================================================
# 3. cleanup() calls stop() + remove(), never raises
# ===========================================================================

class TestCleanup:
    def test_cleanup_calls_stop_and_remove(self):
        """cleanup() must call container.stop() then container.remove()."""
        container = MagicMock()
        adapter = _make_adapter()
        adapter._container = container

        adapter.cleanup()

        container.stop.assert_called_once()
        container.remove.assert_called_once_with(force=True)

    def test_cleanup_never_raises_if_stop_throws(self):
        """cleanup() must not propagate an exception from container.stop()."""
        container = MagicMock()
        container.stop.side_effect = RuntimeError("cannot stop")
        adapter = _make_adapter()
        adapter._container = container

        # Must not raise
        adapter.cleanup()

    def test_cleanup_never_raises_if_remove_throws(self):
        """cleanup() must not propagate an exception from container.remove()."""
        container = MagicMock()
        container.remove.side_effect = RuntimeError("cannot remove")
        adapter = _make_adapter()
        adapter._container = container

        # Must not raise
        adapter.cleanup()

    def test_cleanup_never_raises_if_both_throw(self):
        """cleanup() must not propagate exceptions even if both stop() and remove() throw."""
        container = MagicMock()
        container.stop.side_effect = RuntimeError("stop failed")
        container.remove.side_effect = RuntimeError("remove failed")
        adapter = _make_adapter()
        adapter._container = container

        # Must not raise
        adapter.cleanup()

    def test_cleanup_no_op_when_no_container(self):
        """cleanup() is a no-op when prepare() has never been called."""
        adapter = _make_adapter()
        # Must not raise
        adapter.cleanup()

    def test_cleanup_sets_container_to_none(self):
        """cleanup() must set _container to None after cleanup."""
        container = MagicMock()
        adapter = _make_adapter()
        adapter._container = container

        adapter.cleanup()

        assert adapter._container is None


# ===========================================================================
# 4. Timeout: thread join timeout triggers timed_out=True
# ===========================================================================

class TestTimeout:
    def test_timeout_returns_timed_out_true(self):
        """execute() with a very short timeout returns timed_out=True when exec hangs."""
        import time

        container = MagicMock()

        def slow_exec(**kwargs):
            time.sleep(10)  # simulates a long-running exec
            return (0, (b"", b""))

        container.exec_run.side_effect = slow_exec

        adapter = _make_adapter()
        adapter._container = container

        result = adapter.execute(["sleep", "10"], working_dir="/workspace", timeout_s=1)

        assert result.timed_out is True
        assert result.exit_code == -1

    def test_no_timeout_returns_timed_out_false(self):
        """execute() with a normal execution returns timed_out=False."""
        container = _make_mock_container(exec_stdout=b"done", exec_stderr=b"")
        adapter = _make_adapter()
        adapter._container = container

        result = adapter.execute(["ls"], working_dir="/workspace", timeout_s=30)

        assert result.timed_out is False


# ===========================================================================
# 5. DockerExecutionAdapter is a valid ExecutionAdapter (isinstance check)
# ===========================================================================

class TestIsInstance:
    def test_is_execution_adapter_subclass(self):
        """DockerExecutionAdapter must be a subclass of ExecutionAdapter."""
        assert issubclass(DockerExecutionAdapter, ExecutionAdapter)

    def test_instance_is_execution_adapter(self):
        """An instance of DockerExecutionAdapter must pass isinstance(ExecutionAdapter)."""
        adapter = _make_adapter()
        assert isinstance(adapter, ExecutionAdapter)


# ===========================================================================
# 6. WORK_DIR constant and CLONE_TARGET
# ===========================================================================

class TestConstants:
    def test_work_dir_is_workspace(self):
        """WORK_DIR constant must be '/workspace'."""
        assert DockerExecutionAdapter.WORK_DIR == "/workspace"

    def test_clone_target_is_workspace_repo(self):
        """CLONE_TARGET constant must be '/workspace/repo'."""
        assert DockerExecutionAdapter.CLONE_TARGET == "/workspace/repo"

    def test_container_work_dir_initialised(self):
        """_container_work_dir must be set to WORK_DIR on init."""
        adapter = _make_adapter()
        assert adapter._container_work_dir == DockerExecutionAdapter.WORK_DIR


# ===========================================================================
# 7. Context manager — cleanup called on exit
# ===========================================================================

class TestContextManager:
    def test_context_manager_calls_cleanup_on_normal_exit(self):
        """__exit__ must call cleanup() (stop+remove) on normal exit."""
        container = MagicMock()
        mock_client = _make_mock_docker_client(container)

        adapter = _make_adapter()
        with patch("mergemate.execution.docker_adapter.DockerExecutionAdapter._get_docker_client",
                   return_value=mock_client):
            with adapter:
                adapter._container = container  # simulate prepared state

        container.stop.assert_called()
        container.remove.assert_called()

    def test_context_manager_calls_cleanup_on_exception(self):
        """__exit__ must call cleanup() even if an exception occurs inside the with block."""
        container = MagicMock()
        adapter = _make_adapter()
        adapter._container = container

        with pytest.raises(ValueError, match="simulated"):
            with adapter:
                raise ValueError("simulated")

        container.stop.assert_called()
        container.remove.assert_called()
