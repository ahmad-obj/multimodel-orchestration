from pydantic import BaseModel, Field

from orchestrator.domain.common import WorkerStatus
from orchestrator.domain.tasks import TaskAnalysis
from orchestrator.domain.workers import WorkerDescriptor
from orchestrator.policies.cost import CostPolicy


class RejectedWorker(BaseModel):
    worker_id: str
    reasons: list[str]


class EligibilityResult(BaseModel):
    eligible: list[WorkerDescriptor] = Field(default_factory=list)
    rejected: list[RejectedWorker] = Field(default_factory=list)


def eligible_workers(
    workers: list[WorkerDescriptor],
    analysis: TaskAnalysis,
    cost_policy: CostPolicy,
    *,
    for_manager: bool = False,
    requires_write: bool = False,
) -> EligibilityResult:
    result = EligibilityResult()
    for worker in workers:
        p = worker.profile
        reasons: list[str] = []
        if worker.status is not WorkerStatus.AVAILABLE:
            reasons.append("unavailable")
        if not cost_policy.permits(p):
            reasons.append("paid worker forbidden")
        missing_tools = sorted(analysis.required_tools - p.tools)
        if missing_tools:
            reasons.append("missing tools: " + ", ".join(missing_tools))
        if for_manager and not p.can_manage:
            reasons.append("not manager eligible")
        if requires_write and not p.can_modify_repo:
            reasons.append("cannot modify repository")
        if analysis.required_context_tokens and p.context_tokens and p.context_tokens < analysis.required_context_tokens:
            reasons.append("insufficient context capacity")
        if reasons:
            result.rejected.append(RejectedWorker(worker_id=p.id, reasons=reasons))
        else:
            result.eligible.append(worker)
    return result
