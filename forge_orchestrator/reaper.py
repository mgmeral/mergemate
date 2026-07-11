"""
forge_orchestrator/reaper.py

Orphan reaper: finds and removes containers labelled mergemate.worker=true.

Intended to run at startup (to clean up from a previous crash) and optionally
as a periodic background daemon thread.
"""

from __future__ import annotations

import logging
import threading
import time

import docker as docker_sdk

from forge_orchestrator.worker import WORKER_LABEL

logger = logging.getLogger(__name__)


def reap_orphans(
    docker_client=None,
    dry_run: bool = False,
) -> list[str]:
    """
    Find and remove all containers with label mergemate.worker=true.

    Parameters
    ----------
    docker_client:
        Optional pre-created Docker SDK client. If None, docker.from_env() is used.
    dry_run:
        If True, return the container IDs that *would* be removed without
        actually removing them.

    Returns
    -------
    list[str]
        Container IDs that were removed (or would have been removed in dry_run mode).
    """
    client = docker_client if docker_client is not None else docker_sdk.from_env()

    containers = client.containers.list(
        all=True,
        filters={"label": f"{WORKER_LABEL}=true"},
    )

    removed_ids: list[str] = []
    for container in containers:
        cid = container.id
        if dry_run:
            logger.debug("reap_orphans [dry_run]: would remove container %s", cid[:12])
            removed_ids.append(cid)
        else:
            try:
                container.remove(force=True)
                logger.info("reap_orphans: removed orphan container %s", cid[:12])
                removed_ids.append(cid)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "reap_orphans: failed to remove container %s: %s", cid[:12], exc
                )

    return removed_ids


def start_reaper_thread(
    interval_s: int = 300,
    docker_client=None,
) -> threading.Thread:
    """
    Start a daemon thread that calls reap_orphans() every interval_s seconds.

    Parameters
    ----------
    interval_s:
        How often (in seconds) to run the reaper. Default: 300 (5 minutes).
    docker_client:
        Optional pre-created Docker SDK client passed through to reap_orphans().

    Returns
    -------
    threading.Thread
        The already-started daemon thread.
    """

    def _loop() -> None:
        while True:
            try:
                reap_orphans(docker_client=docker_client)
            except Exception as exc:  # noqa: BLE001
                logger.warning("reaper thread: reap_orphans raised: %s", exc)
            time.sleep(interval_s)

    thread = threading.Thread(target=_loop, daemon=True, name="mergemate-reaper")
    thread.start()
    return thread
