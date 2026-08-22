from pathlib import Path
from types import SimpleNamespace

import pytest

from orchestrator.domain.events import EventType, OrchestratorEvent
from orchestrator.domain.jobs import JobStatus, TaskStatus
from orchestrator.domain.tasks import SubtaskSpec, TaskRisk
from orchestrator.jobs.engine import JobEngine


class Registry:
    async def refresh(self):
        pass

    def all(self):
        return []


class Workers:
    async def upsert_descriptor(self, _worker):
        pass

    async def upsert_profile(self, _profile):
        pass


class Jobs:
    def __init__(self, repo_path: Path):
        self.job = SimpleNamespace(
            job_id="job-1",
            original_request="fix it",
            repo_path=str(repo_path),
            status=JobStatus.RUNNING,
            manager_worker_id="manager",
        )

    async def get(self, job_id):
        assert job_id == "job-1"
        return self.job

    async def set_status(self, job_id, status):
        assert job_id == "job-1"
        self.job.status = status


class Tasks:
    def __init__(self):
        self.spec = SubtaskSpec(
            id="T1",
            objective="fix",
            capability_weights={"coding": 1.0},
            expected_outputs=["fix"],
            read_only=False,
            risk=TaskRisk.LOW,
            verification=[],
        )

    async def list_for_job(self, job_id):
        assert job_id == "job-1"
        return [
            SimpleNamespace(
                spec=self.spec,
                status=TaskStatus.COMPLETED,
                assigned_worker_id="worker",
                position=0,
            )
        ]


class Runtime:
    def __init__(self):
        self.resumed = []

    async def resume(self, job_id):
        self.resumed.append(job_id)


class Events:
    async def list_for_job(self, job_id):
        return [
            OrchestratorEvent(
                type=EventType.JOB_CREATED,
                job_id=job_id,
                payload={
                    "repo_path": "/original/repo",
                    "base_sha": "base-original",
                    "branch": "main",
                },
            )
        ]


class Bus:
    def __init__(self):
        self.events = []

    async def publish(self, event):
        self.events.append(event)


class Accepted:
    async def for_job(self, job_id):
        return {"T1": "task-sha"}


class Integration:
    def __init__(self, workspace):
        self.workspace = workspace
        self.calls = []

    async def integrate(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(status="succeeded", head_sha="final-sha")

    def workspace_for(self, job_id):
        return self.workspace


class Verifier:
    async def verify_repository(self, job_id, workspace):
        return SimpleNamespace(passed=True)


@pytest.mark.asyncio
async def test_resume_finishes_integration_from_original_repository_base(tmp_path):
    jobs = Jobs(tmp_path)
    tasks = Tasks()
    runtime = Runtime()
    integration = Integration(tmp_path)
    bus = Bus()
    engine = JobEngine(
        registry=Registry(),
        worker_repository=Workers(),
        job_repository=jobs,
        task_repository=tasks,
        planning=SimpleNamespace(),
        runtime=runtime,
        accepted_commits=Accepted(),
        integration=integration,
        final_verifier=Verifier(),
        event_bus=bus,
        event_repository=Events(),
    )

    result = await engine.resume_job("job-1")

    assert runtime.resumed == ["job-1"]
    assert integration.calls[0]["base_sha"] == "base-original"
    assert result.status is JobStatus.COMPLETED
    assert result.final_sha == "final-sha"
    assert jobs.job.status is JobStatus.COMPLETED
    assert bus.events[-1].type is EventType.JOB_COMPLETED
