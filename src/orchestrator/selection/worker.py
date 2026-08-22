from pydantic import BaseModel

from orchestrator.capabilities.scoring import SuitabilityScore, WorkerScorer
from orchestrator.domain.tasks import TaskAnalysis
from orchestrator.domain.workers import WorkerDescriptor
from orchestrator.policies.cost import CostPolicy
from orchestrator.selection.filters import RejectedWorker, eligible_workers


class WorkerSelection(BaseModel):
    worker: WorkerDescriptor
    scores: list[SuitabilityScore]
    rejected: list[RejectedWorker]


class WorkerSelector:
    def __init__(
        self, scorer: WorkerScorer | None = None, cost_policy: CostPolicy | None = None
    ) -> None:
        self.scorer = scorer or WorkerScorer()
        self.cost_policy = cost_policy or CostPolicy()

    def select(
        self, analysis: TaskAnalysis, workers: list[WorkerDescriptor], *, requires_write: bool
    ) -> WorkerSelection:
        filtered = eligible_workers(
            workers,
            analysis,
            self.cost_policy,
            for_manager=False,
            requires_write=requires_write,
        )
        scores = [self.scorer.score(w.profile, analysis) for w in filtered.eligible]
        scores = [s for s in scores if s.adequate]
        if not scores:
            raise RuntimeError("no eligible adequate worker")
        scores.sort(key=lambda s: s.total, reverse=True)
        chosen_id = scores[0].worker_id
        chosen = next(w for w in filtered.eligible if w.profile.id == chosen_id)
        return WorkerSelection(worker=chosen, scores=scores, rejected=filtered.rejected)
