from types import SimpleNamespace

import pytest

from orchestrator.domain.common import ExecutionStatus
from orchestrator.domain.events import EventType, OrchestratorEvent
from orchestrator.domain.results import WorkerResult
from orchestrator.execution.accepted import AcceptedCommitStore


class Events:
    async def list_for_job(self, job_id: str):
        return [
            OrchestratorEvent(type=EventType.TASK_ACCEPTED, job_id=job_id, task_id="T1"),
            OrchestratorEvent(type=EventType.TASK_ACCEPTED, job_id=job_id, task_id="T2"),
        ]


class Attempts:
    async def list_for_job(self, job_id: str):
        def row(task_id: str, execution_id: str, commit: str | None):
            result = WorkerResult(
                execution_id=execution_id,
                worker_id="worker",
                task_id=task_id,
                status=ExecutionStatus.SUCCEEDED,
                summary="done",
                local_commit=commit,
            )
            return SimpleNamespace(
                task_id=task_id,
                status=ExecutionStatus.SUCCEEDED,
                result_json=result.model_dump_json(),
                execution_id=execution_id,
            )

        return [
            row("T1", "exec-1", "old-sha"),
            row("T1", "exec-2", "new-sha"),
            row("T2", "exec-3", None),
        ]


@pytest.mark.asyncio
async def test_returns_latest_accepted_local_commits_only() -> None:
    store = AcceptedCommitStore(Attempts(), Events())

    assert await store.for_job("job-1") == {"T1": "new-sha"}
