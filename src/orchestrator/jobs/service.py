from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from orchestrator.domain.jobs import JobStatus, TaskStatus


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
    RESUMABLE = {JobStatus.RUNNING}

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

    async def _pending_approval(self, job_id: str, task_id: str) -> dict[str, object]:
        job = await self.jobs.get(job_id)
        if job is None:
            raise ValueError(f"job {job_id!r} not found")
        if job.status is not JobStatus.WAITING_FOR_APPROVAL:
            raise ValueError(f"job {job_id!r} is not waiting for approval")

        rows = await self.decisions.list_for_job(job_id)
        for row in reversed(rows):
            if row.task_id != task_id:
                continue
            if row.decision_type in {
                "paid_escalation_approved",
                "paid_escalation_rejected",
            }:
                raise ValueError(f"task {task_id!r} approval is already resolved")
            if row.decision_type == "paid_escalation_approval_request":
                return dict(row.payload)
        raise ValueError(f"no pending paid escalation approval for task {task_id!r}")

    async def approve(self, job_id: str, task_id: str, worker_id: str):
        request = await self._pending_approval(job_id, task_id)
        candidates = request.get("candidate_worker_ids", [])
        if not isinstance(candidates, list) or worker_id not in candidates:
            raise ValueError(f"worker {worker_id!r} is not an approved candidate")

        await self.tasks.set_assignment(job_id, task_id, worker_id)
        await self.tasks.set_status(job_id, task_id, TaskStatus.READY)
        await self.decisions.append(
            job_id,
            task_id,
            "paid_escalation_approved",
            {
                "approval_id": request.get("id"),
                "worker_id": worker_id,
                "status": "approved",
            },
        )
        await self.jobs.set_status(job_id, JobStatus.RUNNING)
        return await self.engine.resume_job(job_id)

    async def reject_approval(self, job_id: str, task_id: str):
        request = await self._pending_approval(job_id, task_id)
        await self.tasks.set_status(job_id, task_id, TaskStatus.FAILED)
        await self.decisions.append(
            job_id,
            task_id,
            "paid_escalation_rejected",
            {
                "approval_id": request.get("id"),
                "status": "rejected",
            },
        )
        await self.jobs.set_status(job_id, JobStatus.FAILED)
        return await self.jobs.get(job_id)
