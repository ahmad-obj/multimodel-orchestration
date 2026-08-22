from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel

from orchestrator.analysis.repository import summarize_repository
from orchestrator.domain.events import EventType, OrchestratorEvent
from orchestrator.domain.jobs import JobStatus
from orchestrator.domain.tasks import TaskPlan


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
        event_repository=None,
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
        self.event_repository = event_repository or getattr(event_bus, "repository", None)
        self.summarizer = summarizer

    async def _event(self, event_type: EventType, job_id: str, **payload: object) -> None:
        await self.event_bus.publish(
            OrchestratorEvent(type=event_type, job_id=job_id, payload=dict(payload))
        )

    async def _persist_workers(self) -> None:
        for worker in self.registry.all():
            await self.worker_repository.upsert_descriptor(worker)
            await self.worker_repository.upsert_profile(worker.profile)

    async def _repository_snapshot(self, job_id: str) -> dict[str, object]:
        if self.event_repository is None:
            raise RuntimeError("job resume requires persisted event repository")
        events = await self.event_repository.list_for_job(job_id)
        for event in events:
            if event.type is EventType.JOB_CREATED:
                base_sha = event.payload.get("base_sha")
                if isinstance(base_sha, str) and base_sha:
                    return event.payload
        raise RuntimeError(f"job {job_id} has no persisted repository snapshot")

    @staticmethod
    def _plan_from_tasks(job, tasks) -> TaskPlan:
        return TaskPlan(
            goal=job.original_request,
            confidence=1.0,
            subtasks=[item.spec for item in tasks],
            final_expected_outputs=[],
        )

    async def _finish_execution(
        self,
        *,
        job_id: str,
        plan: TaskPlan,
        source_repo: Path,
        base_sha: str,
        manager_worker_id: str | None,
    ) -> JobRunResult:
        persisted = await self.job_repository.get(job_id)
        if persisted is None:
            raise ValueError(f"job {job_id!r} not found")
        if persisted.status in {
            JobStatus.PAUSED,
            JobStatus.WAITING_FOR_APPROVAL,
            JobStatus.CANCELLED,
            JobStatus.FAILED,
        }:
            return JobRunResult(
                job_id=job_id,
                status=persisted.status,
                manager_worker_id=manager_worker_id,
            )

        commits = await self.accepted_commits.for_job(job_id)
        await self._event(EventType.INTEGRATION_STARTED, job_id, commit_count=len(commits))
        integrated = await self.integration.integrate(
            job_id=job_id,
            source_repo=source_repo,
            base_sha=base_sha,
            plan=plan,
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
            manager_worker_id=manager_worker_id,
            final_sha=integrated.head_sha,
        )

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
        await self._event(
            EventType.JOB_CREATED,
            job_id,
            repo_path=str(summary.root),
            base_sha=summary.head_sha,
            branch=getattr(summary, "branch", None),
        )
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
            return await self._finish_execution(
                job_id=job_id,
                plan=planned.plan,
                source_repo=summary.root,
                base_sha=summary.head_sha,
                manager_worker_id=planned.manager_worker_id,
            )
        except Exception as exc:
            await self.job_repository.set_status(job_id, JobStatus.FAILED)
            await self._event(EventType.JOB_FAILED, job_id, error=str(exc))
            raise

    async def resume_job(self, job_id: str) -> JobRunResult:
        job = await self.job_repository.get(job_id)
        if job is None:
            raise ValueError(f"job {job_id!r} not found")
        if job.status is not JobStatus.RUNNING:
            raise ValueError(f"job {job_id!r} is not resumable from status {job.status.value}")
        tasks = await self.task_repository.list_for_job(job_id)
        if not tasks:
            raise ValueError(f"job {job_id!r} has no persisted task plan")
        snapshot = await self._repository_snapshot(job_id)
        base_sha = snapshot["base_sha"]
        if not isinstance(base_sha, str):
            raise RuntimeError("persisted repository base_sha is invalid")
        await self.registry.refresh()
        await self._persist_workers()
        try:
            await self.runtime.resume(job_id)
            return await self._finish_execution(
                job_id=job_id,
                plan=self._plan_from_tasks(job, tasks),
                source_repo=Path(job.repo_path),
                base_sha=base_sha,
                manager_worker_id=job.manager_worker_id,
            )
        except Exception as exc:
            await self.job_repository.set_status(job_id, JobStatus.FAILED)
            await self._event(EventType.JOB_FAILED, job_id, error=str(exc))
            raise
