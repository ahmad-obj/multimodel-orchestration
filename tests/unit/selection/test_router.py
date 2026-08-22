from pathlib import Path

import pytest

from orchestrator.domain.common import CostClass, WorkerStatus
from orchestrator.domain.tasks import TaskAnalysis, TaskComplexity, TaskRisk
from orchestrator.domain.workers import WorkerDescriptor, WorkerProfile
from orchestrator.selection.manager import RankedManager
from orchestrator.selection.router import InvalidRouterDecision, ManagerRouter


def d(worker_id):
    p = WorkerProfile(
        id=worker_id,
        harness="x",
        model="m",
        capabilities={"reasoning": 0.8, "simple_tasks": 0.8},
        reliability=0.8,
        speed=0.8,
        cost_class=CostClass.FREE,
        parallel_capacity=1,
        tools={"filesystem"},
        can_manage=True,
        is_paid=False,
    )
    return WorkerDescriptor(profile=p, executable_path=Path("/fake"), status=WorkerStatus.AVAILABLE)


class FakeExecutor:
    async def __call__(self, *args, **kwargs):
        from orchestrator.domain.common import ExecutionStatus
        from orchestrator.domain.results import WorkerResult
        from orchestrator.selection.router import RouterDecision

        worker = args[1]
        decision = RouterDecision(worker_id="other", reason="bad")
        return WorkerResult(
            execution_id="e",
            worker_id=worker.profile.id,
            task_id="router",
            status=ExecutionStatus.SUCCEEDED,
            summary="ok",
            structured_output=decision.model_dump(),
        ), decision


async def test_router_cannot_choose_non_candidate() -> None:
    analysis = TaskAnalysis(
        task_type="x",
        complexity=TaskComplexity.LOW,
        risk=TaskRisk.LOW,
        confidence=0.9,
        capability_weights={"reasoning": 0.8},
        required_tools={"filesystem"},
        constraints=[],
        expected_outputs=["x"],
        parallelizable_hint=False,
    )
    candidates = [
        RankedManager(worker=d("a"), score=0.8, reason="x"),
        RankedManager(worker=d("b"), score=0.79, reason="y"),
    ]
    registry = type(
        "R", (), {"available": lambda self: [d("router")], "adapters": {"x": object()}}
    )()
    with pytest.raises(InvalidRouterDecision):
        await ManagerRouter(registry, FakeExecutor()).break_tie(analysis, candidates)
