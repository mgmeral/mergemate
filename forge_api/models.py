"""
forge_api/models.py

Pydantic request/response models for the MergeMate API.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class StartValidationRequest(BaseModel):
    repo_url: str
    feature_branch: str
    target_branch: str
    validation_profile: str = "default"
    active_maven_profiles: list[str] = []


class ValidationRunResponse(BaseModel):
    run_id: str
    status: str  # pending | running | success | failure | error
    started_at: datetime
    finished_at: Optional[datetime]
    has_conflicts: Optional[bool]
    changed_files: list[str]
    conflict_files: list[str]
    maven_command: Optional[str]
    lifecycle_log: list[str]
    error_message: Optional[str]
    # Embedded execution plan (may be None if not yet computed or conflicts)
    execution_plan: Optional[dict]
    # Failure analysis (re-computed on the fly, not persisted)
    failure_analysis: Optional[dict] = None


class ValidationListResponse(BaseModel):
    runs: list[ValidationRunResponse]
    total: int
