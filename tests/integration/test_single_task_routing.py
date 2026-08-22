from pathlib import Path

from orchestrator.domain.common import CostClass, ExecutionStatus, WorkerStatus
from orchestrator.domain.results import WorkerResult
from orchestrator.domain.tasks import TaskAnalysis, TaskComplexity, TaskRisk
from orchestrator.domain.workers import WorkerDescriptor, WorkerProfile
from orchestrator.services.single_task import SingleTaskService


class FakeRegistry:
    def __init__(self, workers):
        self._workers = workers

    async def refresh(self):
        return None

    def available(self):
        return self._workers


class FakeAnalyzer:
    async def analyze(self, user_request, repository_summary):
        return TaskAnalysis(
            task_type="repository_inspection",
            complexity=TaskComplexity.LOW,
            risk=TaskRisk.LOW,
            confidence=0.9,
            capability_weights={"repo_navigation": 0.9, "simple_tasks": 0.8},
            required_tools={"filesystem"},
            constraints=[],
            expected_outputs=["file list"],
            parallelizable_hint=False,
        )


class FakeAdapter:
    async def execute(self, worker, request):
        return WorkerResult(
            execution_id="e",
            worker_id=worker.profile.id,
            task_id=request.task_id,
            status=ExecutionStatus.SUCCEEDED,
            summary="done",
        )


def make(worker_id, cost, nav, simple, reliability, speed):
    p = WorkerProfile(
        id=worker_id,
        harness=worker_id.split("/")[0],
        model="m",
        capabilities={"repo_navigation": nav, "simple_tasks": simple},
        reliability=reliability,
        speed=speed,
        cost_class=cost,
        parallel_capacity=1,
        tools={"filesystem"},
        is_paid=False,
    )
    return WorkerDescriptor(profile=p, executable_path=Path("/fake"), status=WorkerStatus.AVAILABLE)


async def test_easy_task_selects_free_worker(tmp_path) -> None:
    workers = [
        make("codex/default", CostClass.INCLUDED, 0.95, 0.95, 0.82, 0.45),
        make("gemini/flash", CostClass.FREE, 0.85, 0.9, 0.85, 0.95),
    ]
    adapters = {"codex": FakeAdapter(), "gemini": FakeAdapter()}
    service = SingleTaskService(FakeRegistry(workers), adapters, FakeAnalyzer())
    result = await service.run(tmp_path, "list files", repository_summary=object())
    assert result.selection.worker.profile.id == "gemini/flash"
    assert result.result.worker_id == "gemini/flash"
