from pathlib import Path
from types import SimpleNamespace

import pytest

from orchestrator.domain.jobs import JobStatus, TaskStatus
from orchestrator.domain.tasks import SubtaskSpec, TaskRisk
from orchestrator.runtime.langgraph import LangGraphRuntime


class Jobs:
    async def get(self, job_id):
        return SimpleNamespace(
            job_id=job_id,
            original_request="do work",
            repo_path=str(Path.cwd()),
            status=JobStatus.RUNNING,
        )


class Tasks:
    def __init__(self):
        self.item = SimpleNamespace(
            spec=SubtaskSpec(
                id="T1",
                objective="paid approved task",
                capability_weights={"coding": 1.0},
                expected_outputs=["done"],
                read_only=True,
                risk=TaskRisk.LOW,
                verification=[],
            ),
            status=TaskStatus.READY,
            assigned_worker_id="paid/frontier",
        )

    async def list_for_job(self, _job_id):
        return [self.item]


class Scheduler:
    def __init__(self):
        self.running = None
        self.assign_called = False

    def ready_tasks(self, plan, *, completed, running):
        self.running = running
        return []

    def assign(self, *args, **kwargs):
        self.assign_called = True
        raise AssertionError("READY tasks must not be rescheduled")


@pytest.mark.asyncio
async def test_ready_preassigned_task_is_not_rescheduled():
    scheduler = Scheduler()
    runtime = LangGraphRuntime(
        SimpleNamespace(path=Path("unused.db")),
        scheduler=scheduler,
        executor=SimpleNamespace(),
        jobs=Jobs(),
        tasks=Tasks(),
    )

    await runtime._schedule_ready(
        {
            "job_id": "j1",
            "cycle": 0,
            "completed_task_ids": [],
            "failed_task_ids": [],
            "stop_reason": None,
        }
    )

    assert scheduler.running == {"T1"}
    assert not scheduler.assign_called
