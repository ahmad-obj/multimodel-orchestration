import json
from collections.abc import Awaitable, Callable

from pydantic import BaseModel

from orchestrator.domain.common import CostClass
from orchestrator.domain.tasks import TaskAnalysis
from orchestrator.domain.workers import WorkerRequest
from orchestrator.execution.structured import execute_structured
from orchestrator.selection.manager import RankedManager


class RouterDecision(BaseModel):
    worker_id: str
    reason: str


class InvalidRouterDecision(ValueError):
    pass


class ManagerRouter:
    def __init__(self, registry, executor: Callable[..., Awaitable] = execute_structured) -> None:
        self.registry = registry
        self.executor = executor

    def _router_worker(self):
        order = {CostClass.FREE: 0, CostClass.INCLUDED: 1}
        candidates = [
            w
            for w in self.registry.available()
            if w.profile.cost_class in order
            and not w.profile.is_paid
            and w.profile.capabilities.get("reasoning", 0) >= 0.60
            and w.profile.capabilities.get("simple_tasks", 0) >= 0.60
        ]
        if not candidates:
            return None
        return min(
            candidates,
            key=lambda w: (order[w.profile.cost_class], -w.profile.speed, -w.profile.reliability),
        )

    async def break_tie(
        self, analysis: TaskAnalysis, candidates: list[RankedManager]
    ) -> RouterDecision:
        allowed = {candidate.worker.profile.id for candidate in candidates}
        router_worker = self._router_worker()
        if router_worker is None:
            return RouterDecision(
                worker_id=candidates[0].worker.profile.id,
                reason="no free router; deterministic top candidate",
            )
        compact = [
            {
                "worker_id": c.worker.profile.id,
                "score": c.score,
                "capabilities": c.worker.profile.capabilities,
                "reliability": c.worker.profile.reliability,
                "speed": c.worker.profile.speed,
                "cost_class": c.worker.profile.cost_class.value,
            }
            for c in candidates
        ]
        request = WorkerRequest(
            job_id="manager-router",
            task_id="router",
            objective=(
                "Choose the best manager from ONLY the listed candidates. "
                "Return worker_id and reason.\n"
                f"Task analysis: {json.dumps(analysis.model_dump(mode='json'), sort_keys=True)}\n"
                f"Candidates: {json.dumps(compact, sort_keys=True)}"
            ),
            repo_path=__import__("pathlib").Path.cwd(),
            workspace_path=None,
            read_only=True,
            timeout_seconds=120,
        )
        adapter = self.registry.adapters[router_worker.profile.harness]
        _, decision = await self.executor(adapter, router_worker, request, RouterDecision)
        if decision.worker_id not in allowed:
            raise InvalidRouterDecision(f"router chose non-candidate {decision.worker_id}")
        return decision
