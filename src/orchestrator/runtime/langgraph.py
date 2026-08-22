from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Protocol, TypedDict

os.environ.setdefault("LANGGRAPH_STRICT_MSGPACK", "true")

import aiosqlite  # noqa: E402
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver  # noqa: E402
from langgraph.graph import END, START, StateGraph  # noqa: E402

from orchestrator.domain.common import ExecutionStatus
from orchestrator.domain.jobs import JobStatus, TaskStatus
from orchestrator.domain.tasks import TaskPlan
from orchestrator.execution.executor import TaskExecutor
from orchestrator.persistence.db import Database
from orchestrator.persistence.repositories import JobRepository, TaskRepository
from orchestrator.scheduling.scheduler import Assignment, Scheduler

_STOP_ALL_COMPLETED = "all_completed"
_STOP_FAILED_PREFIX = "task_failed:"
_STOP_JOB_PREFIX = "job_"
_NODE_SCHEDULE = "schedule_ready"
_NODE_EXECUTE = "execute_ready"
_NODE_EVALUATE = "evaluate_progress"


class GraphState(TypedDict):
    job_id: str
    cycle: int
    completed_task_ids: list[str]
    failed_task_ids: list[str]
    stop_reason: str | None


class ProgressEvaluator(Protocol):
    async def evaluate(
        self,
        *,
        job_id: str,
        completed_task_ids: list[str],
        failed_task_ids: list[str],
        runnable_tasks_remaining: bool,
    ) -> str | None: ...


def _initial_state(job_id: str) -> GraphState:
    return {
        "job_id": job_id,
        "cycle": 0,
        "completed_task_ids": [],
        "failed_task_ids": [],
        "stop_reason": None,
    }


_TERMINAL_JOB_STATUSES = frozenset(
    {JobStatus.CANCELLED, JobStatus.PAUSED, JobStatus.WAITING_FOR_APPROVAL}
)


def _job_stop_reason(status: JobStatus) -> str | None:
    if status in _TERMINAL_JOB_STATUSES:
        return f"{_STOP_JOB_PREFIX}{status.value}"
    return None


def _reconstructed_plan(job, stored_tasks):
    return TaskPlan(
        goal=job.original_request,
        confidence=1.0,
        subtasks=[t.spec for t in stored_tasks],
        final_expected_outputs=[],
    )


class LangGraphRuntime:
    def __init__(
        self,
        db: Database,
        *,
        scheduler: Scheduler,
        executor: TaskExecutor,
        progress_evaluator: ProgressEvaluator | None = None,
        jobs: JobRepository | None = None,
        tasks: TaskRepository | None = None,
    ) -> None:
        self._db = db
        self._scheduler = scheduler
        self._executor = executor
        self._evaluator = progress_evaluator
        self._jobs = jobs or JobRepository(db)
        self._tasks = tasks or TaskRepository(db)
        self._inflight: dict[str, asyncio.Task] = {}

    async def run(self, job_id: str) -> None:
        await self._drive(job_id, initial=True)

    async def resume(self, job_id: str) -> None:
        await self._drive(job_id, initial=False)

    async def cancel(self, job_id: str) -> None:
        job = await self._jobs.get(job_id)
        if job is None:
            return
        if job.status != JobStatus.CANCELLED:
            await self._jobs.set_status(job_id, JobStatus.CANCELLED)
        task = self._inflight.pop(job_id, None)
        if task is not None and not task.done():
            task.cancel()

    async def _drive(self, job_id: str, *, initial: bool) -> None:
        self._inflight[job_id] = asyncio.current_task()
        try:
            job = await self._jobs.get(job_id)
            if job is None:
                raise ValueError(f"job {job_id!r} not found")
            if initial and job.status in (JobStatus.CREATED, JobStatus.PLANNING):
                await self._jobs.set_status(job_id, JobStatus.RUNNING)
            conn = await aiosqlite.connect(str(self._db.path))
            try:
                await conn.execute("PRAGMA journal_mode=WAL")
                await conn.execute("PRAGMA busy_timeout=5000")
                saver = AsyncSqliteSaver(conn)
                await saver.setup()
                graph = self._compile(saver)
                config = {"configurable": {"thread_id": job_id}}
                if initial:
                    await graph.ainvoke(_initial_state(job_id), config=config)
                else:
                    snapshot = await graph.aget_state(config)
                    if snapshot.created_at is None:
                        await graph.ainvoke(_initial_state(job_id), config=config)
                    else:
                        await graph.ainvoke(None, config=config)
                final = await graph.aget_state(config)
                stop = final.values.get("stop_reason")
                await self._finalize(job_id, stop)
            finally:
                await conn.close()
        finally:
            self._inflight.pop(job_id, None)

    async def _finalize(self, job_id: str, stop_reason: str | None) -> None:
        if stop_reason is None or stop_reason == _STOP_ALL_COMPLETED:
            return
        job = await self._jobs.get(job_id)
        if job is None:
            return
        if stop_reason.startswith(_STOP_FAILED_PREFIX) and job.status != JobStatus.FAILED:
            await self._jobs.set_status(job_id, JobStatus.FAILED)

    def _compile(self, checkpointer: AsyncSqliteSaver) -> any:
        builder = StateGraph(GraphState)
        builder.add_node(_NODE_SCHEDULE, self._schedule_ready)
        builder.add_node(_NODE_EXECUTE, self._execute_ready)
        builder.add_node(_NODE_EVALUATE, self._evaluate_progress)
        builder.add_edge(START, _NODE_SCHEDULE)
        builder.add_edge(_NODE_SCHEDULE, _NODE_EXECUTE)
        builder.add_edge(_NODE_EXECUTE, _NODE_EVALUATE)
        builder.add_conditional_edges(
            _NODE_EVALUATE,
            self._route_after_evaluation,
            {_NODE_SCHEDULE: _NODE_SCHEDULE, END: END},
        )
        return builder.compile(checkpointer=checkpointer)

    async def _require_job(self, job_id: str):
        job = await self._jobs.get(job_id)
        if job is None:
            raise ValueError(f"job {job_id!r} not found")
        return job

    async def _schedule_ready(self, state: GraphState) -> dict:
        job_id = state["job_id"]
        job = await self._require_job(job_id)
        stop = _job_stop_reason(job.status)
        if stop:
            return {"stop_reason": stop}
        stored = await self._tasks.list_for_job(job_id)
        stored_by_id = {item.spec.id: item for item in stored}
        completed = {t.spec.id for t in stored if t.status is TaskStatus.COMPLETED}
        running = {
            t.spec.id
            for t in stored
            if t.status in {TaskStatus.READY, TaskStatus.RUNNING}
        }
        plan = _reconstructed_plan(job, stored)
        ready = self._scheduler.ready_tasks(plan, completed=completed, running=running)
        for subtask in ready:
            preferred = stored_by_id[subtask.id].assigned_worker_id
            assignment = self._scheduler.assign(
                job_id,
                subtask,
                Path(job.repo_path),
                preferred_worker_id=preferred,
            )
            await self._tasks.set_assignment(job_id, subtask.id, assignment.worker_id)
            await self._tasks.set_status(job_id, subtask.id, TaskStatus.READY)
        return {"cycle": state["cycle"] + 1}

    async def _execute_ready(self, state: GraphState) -> dict:
        job_id = state["job_id"]
        job = await self._require_job(job_id)
        stop = _job_stop_reason(job.status)
        if stop:
            return {"stop_reason": stop}
        stored = await self._tasks.list_for_job(job_id)
        actionable = [t for t in stored if t.status in (TaskStatus.READY, TaskStatus.RUNNING)]
        assignments = []
        for item in actionable:
            worker_id = item.assigned_worker_id
            if worker_id is None:
                raise RuntimeError(f"task {item.spec.id} has no persisted worker assignment")
            assignments.append(
                Assignment(
                    job_id=job_id,
                    subtask=item.spec,
                    worker_id=worker_id,
                    source_repo=Path(job.repo_path),
                )
            )
            await self._tasks.set_status(job_id, item.spec.id, TaskStatus.RUNNING)
        if not assignments:
            return {}
        results = await self._executor.execute_many(assignments)
        succeeded = sorted(r.task_id for r in results if r.status is ExecutionStatus.SUCCEEDED)
        failed = sorted(r.task_id for r in results if r.status is not ExecutionStatus.SUCCEEDED)
        for task_id in succeeded:
            await self._tasks.set_status(job_id, task_id, TaskStatus.COMPLETED)
        for task_id in failed:
            await self._tasks.set_status(job_id, task_id, TaskStatus.FAILED)
        completed = set(state["completed_task_ids"]) | set(succeeded)
        failures = (set(state["failed_task_ids"]) | set(failed)) - completed
        return {"completed_task_ids": sorted(completed), "failed_task_ids": sorted(failures)}

    async def _evaluate_progress(self, state: GraphState) -> dict:
        job_id = state["job_id"]
        job = await self._require_job(job_id)
        stop = _job_stop_reason(job.status)
        if stop:
            return {"stop_reason": stop}
        stored = await self._tasks.list_for_job(job_id)
        completed_ids = sorted(t.spec.id for t in stored if t.status is TaskStatus.COMPLETED)
        failed_ids = sorted(t.spec.id for t in stored if t.status is TaskStatus.FAILED)
        has_failed = len(failed_ids) > 0
        has_pending = any(
            t.status in (TaskStatus.PENDING, TaskStatus.READY, TaskStatus.RUNNING) for t in stored
        )
        all_completed = all(t.status == TaskStatus.COMPLETED for t in stored) if stored else False
        if self._evaluator is not None:
            try:
                decision = await self._evaluator.evaluate(
                    job_id=job_id,
                    completed_task_ids=completed_ids,
                    failed_task_ids=failed_ids,
                    runnable_tasks_remaining=has_pending,
                )
                if decision is not None:
                    return {"stop_reason": decision}
            except Exception:
                pass
        if has_failed:
            return {"stop_reason": f"{_STOP_FAILED_PREFIX}{','.join(failed_ids)}"}
        if all_completed:
            return {"stop_reason": _STOP_ALL_COMPLETED}
        return {}

    @staticmethod
    def _route_after_evaluation(state: GraphState) -> str:
        if state.get("stop_reason"):
            return END
        return _NODE_SCHEDULE
