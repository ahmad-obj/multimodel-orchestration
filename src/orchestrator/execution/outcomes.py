from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel

from orchestrator.domain.common import ExecutionStatus
from orchestrator.domain.events import EventType, OrchestratorEvent
from orchestrator.domain.jobs import JobStatus, TaskStatus
from orchestrator.domain.results import WorkerResult
from orchestrator.domain.tasks import TaskRisk
from orchestrator.policies.approval import ApprovalRequest
from orchestrator.policies.escalation import EscalationActionType, EscalationPolicy
from orchestrator.verification.checks import infer_repository_checks
from orchestrator.verification.models import VerificationCheck, VerificationResult


class OutcomeDisposition(StrEnum):
    ACCEPTED = "accepted"
    RETRY = "retry"
    REASSIGNED = "reassigned"
    WAITING_FOR_APPROVAL = "waiting_for_approval"
    FAILED = "failed"


class TaskOutcome(BaseModel):
    disposition: OutcomeDisposition
    failure_class: str | None = None
    next_worker_id: str | None = None
    approval: ApprovalRequest | None = None
    verification: VerificationResult | None = None


def default_task_checks(subtask, workspace: Path) -> list[VerificationCheck]:
    checks: list[VerificationCheck] = []
    if not subtask.read_only:
        checks.append(VerificationCheck(kind="changed_files"))
    checks.extend(infer_repository_checks(workspace, final=False))
    if not subtask.read_only or subtask.risk in {TaskRisk.MEDIUM, TaskRisk.HIGH}:
        checks.append(VerificationCheck(kind="manager_review"))
    if subtask.risk is TaskRisk.HIGH:
        checks.append(VerificationCheck(kind="independent_review"))
    return checks


class TaskOutcomeProcessor:
    def __init__(
        self,
        *,
        registry,
        verification_service,
        failure_classifier,
        escalation_policy: EscalationPolicy | None = None,
        attempt_repository=None,
        task_repository=None,
        job_repository=None,
        decision_repository=None,
        performance_repository=None,
        event_bus=None,
        check_factory=default_task_checks,
    ) -> None:
        self.registry = registry
        self.verification_service = verification_service
        self.failure_classifier = failure_classifier
        self.escalation_policy = escalation_policy or EscalationPolicy()
        self.attempt_repository = attempt_repository
        self.task_repository = task_repository
        self.job_repository = job_repository
        self.decision_repository = decision_repository
        self.performance_repository = performance_repository
        self.event_bus = event_bus
        self.check_factory = check_factory

    async def _publish(self, event: OrchestratorEvent) -> None:
        if self.event_bus is not None:
            await self.event_bus.publish(event)

    async def _attempted_workers(self, job_id: str, task_id: str, current: str) -> list[str]:
        attempted: list[str] = []
        if self.attempt_repository is not None:
            attempts = await self.attempt_repository.list_for_job(job_id)
            attempted = [item.worker_id for item in attempts if item.task_id == task_id]
        if current not in attempted:
            attempted.append(current)
        return attempted

    async def _set_task(
        self,
        job_id: str,
        task_id: str,
        *,
        status: TaskStatus,
        worker_id: str | None = None,
    ) -> None:
        if self.task_repository is None:
            return
        if worker_id is not None:
            await self.task_repository.set_assignment(job_id, task_id, worker_id)
        await self.task_repository.set_status(job_id, task_id, status)

    async def process(self, assignment, result: WorkerResult, workspace: Path) -> TaskOutcome:
        verification: VerificationResult | None = None
        if self.performance_repository is not None:
            await self.performance_repository.record_outcome(result)

        if result.status is ExecutionStatus.SUCCEEDED:
            checks = self.check_factory(assignment.subtask, workspace)
            verification = await self.verification_service.verify(
                assignment.job_id,
                assignment.subtask,
                result,
                workspace,
                checks,
            )
            if verification.passed:
                await self._set_task(
                    assignment.job_id,
                    assignment.subtask.id,
                    status=TaskStatus.COMPLETED,
                )
                await self._publish(
                    OrchestratorEvent(
                        type=EventType.TASK_ACCEPTED,
                        job_id=assignment.job_id,
                        task_id=assignment.subtask.id,
                        worker_id=result.worker_id,
                        payload={
                            "confidence": result.confidence,
                            "execution_id": result.execution_id,
                        },
                    )
                )
                return TaskOutcome(
                    disposition=OutcomeDisposition.ACCEPTED,
                    verification=verification,
                )
            failure = self.failure_classifier.classify(
                result=result,
                verification=verification,
            )
        else:
            failure = self.failure_classifier.classify(result=result)

        await self._publish(
            OrchestratorEvent(
                type=EventType.TASK_REJECTED,
                job_id=assignment.job_id,
                task_id=assignment.subtask.id,
                worker_id=result.worker_id,
                payload={
                    "failure_class": failure.value,
                    "execution_id": result.execution_id,
                },
            )
        )
        attempted = await self._attempted_workers(
            assignment.job_id,
            assignment.subtask.id,
            result.worker_id,
        )
        action = self.escalation_policy.decide(
            failure,
            attempted,
            assignment.subtask,
            len(attempted),
            self.registry,
            current_worker_id=result.worker_id,
        )

        if action.type is EscalationActionType.RETRY_SAME:
            await self._set_task(
                assignment.job_id,
                assignment.subtask.id,
                status=TaskStatus.PENDING,
                worker_id=result.worker_id,
            )
            return TaskOutcome(
                disposition=OutcomeDisposition.RETRY,
                failure_class=failure.value,
                next_worker_id=result.worker_id,
                verification=verification,
            )

        if action.type in {EscalationActionType.REASSIGN, EscalationActionType.ESCALATE}:
            target = action.worker_id
            if target is None:
                raise RuntimeError(f"{action.type.value} requires a target worker")
            await self._set_task(
                assignment.job_id,
                assignment.subtask.id,
                status=TaskStatus.PENDING,
                worker_id=target,
            )
            await self._publish(
                OrchestratorEvent(
                    type=EventType.TASK_REASSIGNED,
                    job_id=assignment.job_id,
                    task_id=assignment.subtask.id,
                    worker_id=target,
                    payload={
                        "previous_worker_id": result.worker_id,
                        "reason": action.reason,
                    },
                )
            )
            return TaskOutcome(
                disposition=OutcomeDisposition.REASSIGNED,
                failure_class=failure.value,
                next_worker_id=target,
                verification=verification,
            )

        if action.type is EscalationActionType.REQUIRES_USER_APPROVAL:
            approval = ApprovalRequest(
                id=f"approval-{uuid4().hex[:12]}",
                job_id=assignment.job_id,
                task_id=assignment.subtask.id,
                reason=action.reason,
                candidate_worker_ids=action.candidate_worker_ids,
            )
            await self._set_task(
                assignment.job_id,
                assignment.subtask.id,
                status=TaskStatus.PENDING,
            )
            if self.job_repository is not None:
                await self.job_repository.set_status(
                    assignment.job_id,
                    JobStatus.WAITING_FOR_APPROVAL,
                )
            if self.decision_repository is not None:
                await self.decision_repository.append(
                    assignment.job_id,
                    assignment.subtask.id,
                    "paid_escalation_approval_request",
                    approval.model_dump(mode="json"),
                )
            await self._publish(
                OrchestratorEvent(
                    type=EventType.APPROVAL_REQUIRED,
                    job_id=assignment.job_id,
                    task_id=assignment.subtask.id,
                    worker_id=result.worker_id,
                    payload=approval.model_dump(mode="json"),
                )
            )
            return TaskOutcome(
                disposition=OutcomeDisposition.WAITING_FOR_APPROVAL,
                failure_class=failure.value,
                approval=approval,
                verification=verification,
            )

        await self._set_task(
            assignment.job_id,
            assignment.subtask.id,
            status=TaskStatus.FAILED,
        )
        if self.decision_repository is not None:
            await self.decision_repository.append(
                assignment.job_id,
                assignment.subtask.id,
                "terminal_task_failure",
                {
                    "failure_class": failure.value,
                    "escalation_action": action.type.value,
                    "reason": action.reason,
                },
            )
        return TaskOutcome(
            disposition=OutcomeDisposition.FAILED,
            failure_class=failure.value,
            verification=verification,
        )
