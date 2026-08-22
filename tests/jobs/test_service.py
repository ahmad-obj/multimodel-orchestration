from types import SimpleNamespace

import pytest

from orchestrator.domain.jobs import JobStatus
from orchestrator.jobs.service import JobControlService


class Jobs:
    async def list_recent(self, limit=50):
        return [SimpleNamespace(job_id="j1", status=JobStatus.RUNNING)]

    async def get(self, job_id):
        return SimpleNamespace(job_id=job_id, status=JobStatus.RUNNING)


class Repo:
    async def list_for_job(self, job_id):
        return [SimpleNamespace(job_id=job_id)]


class Engine:
    async def run_new_job(self, repo_path, objective, job_id=None):
        return SimpleNamespace(job_id=job_id or "generated", status=JobStatus.COMPLETED)

    async def resume_job(self, job_id):
        return SimpleNamespace(job_id=job_id, status=JobStatus.COMPLETED)


class Runtime:
    def __init__(self):
        self.cancelled = []

    async def cancel(self, job_id):
        self.cancelled.append(job_id)


@pytest.mark.asyncio
async def test_job_control_inspection_collects_durable_views():
    service = JobControlService(
        jobs=Jobs(),
        tasks=Repo(),
        attempts=Repo(),
        artifacts=Repo(),
        decisions=Repo(),
        verifications=Repo(),
        events=Repo(),
        engine=Engine(),
        runtime=Runtime(),
    )

    snapshot = await service.inspect("j1")

    assert snapshot.job.job_id == "j1"
    assert len(snapshot.tasks) == 1
    assert len(snapshot.attempts) == 1
    assert len(snapshot.events) == 1


@pytest.mark.asyncio
async def test_job_control_delegates_resume_and_cancel():
    runtime = Runtime()
    service = JobControlService(
        jobs=Jobs(),
        tasks=Repo(),
        attempts=Repo(),
        artifacts=Repo(),
        decisions=Repo(),
        verifications=Repo(),
        events=Repo(),
        engine=Engine(),
        runtime=runtime,
    )

    resumed = await service.resume("j1")
    cancelled = await service.cancel("j1")

    assert resumed.status is JobStatus.COMPLETED
    assert cancelled.status is JobStatus.RUNNING
    assert runtime.cancelled == ["j1"]
