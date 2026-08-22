from enum import StrEnum

from pydantic import BaseModel, Field


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class ApprovalRequest(BaseModel):
    id: str
    job_id: str
    task_id: str
    reason: str
    candidate_worker_ids: list[str] = Field(min_length=1)
    estimated_cost_note: str | None = None
    status: ApprovalStatus = ApprovalStatus.PENDING
