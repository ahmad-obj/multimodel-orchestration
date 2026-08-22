from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from orchestrator.domain.common import CostClass, ExecutionStatus, WorkerStatus
from orchestrator.domain.jobs import JobStatus
from orchestrator.domain.results import WorkerResult
from orchestrator.domain.tasks import SubtaskSpec, TaskPlan, TaskRisk
from orchestrator.domain.workers import WorkerDescriptor, WorkerProfile
from orchestrator.execution.executor import TaskExecutor
from orchestrator.persistence.db import Database
from orchestrator.persistence.repositories import JobRepository, TaskRepository
from orchestrator.runtime import langgraph as lg_mod
from orchestrator.runtime.langgraph import LangGraphRuntime
from orchestrator.scheduling.scheduler import Scheduler


class FakeAdapter:
    async def execute(self, worker, request):
        return WorkerResult(
            execution_id=f"e-{request.task_id}",
            worker_id=worker.profile.id,
            task_id=request.task_id,
            status=ExecutionStatus.SUCCEEDED,
            summary="ok",
        )


class FakeRegistry:
    def __init__(self) -> None:
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
        self.adapters: dict = {"x": FakeAdapter()}

    def available(self):
        return [self.worker]

    def get(self, worker_id: str):
        return self.worker


def _spec(task_id: str) -> SubtaskSpec:
    return SubtaskSpec(
        id=task_id,
        objective=f"do {task_id}",
        capability_weights={"simple_tasks": 0.8},
        dependencies=[],
        expected_outputs=["out"],
        required_tools={"filesystem"},
        read_only=True,
        risk=TaskRisk.LOW,
        verification=["manager_review"],
    )


class _TrackedConn:
    def __init__(self, real_conn):
        self._real = real_conn
        self.close_called = False

    async def close(self):
        self.close_called = True
        await self._real.close()

    def __getattr__(self, name):
        return getattr(self._real, name)


class _ConnTracker:
    def __init__(self) -> None:
        self.created: list[_TrackedConn] = []
        self._orig = lg_mod.aiosqlite.connect

    async def __call__(self, *args, **kwargs):
        real = await self._orig(*args, **kwargs)
        tracked = _TrackedConn(real)
        self.created.append(tracked)
        return tracked

    def all_closed(self) -> bool:
        return all(c.close_called for c in self.created)


async def test_connections_closed_after_run(tmp_path: Path) -> None:
    db_path = tmp_path / "lc.db"
    db = Database(db_path)
    await db.initialize()
    try:
        tracker = _ConnTracker()
        registry = FakeRegistry()
        jobs_repo = JobRepository(db)
        tasks_repo = TaskRepository(db)
        await jobs_repo.create("j", "req", str(tmp_path), JobStatus.CREATED)
        plan = TaskPlan(
            goal="req", confidence=1.0, subtasks=[_spec("T1")], final_expected_outputs=[]
        )
        await tasks_repo.replace_plan("j", plan)
        runtime = LangGraphRuntime(
            db,
            scheduler=Scheduler(registry),
            executor=TaskExecutor(registry),
            jobs=jobs_repo,
            tasks=tasks_repo,
        )
        with patch.object(lg_mod, "aiosqlite", type("M", (), {"connect": staticmethod(tracker)})()):
            await runtime.run("j")
        assert tracker.all_closed()
    finally:
        await db.dispose()


async def test_connections_closed_after_resume(tmp_path: Path) -> None:
    db_path = tmp_path / "lc.db"
    db = Database(db_path)
    await db.initialize()
    try:
        registry = FakeRegistry()
        jobs_repo = JobRepository(db)
        tasks_repo = TaskRepository(db)
        await jobs_repo.create("j", "req", str(tmp_path), JobStatus.CREATED)
        plan = TaskPlan(
            goal="req", confidence=1.0, subtasks=[_spec("T1")], final_expected_outputs=[]
        )
        await tasks_repo.replace_plan("j", plan)
        tracker = _ConnTracker()
        runtime = LangGraphRuntime(
            db,
            scheduler=Scheduler(registry),
            executor=TaskExecutor(registry),
            jobs=jobs_repo,
            tasks=tasks_repo,
        )
        with patch.object(lg_mod, "aiosqlite", type("M", (), {"connect": staticmethod(tracker)})()):
            await runtime.run("j")
        assert tracker.all_closed()
        tracker2 = _ConnTracker()
        with patch.object(
            lg_mod, "aiosqlite", type("M", (), {"connect": staticmethod(tracker2)})()
        ):
            await runtime.resume("j")
        assert tracker2.all_closed()
    finally:
        await db.dispose()


async def test_connections_closed_after_exception(tmp_path: Path) -> None:
    db_path = tmp_path / "lc.db"
    db = Database(db_path)
    await db.initialize()
    try:
        registry = FakeRegistry()
        jobs_repo = JobRepository(db)
        tasks_repo = TaskRepository(db)
        await jobs_repo.create("j", "req", str(tmp_path), JobStatus.CREATED)
        plan = TaskPlan(
            goal="req", confidence=1.0, subtasks=[_spec("T1")], final_expected_outputs=[]
        )
        await tasks_repo.replace_plan("j", plan)
        runtime = LangGraphRuntime(
            db,
            scheduler=Scheduler(registry),
            executor=TaskExecutor(registry),
            jobs=jobs_repo,
            tasks=tasks_repo,
        )
        with patch.object(
            lg_mod,
            "aiosqlite",
            type("M", (), {"connect": staticmethod(AsyncMock(side_effect=RuntimeError("boom")))})(),
        ):
            with pytest.raises(RuntimeError, match="boom"):
                await runtime.run("j")
        assert runtime._inflight.get("j") is None
    finally:
        await db.dispose()
