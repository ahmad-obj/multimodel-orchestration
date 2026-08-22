from pathlib import Path

import pytest

from orchestrator.domain.common import CostClass, ExecutionStatus, WorkerStatus
from orchestrator.domain.results import WorkerResult
from orchestrator.domain.tasks import SubtaskSpec, TaskRisk
from orchestrator.domain.workers import WorkerDescriptor, WorkerProfile
from orchestrator.execution.executor import TaskExecutor
from orchestrator.execution.outcomes import OutcomeDisposition, TaskOutcome
from orchestrator.scheduling.scheduler import Assignment


class Adapter:
    async def execute(self, worker, request):
        return WorkerResult(
            execution_id=request.execution_id or "adapter",
            worker_id=worker.profile.id,
            task_id=request.task_id,
            status=ExecutionStatus.FAILED,
            summary="retry me",
        )


class Registry:
    def __init__(self):
        profile = WorkerProfile(
            id="w1",
            harness="fake",
            model="m",
            capabilities={"simple_tasks": 1.0},
            reliability=1.0,
            speed=1.0,
            cost_class=CostClass.FREE,
            parallel_capacity=1,
            tools=set(),
        )
        self.descriptor = WorkerDescriptor(
            profile=profile,
            executable_path=Path("/fake"),
            status=WorkerStatus.AVAILABLE,
        )
        self.adapters = {"fake": Adapter()}

    def get(self, worker_id):
        assert worker_id == "w1"
        return self.descriptor


class DeferredProcessor:
    async def process(self, assignment, result, workspace):
        return TaskOutcome(
            disposition=OutcomeDisposition.RETRY,
            failure_class="implementation_failure",
            next_worker_id="w1",
        )


def make_assignment():
    return Assignment(
        job_id="job-1",
        subtask=SubtaskSpec(
            id="T1",
            objective="inspect",
            capability_weights={"simple_tasks": 1.0},
            expected_outputs=["answer"],
            read_only=True,
            risk=TaskRisk.LOW,
            verification=[],
        ),
        worker_id="w1",
        source_repo=Path("/repo"),
    )


@pytest.mark.asyncio
async def test_execute_many_omits_deferred_outcomes():
    executor = TaskExecutor(Registry(), outcome_processor=DeferredProcessor())

    results = await executor.execute_many([make_assignment()])

    assert executor.manages_task_outcomes is True
    assert results == []
