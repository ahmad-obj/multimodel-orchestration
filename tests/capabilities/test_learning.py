from datetime import datetime, timezone
from types import SimpleNamespace

from orchestrator.capabilities.learning import PerformanceLearningService
from orchestrator.domain.common import ExecutionStatus
from orchestrator.domain.events import EventType, OrchestratorEvent
from orchestrator.domain.jobs import TaskStatus
from orchestrator.domain.tasks import SubtaskSpec, TaskRisk
from orchestrator.persistence.repositories import StoredPerformanceOutcome, StoredTask


class PerformanceRepo:
    async def list_for_worker(self, worker_id):
        assert worker_id == "w1"
        return [
            StoredPerformanceOutcome(
                execution_id="e1",
                task_id="T1",
                status=ExecutionStatus.SUCCEEDED,
                confidence=0.9,
                duration_seconds=2.0,
                usage={},
                created_at=datetime.now(timezone.utc),
            ),
            StoredPerformanceOutcome(
                execution_id="e2",
                task_id="T1",
                status=ExecutionStatus.SUCCEEDED,
                confidence=0.7,
                duration_seconds=3.0,
                usage={},
                created_at=datetime.now(timezone.utc),
            ),
        ]


class Attempts:
    async def get(self, execution_id):
        return SimpleNamespace(
            execution_id=execution_id,
            job_id="job-1",
            task_id="T1",
            worker_id="w1",
            started_at=datetime.now(timezone.utc),
        )

    async def list_for_job(self, _job_id):
        return [
            SimpleNamespace(execution_id="e1", task_id="T1"),
            SimpleNamespace(execution_id="e2", task_id="T1"),
        ]


class Tasks:
    async def list_for_job(self, _job_id):
        spec = SubtaskSpec(
            id="T1",
            objective="fix bug",
            capability_weights={"debugging": 1.0, "coding": 0.6},
            expected_outputs=["fix"],
            read_only=False,
            risk=TaskRisk.MEDIUM,
            verification=[],
        )
        return [
            StoredTask(
                spec=spec,
                status=TaskStatus.COMPLETED,
                assigned_worker_id="w1",
                position=0,
            )
        ]


class Events:
    async def list_for_job(self, _job_id):
        return [
            OrchestratorEvent(
                type=EventType.TASK_ACCEPTED,
                job_id="job-1",
                task_id="T1",
                worker_id="w1",
                payload={"execution_id": "e2"},
            )
        ]


async def test_learning_rebuilds_verified_task_specific_history():
    service = PerformanceLearningService(
        PerformanceRepo(),
        Attempts(),
        Tasks(),
        Events(),
    )

    history = await service.load(["w1"])
    summary = history.summarize(
        "w1",
        "debugging",
        {"debugging"},
        base_reliability=0.8,
    )

    assert summary.sample_count == 2
    assert summary.verified_success_rate == 0.5
