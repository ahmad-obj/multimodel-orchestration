from pathlib import Path

import aiosqlite
import pytest

from orchestrator.domain.common import CostClass, ExecutionStatus, WorkerStatus
from orchestrator.domain.jobs import JobStatus, TaskStatus
from orchestrator.domain.results import WorkerResult
from orchestrator.domain.tasks import SubtaskSpec, TaskPlan, TaskRisk
from orchestrator.domain.workers import WorkerDescriptor, WorkerProfile
from orchestrator.execution.executor import TaskExecutor
from orchestrator.persistence.db import Database
from orchestrator.persistence.repositories import JobRepository, TaskRepository
from orchestrator.runtime.langgraph import LangGraphRuntime
from orchestrator.scheduling.scheduler import Scheduler


class FlakyAdapter:
    def __init__(self, *, fail_task_ids: set[str] | None = None) -> None:
        self.fail_task_ids = fail_task_ids or set()
        self.executions: list[str] = []

    async def execute(self, worker, request):
        self.executions.append(request.task_id)
        if request.task_id in self.fail_task_ids:
            self.fail_task_ids.discard(request.task_id)
            raise RuntimeError("simulated crash")
        return WorkerResult(
            execution_id=f"e-{request.task_id}",
            worker_id=worker.profile.id,
            task_id=request.task_id,
            status=ExecutionStatus.SUCCEEDED,
            summary="ok",
        )


class FakeRegistry:
    def __init__(self, adapter: FlakyAdapter) -> None:
        p = WorkerProfile(
            id="w",
            harness="x",
            model="m",
            capabilities={"simple_tasks": 0.9},
            reliability=0.9,
            speed=0.9,
            cost_class=CostClass.FREE,
            parallel_capacity=2,
            tools={"filesystem"},
            is_paid=False,
        )
        self.worker = WorkerDescriptor(
            profile=p, executable_path=Path("/fake"), status=WorkerStatus.AVAILABLE
        )
        self.adapters: dict = {"x": adapter}

    def available(self):
        return [self.worker]

    def get(self, worker_id: str):
        return self.worker


def _spec(task_id: str, deps: list[str] | None = None) -> SubtaskSpec:
    return SubtaskSpec(
        id=task_id,
        objective=f"do {task_id}",
        capability_weights={"simple_tasks": 0.8},
        dependencies=deps or [],
        expected_outputs=["out"],
        required_tools={"filesystem"},
        read_only=True,
        risk=TaskRisk.LOW,
        verification=["manager_review"],
    )


async def test_durable_crash_restart_resume(tmp_path: Path) -> None:
    db_path = tmp_path / "orch.db"

    adapter1 = FlakyAdapter(fail_task_ids={"T2"})
    registry1 = FakeRegistry(adapter1)
    executor1 = TaskExecutor(registry1)
    scheduler = Scheduler(registry1)

    db1 = Database(db_path)
    await db1.initialize()
    try:
        jobs_repo1 = JobRepository(db1)
        tasks_repo1 = TaskRepository(db1)

        await jobs_repo1.create(
            job_id="job-1",
            original_request="do work",
            repo_path=str(tmp_path),
            status=JobStatus.CREATED,
        )

        plan = TaskPlan(
            goal="do work",
            confidence=1.0,
            subtasks=[_spec("T1"), _spec("T2", ["T1"]), _spec("T3", ["T2"])],
            final_expected_outputs=[],
        )
        await tasks_repo1.replace_plan("job-1", plan)

        runtime1 = LangGraphRuntime(
            db1,
            scheduler=scheduler,
            executor=executor1,
            jobs=jobs_repo1,
            tasks=tasks_repo1,
        )

        with pytest.raises(RuntimeError, match="simulated crash"):
            await runtime1.run("job-1")

        job1 = await jobs_repo1.get("job-1")
        assert job1 is not None

        t1_status = (await tasks_repo1.list_for_job("job-1"))[0].status
        assert t1_status == TaskStatus.COMPLETED
    finally:
        await db1.dispose()

    adapter2 = FlakyAdapter()
    registry2 = FakeRegistry(adapter2)
    executor2 = TaskExecutor(registry2)
    scheduler2 = Scheduler(registry2)

    db2 = Database(db_path)
    await db2.initialize()
    try:
        jobs_repo2 = JobRepository(db2)
        tasks_repo2 = TaskRepository(db2)

        runtime2 = LangGraphRuntime(
            db2,
            scheduler=scheduler2,
            executor=executor2,
            jobs=jobs_repo2,
            tasks=tasks_repo2,
        )

        await runtime2.resume("job-1")

        t1_count = adapter1.executions.count("T1") + adapter2.executions.count("T1")
        assert t1_count == 1, f"T1 executed {t1_count} times; expected exactly 1"
        assert sorted(adapter2.executions) == ["T2", "T3"]

        job2 = await jobs_repo2.get("job-1")
        assert job2 is not None
        assert job2.status == JobStatus.RUNNING

        final_tasks = await tasks_repo2.list_for_job("job-1")
        final_statuses = {t.spec.id: t.status for t in final_tasks}
        assert final_statuses == {
            "T1": TaskStatus.COMPLETED,
            "T2": TaskStatus.COMPLETED,
            "T3": TaskStatus.COMPLETED,
        }

        conn = await aiosqlite.connect(str(db_path))
        try:
            cursor = await conn.execute(
                "SELECT thread_id FROM checkpoints WHERE thread_id = ?",
                ("job-1",),
            )
            rows = await cursor.fetchall()
            assert len(rows) >= 1, f"no checkpoints found for thread_id 'job-1': {rows}"
        finally:
            await conn.close()
    finally:
        await db2.dispose()
