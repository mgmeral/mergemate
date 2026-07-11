"""
forge_api/repository.py

Repository interface and SQLite implementation for persisting ValidationRun records.
"""

from __future__ import annotations

import json
import sqlite3
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Optional

from forge_orchestrator.orchestrator import ValidationRequest, ValidationRun


# ---------------------------------------------------------------------------
# Abstract repository interface
# ---------------------------------------------------------------------------

class ValidationRunRepository(ABC):
    @abstractmethod
    def save(self, run: ValidationRun) -> None:
        """Insert or update a run record."""
        ...

    @abstractmethod
    def get(self, run_id: str) -> Optional[ValidationRun]:
        """Return a ValidationRun by run_id, or None if not found."""
        ...

    @abstractmethod
    def list_recent(self, limit: int = 50) -> list[ValidationRun]:
        """Return recent runs ordered by started_at descending."""
        ...


# ---------------------------------------------------------------------------
# SQLite implementation
# ---------------------------------------------------------------------------

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS validation_runs (
    run_id TEXT PRIMARY KEY,
    repo_url TEXT NOT NULL,
    feature_branch TEXT NOT NULL,
    target_branch TEXT NOT NULL,
    validation_profile TEXT NOT NULL DEFAULT 'default',
    active_maven_profiles TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    has_conflicts INTEGER,
    changed_files TEXT NOT NULL,
    conflict_files TEXT NOT NULL,
    maven_command TEXT,
    lifecycle_log TEXT NOT NULL,
    error_message TEXT,
    execution_plan TEXT
);
"""


def _parse_datetime(value: Optional[str]) -> Optional[datetime]:
    """Parse an ISO 8601 string back to a timezone-aware datetime."""
    if value is None:
        return None
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _serialize_datetime(dt: Optional[datetime]) -> Optional[str]:
    """Serialize a datetime to an ISO 8601 string."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _row_to_run(row: sqlite3.Row) -> ValidationRun:
    """Convert a database row to a ValidationRun object."""
    request = ValidationRequest(
        repo_url=row["repo_url"],
        feature_branch=row["feature_branch"],
        target_branch=row["target_branch"],
        validation_profile=row["validation_profile"] if row["validation_profile"] else "default",
        active_maven_profiles=json.loads(row["active_maven_profiles"]) if row["active_maven_profiles"] else [],
    )
    run = ValidationRun(
        run_id=row["run_id"],
        request=request,
        status=row["status"],
        started_at=_parse_datetime(row["started_at"]),
        finished_at=_parse_datetime(row["finished_at"]),
        has_conflicts=bool(row["has_conflicts"]) if row["has_conflicts"] is not None else None,
        changed_files=json.loads(row["changed_files"]),
        conflict_files=json.loads(row["conflict_files"]),
        maven_command=row["maven_command"],
        lifecycle_log=json.loads(row["lifecycle_log"]),
        error_message=row["error_message"],
    )
    # Store execution_plan as an extra attribute if present
    execution_plan_raw = row["execution_plan"]
    run._execution_plan = json.loads(execution_plan_raw) if execution_plan_raw else None  # type: ignore[attr-defined]
    return run


class SQLiteRunRepository(ValidationRunRepository):
    """SQLite-backed repository for ValidationRun objects."""

    def __init__(self, db_path: str = "mergemate.db") -> None:
        """Initialize the database and create tables if they don't exist."""
        self._db_path = db_path
        # For in-memory databases, we must keep a single persistent connection
        # because each new sqlite3.connect(":memory:") creates an isolated empty DB.
        if db_path == ":memory:":
            self._conn: Optional[sqlite3.Connection] = sqlite3.connect(
                ":memory:", check_same_thread=False
            )
            self._conn.row_factory = sqlite3.Row
        else:
            self._conn = None
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        """Return a connection. For in-memory DBs, reuse the persistent connection."""
        if self._conn is not None:
            return self._conn
        conn = sqlite3.connect(self._db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        conn = self._connect()
        conn.execute(_CREATE_TABLE_SQL)
        conn.commit()

    def save(self, run: ValidationRun, execution_plan: Optional[dict] = None) -> None:
        """Insert or update a run record."""
        # Check for execution_plan stored as private attribute
        ep = execution_plan
        if ep is None and hasattr(run, "_execution_plan"):
            ep = run._execution_plan  # type: ignore[attr-defined]

        sql = """
        INSERT OR REPLACE INTO validation_runs (
            run_id, repo_url, feature_branch, target_branch,
            validation_profile, active_maven_profiles,
            status, started_at, finished_at,
            has_conflicts, changed_files, conflict_files,
            maven_command, lifecycle_log, error_message, execution_plan
        ) VALUES (
            :run_id, :repo_url, :feature_branch, :target_branch,
            :validation_profile, :active_maven_profiles,
            :status, :started_at, :finished_at,
            :has_conflicts, :changed_files, :conflict_files,
            :maven_command, :lifecycle_log, :error_message, :execution_plan
        )
        """
        params = {
            "run_id": run.run_id,
            "repo_url": run.request.repo_url,
            "feature_branch": run.request.feature_branch,
            "target_branch": run.request.target_branch,
            "validation_profile": run.request.validation_profile,
            "active_maven_profiles": json.dumps(run.request.active_maven_profiles),
            "status": run.status,
            "started_at": _serialize_datetime(run.started_at),
            "finished_at": _serialize_datetime(run.finished_at),
            "has_conflicts": (
                int(run.has_conflicts) if run.has_conflicts is not None else None
            ),
            "changed_files": json.dumps(run.changed_files),
            "conflict_files": json.dumps(run.conflict_files),
            "maven_command": run.maven_command,
            "lifecycle_log": json.dumps(run.lifecycle_log),
            "error_message": run.error_message,
            "execution_plan": json.dumps(ep) if ep is not None else None,
        }

        conn = self._connect()
        conn.execute(sql, params)
        conn.commit()

    def get(self, run_id: str) -> Optional[ValidationRun]:
        """Return a ValidationRun by run_id, or None if not found."""
        sql = "SELECT * FROM validation_runs WHERE run_id = ?"
        conn = self._connect()
        cursor = conn.execute(sql, (run_id,))
        row = cursor.fetchone()
        if row is None:
            return None
        return _row_to_run(row)

    def list_recent(self, limit: int = 50) -> list[ValidationRun]:
        """Return recent runs ordered by started_at descending."""
        sql = "SELECT * FROM validation_runs ORDER BY started_at DESC LIMIT ?"
        conn = self._connect()
        cursor = conn.execute(sql, (limit,))
        rows = cursor.fetchall()
        return [_row_to_run(row) for row in rows]
