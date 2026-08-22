from enum import StrEnum

from pydantic import BaseModel, Field

from orchestrator.capabilities.scoring import WorkerScorer
from orchestrator.domain.common import CostClass
from orchestrator.domain.tasks import SubtaskSpec, TaskAnalysis, TaskComplexity
from orchestrator.execution.failures import FailureClass
from orchestrator.policies.cost import CostPolicy


class EscalationActionType(StrEnum):
    RETRY_SAME = "retry_same"
    REASSIGN = "reassign"
    ESCALATE = "escalate"
    REQUIRES_USER_APPROVAL = "requires_user_approval"
    STOP = "stop"
    CREATE_CONFLICT_TASK = "create_conflict_task"
    MANAGER_REVIEW = "manager_review"


class EscalationAction(BaseModel):
    type: EscalationActionType
    worker_id: str | None = None
    candidate_worker_ids: list[str] = Field(default_factory=list)
    reason: str


class EscalationPolicy:
    MAX_ATTEMPTS = 4
    COST_RANK = {
        CostClass.FREE: 0,
        CostClass.INCLUDED: 1,
        CostClass.CHEAP: 2,
        CostClass.PAID: 3,
    }

    def __init__(
        self,
        *,
        scorer: WorkerScorer | None = None,
        cost_policy: CostPolicy | None = None,
    ) -> None:
        self.scorer = scorer or WorkerScorer()
        self.cost_policy = cost_policy or CostPolicy()

    def _analysis(self, task: SubtaskSpec) -> TaskAnalysis:
        return TaskAnalysis(
            task_type="subtask",
            complexity=TaskComplexity.MEDIUM,
            risk=task.risk,
            confidence=1.0,
            capability_weights=task.capability_weights,
            required_tools=task.required_tools,
            context_requirements=task.context_requirements,
            constraints=[],
            expected_outputs=task.expected_outputs,
            parallelizable_hint=False,
        )

    def _ranked_candidates(self, task: SubtaskSpec, registry, attempted: set[str]):
        analysis = self._analysis(task)
        candidates = []
        for descriptor in registry.available():
            profile = descriptor.profile
            if profile.id in attempted:
                continue
            if not task.read_only and not profile.can_modify_repo:
                continue
            if not task.required_tools <= profile.tools:
                continue
            score = self.scorer.score(profile, analysis)
            if score.adequate:
                candidates.append((descriptor, score))
        candidates.sort(key=lambda item: item[1].total, reverse=True)
        return candidates

    def decide(
        self,
        failure: FailureClass,
        attempted_worker_ids: list[str],
        task: SubtaskSpec,
        attempt_count: int,
        registry,
        *,
        current_worker_id: str,
    ) -> EscalationAction:
        if attempt_count >= self.MAX_ATTEMPTS:
            return EscalationAction(
                type=EscalationActionType.STOP,
                reason="maximum attempts reached",
            )
        if failure is FailureClass.POLICY_PERMISSION:
            return EscalationAction(
                type=EscalationActionType.STOP,
                reason="policy cannot be bypassed",
            )
        if failure is FailureClass.INTEGRATION_CONFLICT:
            return EscalationAction(
                type=EscalationActionType.CREATE_CONFLICT_TASK,
                reason="integration conflict requires explicit resolution task",
            )
        if failure is FailureClass.UNKNOWN:
            return EscalationAction(
                type=EscalationActionType.MANAGER_REVIEW,
                reason="unknown failure requires manager review",
            )

        current_attempts = attempted_worker_ids.count(current_worker_id)
        retryable = {
            FailureClass.ENVIRONMENTAL,
            FailureClass.TIMEOUT,
            FailureClass.INVALID_STRUCTURED_RESPONSE,
        }
        if failure in retryable and current_attempts <= 1:
            return EscalationAction(
                type=EscalationActionType.RETRY_SAME,
                worker_id=current_worker_id,
                reason=f"one bounded retry for {failure.value}",
            )

        attempted = set(attempted_worker_ids)
        candidates = self._ranked_candidates(task, registry, attempted)
        nonpaid = [item for item in candidates if self.cost_policy.permits(item[0].profile)]
        current = registry.get(current_worker_id).profile

        if nonpaid:
            current_rank = self.COST_RANK[current.cost_class]
            same_tier = [
                item
                for item in nonpaid
                if self.COST_RANK[item[0].profile.cost_class] == current_rank
            ]
            chosen = same_tier[0] if same_tier else nonpaid[0]
            action_type = (
                EscalationActionType.REASSIGN
                if chosen[0].profile.cost_class == current.cost_class
                else EscalationActionType.ESCALATE
            )
            return EscalationAction(
                type=action_type,
                worker_id=chosen[0].profile.id,
                reason=f"reassign after {failure.value}",
            )

        paid = [item[0].profile.id for item in candidates if item[0].profile.is_paid]
        if paid and not self.cost_policy.allow_paid:
            return EscalationAction(
                type=EscalationActionType.REQUIRES_USER_APPROVAL,
                candidate_worker_ids=paid,
                reason="only paid eligible workers remain",
            )
        return EscalationAction(
            type=EscalationActionType.STOP,
            reason="no eligible worker remains",
        )
