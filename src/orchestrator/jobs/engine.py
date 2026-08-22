from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel

from orchestrator.analysis.repository import summarize_repository
from orchestrator.domain.events import EventType, OrchestratorEvent
from orchestrator.domain.jobs import JobStatus


class JobRunResult(BaseModel):
    job_id: str
    status: JobStatus
    manager_worker_id: str | None = None
    final_sha: str | None = None
    human_question: str | None = None
    error: str | None = None


class JobEngine:
    def __init__(
        self,
        *,
        registry,
        worker_repository,
        job_repository,
        task_repository,
        planning,
        runtime,
        accepted_commits,
        integration,
        final_verifier,
        event_bus,
        summarizer=summarize_repository,
    ) -> None:
        self.registry = registry
        self.worker_repository = worker_repository
        self.job_repository = job_repository
        self.task_repository = task_repository
        self.planning = planning
        self.runtime = runtime
        self.accepted_commits = accepted_commits
        self.integration = integration
        self.final_verifier = final_verifier
        self.event_bus = event_bus
        self.summarizer = summarizer

    async def _event(self, event_type: EventType, job_id: str, **payload: object) -> None:
        await self.event_bus.publish(
            OrchestratorEvent(type=event_type, job_id=job_id, payload=dict(payload))
        )

    async def _persist_workers(self) -> None:
        for worker in self.registry.all():
            await self.worker_repository.upsert_descriptor(worker)
            await self.worker_repository.upsert_profile(worker.profile)

    async def run_new_job(
        self,
        repo_path: Path,
        objective: str,
        *,
        job_id: str | None = None,
    ) -> JobRunResult:
        job_id = job_id or f"job-{uuid4().hex[:12]}"
        summary = self.summarizer(repo_path)
        await self.registry.refresh()
        await self._persist_workers()
        await self.job_repository.create(
            job_id,
            objective,
            str(summary.root),
            status=JobStatus.CREATED,
        )
        await self._event(EventType.JOB_CREATED, job_id)
        try:
            await self.job_repository.set_status(job_id, JobStatus.PLANNING)
            await self._event(EventType.ANALYSIS_STARTED, job_id)
            planned = await self.planning.plan(objective, summary, self.registry)
            await self._event(
                EventType.ANALYSIS_COMPLETED,
                job_id,
                task_type=planned.analysis.task_type,
                confidence=planned.analysis.confidence,
            )
            set_manager = getattr(self.job_repository, "set_manager", None)
            if set_manager is not None:
                await set_manager(job_id, planned.manager_worker_id)
            await self._event(
                EventType.MANAGER_SELECTED,
                job_id,
                manager_worker_id=planned.manager_worker_id,
                reason=planned.manager_selection_reason,
            )
            await self._event(
                EventType.PLAN_CREATED,
                job_id,
                task_count=len(planned.plan.subtasks),
                confidence=planned.plan.confidence,
            )
            if planned.requires_human_input:
                await self.job_repository.set_status(job_id, JobStatus.PAUSED)
                question = planned.human_question or "Additional input is required before execution."
                await self._event(
                    EventType.HUMAN_INPUT_REQUIRED,
                    job_id,
                    question=question,
                )
                return JobRunResult(
                    job_id=job_id,
                    status=JobStatus.PAUSED,
                    manager_worker_id=planned.manager_worker_id,
                    human_question=question,
                )

            await self.task_repository.replace_plan(job_id, planned.plan)
            await self.job_repository.set_status(job_id, JobStatus.RUNNING)
            await self.runtime.run(job_id)

            persisted = await self.job_repository.get(job_id)
            if persisted is not None and persisted.status in {
                JobStatus.PAUSED,
                JobStatus.WAITING_FOR_APPROVAL,
                JobStatus.CANCELLED,
                JobStatus.FAILED,
            }:
                return JobRunResult(
                    job_id=job_id,
                    status=persisted.status,
                    manager_worker_id=planned.manager_worker_id,
                )

            commits = await self.accepted_commits.for_job(job_id)
            await self._event(EventType.INTEGRATION_STARTED, job_id, commit_count=len(commits))
            integrated = await self.integration.integrate(
                job_id=job_id,
                source_repo=summary.root,
                base_sha=summary.head_sha,
                plan=planned.plan,
                accepted_commits=commits,
            )
            await self._event(
                EventType.INTEGRATION_COMPLETED,
                job_id,
                status=integrated.status,
                head_sha=integrated.head_sha,
            )
            if integrated.status != "succeeded":
                raise RuntimeError(f"integration ended with status {integrated.status}")
            workspace = self.integration.workspace_for(job_id)
            verification = await self.final_verifier.verify_repository(job_id, workspace)
            if not verification.passed:
                raise RuntimeError("final verification failed")

            await self.job_repository.set_status(job_id, JobStatus.COMPLETED)
            await self._event(EventType.JOB_COMPLETED, job_id, final_sha=integrated.head_sha)
            return JobRunResult(
                job_id=job_id,
                status=JobStatus.COMPLETED,
                manager_worker_id=planned.manager_worker_id,
                final_sha=integrated.head_sha,
            )
        except Exception as exc:
            await self.job_repository.set_status(job_id, JobStatus.FAILED)
            await self._event(EventType.JOB_FAILED, job_id, error=str(exc))
            raise
