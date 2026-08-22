from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from orchestrator.domain.jobs import JobStatus


@dataclass(slots=True)
class JobSnapshot:
    job: Any
    tasks: list[Any]
    attempts: list[Any]
    artifacts: list[Any]
    decisions: list[Any]
    verifications: list[Any]
    events: list[Any]


class JobControlService:
    RESUMABLE = {JobStatus.RUNNING, JobStatus.PAUSED}

    def __init__(
        self,
        *,
        jobs,
        tasks,
        attempts,
        artifacts,
        decisions,
        verifications,
        events,
        engine,
        runtime,
    ) -> None:
        self.jobs = jobs
        self.tasks = tasks
        self.attempts = attempts
        self.artifacts = artifacts
        self.decisions = decisions
        self.verifications = verifications
        self.events = events
        self.engine = engine
        self.runtime = runtime

    async def run(self, repo_path: Path, objective: str, *, job_id: str | None = None):
        return await self.engine.run_new_job(repo_path, objective, job_id=job_id)

    async def list_jobs(self, *, limit: int = 50):
        return await self.jobs.list_recent(limit=limit)

    async def inspect(self, job_id: str) -> JobSnapshot:
        job = await self.jobs.get(job_id)
        if job is None:
            raise ValueError(f"job {job_id!r} not found")
        return JobSnapshot(
            job=job,
            tasks=await self.tasks.list_for_job(job_id),
            attempts=await self.attempts.list_for_job(job_id),
            artifacts=await self.artifacts.list_for_job(job_id),
            decisions=await self.decisions.list_for_job(job_id),
            verifications=await self.verifications.list_for_job(job_id),
            events=await self.events.list_for_job(job_id),
        )

    async def resume(self, job_id: str):
        job = await self.jobs.get(job_id)
        if job is None:
            raise ValueError(f"job {job_id!r} not found")
        if job.status not in self.RESUMABLE:
            raise ValueError(f"job {job_id!r} is not resumable from {job.status.value}")
        return await self.engine.resume_job(job_id)

    async def cancel(self, job_id: str):
        job = await self.jobs.get(job_id)
        if job is None:
            raise ValueError(f"job {job_id!r} not found")
        if job.status in {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}:
            raise ValueError(f"job {job_id!r} is already terminal")
        await self.runtime.cancel(job_id)
        return await self.jobs.get(job_id)
