"""
mergemate/execution/docker_adapter.py

Docker-based ExecutionAdapter.

Fixes vs. original forge_orchestrator:
- Consistent container path: /workspace (was /workspace vs /work/repo mismatch)
- Explicit target branch fetch before merge-base computation
- Real timeout: thread-based timeout on exec_run
- stdout/stderr always captured (demux=True) and decoded
- Guard checked before every git command (delegated to lifecycle)
"""

from __future__ import annotations

import os
import threading
from typing import Optional

from mergemate.execution.adapter import ExecutionAdapter, ExecutionResult


class DockerExecutionAdapter(ExecutionAdapter):
    """
    Runs validation inside a Docker worker container.

    Fixes vs. original forge_orchestrator:
    - Consistent container path: /workspace (was /workspace vs /work/repo mismatch)
    - Explicit target branch fetch before merge-base computation
    - Real timeout: exec_run with thread-based socket timeout
    - stdout/stderr always captured (demux=True)
    - Guard checked before every git command
    """

    WORK_DIR = "/workspace"         # consistent path inside container
    CLONE_TARGET = "/workspace/repo"  # clone subdirectory, avoids permission issues

    def __init__(
        self,
        image: str = "mergemate-worker:latest",
        ssh_key_path: Optional[str] = None,
        mem_limit: str = "2g",
        nano_cpus: int = 2_000_000_000,
    ) -> None:
        self.image = image
        self.ssh_key_path = ssh_key_path or os.path.expanduser("~/.ssh/id_rsa")
        self.mem_limit = mem_limit
        self.nano_cpus = nano_cpus
        self._container = None
        self._client = None
        self._container_work_dir = self.WORK_DIR

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_docker_client(self):
        """Lazily import and initialise the Docker client."""
        try:
            import docker  # noqa: PLC0415
        except ImportError:
            raise RuntimeError("docker SDK not installed; run: pip install docker")
        return docker.from_env()

    def _exec_with_timeout(
        self,
        container,
        argv: list[str],
        workdir: str,
        timeout_s: int,
    ) -> tuple[int, bytes, bytes, bool]:
        """
        Run exec_run inside a daemon thread so we can apply a wall-clock timeout.

        Returns (exit_code, stdout_bytes, stderr_bytes, timed_out).
        """
        result_holder: dict = {}

        def _run() -> None:
            try:
                exit_code, (stdout, stderr) = container.exec_run(
                    cmd=argv,
                    workdir=workdir,
                    demux=True,
                    stdout=True,
                    stderr=True,
                )
                result_holder["exit_code"] = exit_code
                result_holder["stdout"] = stdout or b""
                result_holder["stderr"] = stderr or b""
            except Exception as exc:  # noqa: BLE001
                result_holder["error"] = str(exc)

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()
        thread.join(timeout=timeout_s)

        if thread.is_alive():
            return -1, b"", b"Execution timed out", True

        if "error" in result_holder:
            return -1, b"", result_holder["error"].encode(), False

        return (
            result_holder.get("exit_code", -1),
            result_holder.get("stdout", b""),
            result_holder.get("stderr", b""),
            False,
        )

    # ------------------------------------------------------------------
    # ExecutionAdapter interface
    # ------------------------------------------------------------------

    def prepare(self, project_dir: str, source_ref: str) -> str:
        """
        Start an ephemeral Docker container.

        Returns self.WORK_DIR (the top-level work directory inside the container).
        Cloning happens separately via execute().

        Parameters
        ----------
        project_dir:
            Path on the host (unused for Docker; the container is self-contained).
        source_ref:
            The git ref / branch that will be validated (informational only here).
        """
        self._client = self._get_docker_client()

        volumes: dict = {}
        if self.ssh_key_path and os.path.exists(self.ssh_key_path):
            volumes[self.ssh_key_path] = {
                "bind": "/home/worker/.ssh/id_rsa",
                "mode": "ro",
            }

        self._container = self._client.containers.run(
            image=self.image,
            labels={"mergemate.worker": "true"},
            volumes=volumes,
            detach=True,
            remove=False,
            network_mode="bridge",
            user="worker",
            mem_limit=self.mem_limit,
            nano_cpus=self.nano_cpus,
            command="sleep infinity",
        )

        return self.WORK_DIR

    def execute(
        self,
        argv: list[str],
        working_dir: str,
        timeout_s: int = 3600,
        env: Optional[dict] = None,
    ) -> ExecutionResult:
        """
        Run argv inside the container at working_dir.

        Uses container.exec_run(cmd=argv, workdir=working_dir, demux=True).
        Applies a thread-based timeout so long-running commands can be
        detected and reported without leaving zombie threads forever.

        Returns ExecutionResult with exit_code, stdout, stderr, timed_out.
        """
        if self._container is None:
            raise RuntimeError(
                "DockerExecutionAdapter: prepare() must be called before execute()."
            )

        exit_code, stdout_bytes, stderr_bytes, timed_out = self._exec_with_timeout(
            container=self._container,
            argv=argv,
            workdir=working_dir,
            timeout_s=timeout_s,
        )

        stdout_str = (
            stdout_bytes.decode("utf-8", errors="replace")
            if isinstance(stdout_bytes, bytes)
            else (stdout_bytes or "")
        )
        stderr_str = (
            stderr_bytes.decode("utf-8", errors="replace")
            if isinstance(stderr_bytes, bytes)
            else (stderr_bytes or "")
        )

        return ExecutionResult(
            exit_code=exit_code,
            stdout=stdout_str,
            stderr=stderr_str,
            timed_out=timed_out,
        )

    def cleanup(self) -> None:
        """Stop and remove the container. Never raises."""
        if self._container is None:
            return
        try:
            self._container.stop(timeout=5)
        except Exception:  # noqa: BLE001
            pass
        try:
            self._container.remove(force=True)
        except Exception:  # noqa: BLE001
            pass
        self._container = None
