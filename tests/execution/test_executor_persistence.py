from pathlib import Path

import pytest

from orchestrator.domain.common import CostClass, ExecutionStatus, WorkerStatus
from orchestrator.domain.results import WorkerResult
from orchestrator.domain.tasks import SubtaskSpec, TaskRisk
from orchestrator.domain.workers import WorkerDescriptor, WorkerProfile
from orchestrator.execution.executor import TaskExecutor
from orchestrator.scheduling.scheduler import Assignment


class AttemptRecorder:
    def __init__(self) -> None:
        self.started: tuple[str, str, str, str] | None = None
        self.finished: tuple[str, ExecutionStatus, str | None, str | None] | None = None

    async def start(self, job_id, task_id, worker_id, execution_id) -> None:
        self.started = (job_id, task_id, worker_id, execution_id)

    async def finish(self, execution_id, status, result_json, failure_class) -> None:
        self.finished = (execution_id, status, result_json, failure_class)


class Adapter:
    def __init__(self) -> None:
        self.execution_id: str | None = None

    async def execute(self, worker, request):
        self.execution_id = request.execution_id
        return WorkerResult(
            execution_id="adapter-generated-id",
            worker_id=worker.profile.id,
            task_id=request.task_id,
            status=ExecutionStatus.SUCCEEDED,
            summary="done",
            confidence=1.0,
        )


class Registry:
    def __init__(self, descriptor, adapter) -> None:
        self.descriptor = descriptor
        self.adapters = {descriptor.profile.harness: adapter}

    def get(self, worker_id):
        assert worker_id == self.descriptor.profile.id
        return self.descriptor


@pytest.mark.asyncio
async def test_executor_persists_attempt_around_worker_execution(tmp_path: Path) -> None:
    profile = WorkerProfile(
        id="worker/default",
        harness="fake",
        model="fake-model",
        capabilities={"repo_navigation": 1.0},
        reliability=1.0,
        speed=1.0,
        cost_class=CostClass.FREE,
        parallel_capacity=1,
        tools={"filesystem"},
    )
    descriptor = WorkerDescriptor(
        profile=profile,
        executable_path=Path("/fake"),
        status=WorkerStatus.AVAILABLE,
    )
    adapter = Adapter()
    attempts = AttemptRecorder()
    executor = TaskExecutor(
        Registry(descriptor, adapter),
        attempt_repository=attempts,
    )
    subtask = SubtaskSpec(
        id="T1",
        objective="inspect repository",
        capability_weights={"repo_navigation": 1.0},
        expected_outputs=["report"],
        read_only=True,
        risk=TaskRisk.LOW,
        verification=[],
    )
    assignment = Assignment(
        job_id="job-1",
        subtask=subtask,
        worker_id=profile.id,
        source_repo=tmp_path,
    )

    result = await executor.execute_assignment(assignment)

    assert attempts.started is not None
    execution_id = attempts.started[3]
    assert adapter.execution_id == execution_id
    assert result.execution_id == execution_id
    assert attempts.finished is not None
    assert attempts.finished[0] == execution_id
    assert attempts.finished[1] is ExecutionStatus.SUCCEEDED
    assert attempts.finished[2] is not None
    persisted = WorkerResult.model_validate_json(attempts.finished[2])
    assert persisted.execution_id == execution_id
