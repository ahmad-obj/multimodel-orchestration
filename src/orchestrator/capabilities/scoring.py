from pydantic import BaseModel

from orchestrator.domain.common import CostClass
from orchestrator.domain.tasks import TaskAnalysis
from orchestrator.domain.workers import WorkerProfile


class SuitabilityScore(BaseModel):
    worker_id: str
    total: float
    capability_match: float
    reliability: float
    history: float
    speed: float
    cost_component: float
    adequate: bool


class WorkerScorer:
    COST = {CostClass.FREE: 1.0, CostClass.INCLUDED: 0.85, CostClass.CHEAP: 0.55, CostClass.PAID: 0.0}

    def score(self, profile: WorkerProfile, analysis: TaskAnalysis, history_score: float | None = None) -> SuitabilityScore:
        total_weight = sum(analysis.capability_weights.values())
        capability = sum(
            profile.capabilities.get(name, 0.0) * weight
            for name, weight in analysis.capability_weights.items()
        ) / total_weight
        adequate = all(
            weight < 0.75 or profile.capabilities.get(name, 0.0) >= 0.55
            for name, weight in analysis.capability_weights.items()
        )
        history = profile.reliability if history_score is None else history_score
        cost = self.COST[profile.cost_class]
        total = (
            0.55 * capability
            + 0.15 * profile.reliability
            + 0.10 * history
            + 0.10 * profile.speed
            + 0.10 * cost
        )
        return SuitabilityScore(
            worker_id=profile.id,
            total=round(total, 6),
            capability_match=capability,
            reliability=profile.reliability,
            history=history,
            speed=profile.speed,
            cost_component=cost,
            adequate=adequate,
        )
