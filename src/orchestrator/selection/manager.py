from pydantic import BaseModel, Field

from orchestrator.capabilities.scoring import WorkerScorer
from orchestrator.domain.tasks import TaskAnalysis
from orchestrator.domain.workers import WorkerDescriptor
from orchestrator.policies.cost import CostPolicy
from orchestrator.selection.filters import RejectedWorker, eligible_workers


class RankedManager(BaseModel):
    worker: WorkerDescriptor
    score: float
    reason: str


class ManagerSelection(BaseModel):
    ranked: list[RankedManager] = Field(default_factory=list)
    rejected: list[RejectedWorker] = Field(default_factory=list)
    needs_tiebreak: bool = False


class ManagerSelector:
    CLEAR_WINNER_GAP = 0.08

    def __init__(self, scorer: WorkerScorer | None = None, cost_policy: CostPolicy | None = None) -> None:
        self.scorer = scorer or WorkerScorer()
        self.cost_policy = cost_policy or CostPolicy()

    def rank(self, analysis: TaskAnalysis, workers: list[WorkerDescriptor]) -> ManagerSelection:
        filtered = eligible_workers(workers, analysis, self.cost_policy, for_manager=True, requires_write=False)
        ranked: list[RankedManager] = []
        for worker in filtered.eligible:
            score = self.scorer.score(worker.profile, analysis)
            if not score.adequate:
                continue
            reliability_bonus = min(worker.profile.reliability * 1.10, 1.0) - worker.profile.reliability
            total = min(1.0, score.total + 0.15 * reliability_bonus)
            ranked.append(
                RankedManager(
                    worker=worker,
                    score=round(total, 6),
                    reason=(
                        f"capability={score.capability_match:.3f}, reliability={worker.profile.reliability:.3f}, "
                        f"speed={worker.profile.speed:.3f}, cost={worker.profile.cost_class.value}"
                    ),
                )
            )
        ranked.sort(key=lambda item: item.score, reverse=True)
        needs_tiebreak = len(ranked) >= 2 and ranked[0].score - ranked[1].score < self.CLEAR_WINNER_GAP
        return ManagerSelection(ranked=ranked[:3], rejected=filtered.rejected, needs_tiebreak=needs_tiebreak)
