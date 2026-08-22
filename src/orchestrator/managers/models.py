from enum import StrEnum

from pydantic import BaseModel, Field, model_validator

from orchestrator.domain.tasks import SubtaskSpec
from orchestrator.verification.models import VerificationCheck


class ManagerAction(StrEnum):
    ACCEPT = "accept"
    REJECT = "reject"
    REASSIGN = "reassign"
    ADD_SUBTASKS = "add_subtasks"
    CANCEL_SUBTASKS = "cancel_subtasks"
    REQUEST_VERIFICATION = "request_verification"


class ManagerDecision(BaseModel):
    action: ManagerAction
    task_ids: list[str] = Field(default_factory=list)
    reason: str = Field(min_length=1)
    new_subtasks: list[SubtaskSpec] = Field(default_factory=list)
    requested_worker_id: str | None = None
    requested_checks: list[VerificationCheck] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_action_payload(self) -> "ManagerDecision":
        if self.action is ManagerAction.REASSIGN and not self.requested_worker_id:
            raise ValueError("reassign requires requested_worker_id")
        if self.action is ManagerAction.ADD_SUBTASKS and not self.new_subtasks:
            raise ValueError("add_subtasks requires new_subtasks")
        if self.action is ManagerAction.REQUEST_VERIFICATION and not self.requested_checks:
            raise ValueError("request_verification requires requested_checks")
        return self
