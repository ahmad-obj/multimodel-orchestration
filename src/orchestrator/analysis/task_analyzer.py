import json
from collections.abc import Awaitable, Callable

from orchestrator.analysis.errors import NoEligibleWorkerError
from orchestrator.analysis.repository import RepositorySummary
from orchestrator.capabilities.profiles import BASE_CAPABILITY_DIMENSIONS
from orchestrator.domain.common import CostClass
from orchestrator.domain.tasks import TaskAnalysis
from orchestrator.domain.workers import WorkerRequest
from orchestrator.execution.structured import execute_structured


class TaskAnalyzer:
    def __init__(self, registry, executor: Callable[..., Awaitable] = execute_structured) -> None:
        self.registry = registry
        self.executor = executor

    def _select_worker(self):
        order = {CostClass.FREE: 0, CostClass.INCLUDED: 1}
        candidates = [
            w
            for w in self.registry.available()
            if not w.profile.is_paid
            and w.profile.cost_class in order
            and w.profile.capabilities.get("reasoning", 0) >= 0.60
            and w.profile.capabilities.get("simple_tasks", 0) >= 0.60
        ]
        if not candidates:
            raise NoEligibleWorkerError("no free/included task analyzer is available")
        candidates.sort(
            key=lambda w: (order[w.profile.cost_class], -w.profile.speed, -w.profile.reliability)
        )
        return candidates[0]

    async def analyze(
        self, user_request: str, repository_summary: RepositorySummary
    ) -> TaskAnalysis:
        worker = self._select_worker()
        adapter = self.registry.adapters[worker.profile.harness]
        summary_json = json.dumps(repository_summary.model_dump(mode="json"), sort_keys=True)
        dims = sorted(BASE_CAPABILITY_DIMENSIONS)
        prompt = (
            "Analyze this coding task for orchestration. "
            "Return only the requested structured JSON.\n"
            f"User request: {user_request}\n"
            f"Repository summary: {summary_json}\n"
            f"Capability dimensions: {dims}\n"
            "Use normalized capability weights from 0 to 1. "
            "Identify required tools, risk, complexity, context "
            "requirements, expected outputs, and whether independent "
            "parallel work is plausible."
        )
        request = WorkerRequest(
            job_id="analysis",
            task_id="analysis",
            objective=prompt,
            repo_path=repository_summary.root,
            workspace_path=None,
            read_only=True,
            timeout_seconds=300,
        )
        _, analysis = await self.executor(adapter, worker, request, TaskAnalysis)
        return analysis
