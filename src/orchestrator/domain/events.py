from datetime import datetime, timezone
from enum import StrEnum

from pydantic import BaseModel, Field


class EventType(StrEnum):
    JOB_CREATED = "job_created"
    ANALYSIS_STARTED = "analysis_started"
    ANALYSIS_COMPLETED = "analysis_completed"
    MANAGER_SELECTED = "manager_selected"
    PLAN_CREATED = "plan_created"
    PLAN_VALIDATION_FAILED = "plan_validation_failed"
    TASK_ASSIGNED = "task_assigned"
    WORKER_STARTED = "worker_started"
    WORKER_COMPLETED = "worker_completed"
    WORKER_FAILED = "worker_failed"
    TASK_ACCEPTED = "task_accepted"
    TASK_REJECTED = "task_rejected"
    TASK_REASSIGNED = "task_reassigned"
    VERIFICATION_STARTED = "verification_started"
    VERIFICATION_FAILED = "verification_failed"
    VERIFICATION_PASSED = "verification_passed"
    INTEGRATION_STARTED = "integration_started"
    INTEGRATION_COMPLETED = "integration_completed"
    JOB_COMPLETED = "job_completed"
    JOB_FAILED = "job_failed"
    HUMAN_INPUT_REQUIRED = "human_input_required"
    APPROVAL_REQUIRED = "approval_required"


class OrchestratorEvent(BaseModel):
    type: EventType
    job_id: str
    task_id: str | None = None
    worker_id: str | None = None
    payload: dict[str, object] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
