"""
forge_orchestrator/worker.py

Ephemeral Docker worker: create, exec, stream logs, destroy.

Uses the Docker Python SDK (docker.from_env()).
Every container gets the label mergemate.worker=true for reaper identification.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Iterator

import docker

logger = logging.getLogger(__name__)

# Label key applied to all containers we create.
WORKER_LABEL = "mergemate.worker"


@dataclass
class WorkerConfig:
    image: str            # e.g. "mergemate-worker:latest"
    remote_url: str       # git remote URL
    ssh_key_path: str     # host path to SSH key (mounted read-only)
    work_dir: str = "/workspace"  # dir inside container


class Worker:
    """
    Manages the lifecycle of a single ephemeral Docker container.

    Use as a context manager to guarantee teardown even on exception.
    """

    def __init__(self, config: WorkerConfig) -> None:
        self._config = config
        self._client = docker.from_env()
        self._container = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> str:
        """
        Create and start an ephemeral container.

        Returns the container ID.
        """
        cfg = self._config
        self._container = self._client.containers.run(
            image=cfg.image,
            labels={WORKER_LABEL: "true"},
            volumes={
                cfg.ssh_key_path: {
                    "bind": "/home/worker/.ssh/id_rsa",
                    "mode": "ro",
                }
            },
            detach=True,
            remove=False,
            network_mode="bridge",
            user="worker",
            mem_limit="2g",
            nano_cpus=2_000_000_000,
            # Keep the container alive so we can exec into it
            command="sleep infinity",
        )
        return self._container.id

    def exec(self, argv: list[str], timeout_s: int = 300) -> tuple[int, str, str]:
        """
        Execute argv inside the running container.

        argv is passed directly (no shell invocation).
        Returns (exit_code, stdout, stderr).
        """
        if self._container is None:
            raise RuntimeError("Worker has not been started. Call start() first.")

        result = self._container.exec_run(
            cmd=argv,
            demux=True,
        )
        exit_code = result.exit_code
        raw_out, raw_err = result.output if result.output else (None, None)

        stdout = raw_out.decode("utf-8", errors="replace") if raw_out else ""
        stderr = raw_err.decode("utf-8", errors="replace") if raw_err else ""

        return exit_code, stdout, stderr

    def stream_logs(self) -> Iterator[str]:
        """Stream container logs line by line."""
        if self._container is None:
            raise RuntimeError("Worker has not been started. Call start() first.")

        for line in self._container.logs(stream=True, follow=True):
            if isinstance(line, bytes):
                yield line.decode("utf-8", errors="replace").rstrip("\n")
            else:
                yield str(line).rstrip("\n")

    def stop(self) -> None:
        """
        Stop and remove the container.

        Best-effort: never raises. Errors are logged silently.
        """
        if self._container is None:
            return
        try:
            self._container.stop(timeout=5)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Worker.stop: container.stop() failed (ignored): %s", exc)
        try:
            self._container.remove(force=True)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Worker.stop: container.remove() failed (ignored): %s", exc)

    # ------------------------------------------------------------------
    # Context manager — guaranteed teardown
    # ------------------------------------------------------------------

    def __enter__(self) -> "Worker":
        self.start()
        return self

    def __exit__(self, *_) -> None:
        """Always calls stop() — guaranteed teardown regardless of exceptions."""
        self.stop()
