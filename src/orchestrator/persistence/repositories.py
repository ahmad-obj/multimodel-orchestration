from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from orchestrator.domain.artifacts import ArtifactRef
from orchestrator.domain.common import ExecutionStatus, WorkerStatus
from orchestrator.domain.events import EventType, OrchestratorEvent
from orchestrator.domain.jobs import JobStatus, TaskStatus
from orchestrator.domain.results import WorkerResult
from orchestrator.domain.tasks import SubtaskSpec, TaskPlan
from orchestrator.domain.workers import WorkerDescriptor, WorkerProfile
from orchestrator.persistence import models
from orchestrator.persistence.db import Database

_UTC = UTC


def _utc_now_naive() -> datetime:
    return datetime.now(_UTC).replace(tzinfo=None)


def _to_aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=_UTC)
    return dt.astimezone(_UTC)


def _dump_json(value: Mapping[str, Any] | dict[str, Any]) -> str:
    if isinstance(value, dict):
        return json.dumps(value, sort_keys=True, default=str)
    return json.dumps(dict(value), sort_keys=True, default=str)


class StoredJob(BaseModel):
    job_id: str
    original_request: str
    repo_path: str
    status: JobStatus
    manager_worker_id: str | None
    created_at: datetime
    updated_at: datetime


class StoredTask(BaseModel):
    spec: SubtaskSpec
    status: TaskStatus
    assigned_worker_id: str | None
    position: int


class StoredAttempt(BaseModel):
    execution_id: str
    job_id: str
    task_id: str
    worker_id: str
    status: ExecutionStatus | None
    result_json: str | None
    failure_class: str | None
    started_at: datetime
    finished_at: datetime | None


class StoredArtifact(BaseModel):
    artifact_ref: ArtifactRef
    metadata: dict[str, object]
    recorded_at: datetime


class StoredDecision(BaseModel):
    decision_type: str
    task_id: str | None
    payload: dict[str, object]
    created_at: datetime


class StoredVerification(BaseModel):
    task_id: str
    verification_json: str
    created_at: datetime


class StoredCostUsage(BaseModel):
    task_id: str
    worker_id: str
    usage_json: str
    created_at: datetime


class StoredPerformanceOutcome(BaseModel):
    execution_id: str
    task_id: str
    status: ExecutionStatus
    confidence: float
    duration_seconds: float
    usage: dict[str, object]
    created_at: datetime


class WorkerRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def upsert_descriptor(self, worker: WorkerDescriptor) -> None:
        now = _utc_now_naive()
        data = {
            "id": worker.profile.id,
            "executable_path": str(worker.executable_path) if worker.executable_path else None,
            "status": worker.status.value,
            "health_reason": worker.health_reason,
            "updated_at": now,
        }
        stmt = (
            sqlite_insert(models.WorkerRow)
            .values(**data)
            .on_conflict_do_update(index_elements=["id"], set_=data)
        )
        async with self._db.sessions() as session, session.begin():
            await session.execute(stmt)

    async def upsert_profile(self, profile: WorkerProfile) -> None:
        pj = profile.model_dump_json()
        stmt = (
            sqlite_insert(models.WorkerProfileRow)
            .values(worker_id=profile.id, profile_json=pj)
            .on_conflict_do_update(index_elements=["worker_id"], set_={"profile_json": pj})
        )
        async with self._db.sessions() as session, session.begin():
            await session.execute(stmt)

    async def get_profile(self, worker_id: str) -> WorkerProfile | None:
        async with self._db.sessions() as session:
            row = (
                await session.execute(
                    select(models.WorkerProfileRow).where(
                        models.WorkerProfileRow.worker_id == worker_id
                    )
                )
            ).scalar_one_or_none()
        if row is None:
            return None
        return WorkerProfile.model_validate_json(row.profile_json)

    async def get_descriptor(self, worker_id: str) -> WorkerDescriptor | None:
        from pathlib import Path as _Path

        async with self._db.sessions() as session:
            w_row = (
                await session.execute(
                    select(models.WorkerRow).where(models.WorkerRow.id == worker_id)
                )
            ).scalar_one_or_none()
            if w_row is None:
                return None
            p_row = (
                await session.execute(
                    select(models.WorkerProfileRow).where(
                        models.WorkerProfileRow.worker_id == worker_id
                    )
                )
            ).scalar_one_or_none()
            if p_row is None:
                return None
        profile = WorkerProfile.model_validate_json(p_row.profile_json)
        executable = _Path(w_row.executable_path) if w_row.executable_path else None
        return WorkerDescriptor(
            profile=profile,
            executable_path=executable,
            status=WorkerStatus(w_row.status),
            health_reason=w_row.health_reason,
        )


class JobRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def create(
        self,
        job_id: str,
        original_request: str,
        repo_path: str,
        status: JobStatus,
        manager_worker_id: str | None = None,
    ) -> StoredJob:
        now = _utc_now_naive()
        async with self._db.sessions() as session, session.begin():
            row = models.JobRow(
                id=job_id,
                original_request=original_request,
                repo_path=str(repo_path),
                status=status.value,
                manager_worker_id=manager_worker_id,
                created_at=now,
                updated_at=now,
            )
            session.add(row)
        return StoredJob(
            job_id=job_id,
            original_request=original_request,
            repo_path=str(repo_path),
            status=status,
            manager_worker_id=manager_worker_id,
            created_at=_to_aware(now),
            updated_at=_to_aware(now),
        )

    async def get(self, job_id: str) -> StoredJob | None:
        async with self._db.sessions() as session:
            row = (
                await session.execute(select(models.JobRow).where(models.JobRow.id == job_id))
            ).scalar_one_or_none()
        if row is None:
            return None
        return StoredJob(
            job_id=row.id,
            original_request=row.original_request,
            repo_path=row.repo_path,
            status=JobStatus(row.status),
            manager_worker_id=row.manager_worker_id,
            created_at=_to_aware(row.created_at),
            updated_at=_to_aware(row.updated_at),
        )

    async def set_status(self, job_id: str, status: JobStatus) -> None:
        now = _utc_now_naive()
        async with self._db.sessions() as session, session.begin():
            result = await session.execute(select(models.JobRow).where(models.JobRow.id == job_id))
            row = result.scalar_one_or_none()
            if row is None:
                raise ValueError(f"job {job_id!r} not found")
            row.status = status.value
            row.updated_at = now


class TaskRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def replace_plan(self, job_id: str, plan: TaskPlan) -> None:
        async with self._db.sessions() as session, session.begin():
            await session.execute(
                delete(models.TaskDependencyRow).where(models.TaskDependencyRow.job_id == job_id)
            )
            await session.execute(delete(models.TaskRow).where(models.TaskRow.job_id == job_id))
            for position, spec in enumerate(plan.subtasks):
                session.add(
                    models.TaskRow(
                        job_id=job_id,
                        task_id=spec.id,
                        position=position,
                        spec_json=spec.model_dump_json(),
                        status=TaskStatus.PENDING.value,
                    )
                )
            await session.flush()
            for spec in plan.subtasks:
                for dep in spec.dependencies:
                    session.add(
                        models.TaskDependencyRow(
                            job_id=job_id,
                            task_id=spec.id,
                            depends_on_task_id=dep,
                        )
                    )

    async def list_for_job(self, job_id: str) -> list[StoredTask]:
        async with self._db.sessions() as session:
            rows = (
                (
                    await session.execute(
                        select(models.TaskRow)
                        .where(models.TaskRow.job_id == job_id)
                        .order_by(models.TaskRow.position)
                    )
                )
                .scalars()
                .all()
            )
        return [
            StoredTask(
                spec=SubtaskSpec.model_validate_json(r.spec_json),
                status=TaskStatus(r.status),
                assigned_worker_id=r.assigned_worker_id,
                position=r.position,
            )
            for r in rows
        ]

    async def set_assignment(self, job_id: str, task_id: str, worker_id: str) -> None:
        async with self._db.sessions() as session, session.begin():
            result = await session.execute(
                select(models.TaskRow).where(
                    models.TaskRow.job_id == job_id,
                    models.TaskRow.task_id == task_id,
                )
            )
            row = result.scalar_one_or_none()
            if row is None:
                raise ValueError(f"task ({job_id!r}, {task_id!r}) not found")
            row.assigned_worker_id = worker_id

    async def set_status(self, job_id: str, task_id: str, status: TaskStatus) -> None:
        async with self._db.sessions() as session, session.begin():
            result = await session.execute(
                select(models.TaskRow).where(
                    models.TaskRow.job_id == job_id,
                    models.TaskRow.task_id == task_id,
                )
            )
            row = result.scalar_one_or_none()
            if row is None:
                raise ValueError(f"task ({job_id!r}, {task_id!r}) not found")
            row.status = status.value


class AttemptRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def start(self, job_id: str, task_id: str, worker_id: str, execution_id: str) -> str:
        now = _utc_now_naive()
        async with self._db.sessions() as session, session.begin():
            session.add(
                models.AttemptRow(
                    execution_id=execution_id,
                    job_id=job_id,
                    task_id=task_id,
                    worker_id=worker_id,
                    started_at=now,
                )
            )
        return execution_id

    async def finish(
        self,
        execution_id: str,
        status: ExecutionStatus,
        result_json: str | None = None,
        failure_class: str | None = None,
    ) -> None:
        now = _utc_now_naive()
        async with self._db.sessions() as session, session.begin():
            result = await session.execute(
                select(models.AttemptRow).where(models.AttemptRow.execution_id == execution_id)
            )
            row = result.scalar_one_or_none()
            if row is None:
                raise ValueError(f"attempt {execution_id!r} not found")
            row.status = status.value
            row.result_json = result_json
            row.failure_class = failure_class
            row.finished_at = now

    async def get(self, execution_id: str) -> StoredAttempt | None:
        async with self._db.sessions() as session:
            row = (
                await session.execute(
                    select(models.AttemptRow).where(models.AttemptRow.execution_id == execution_id)
                )
            ).scalar_one_or_none()
        if row is None:
            return None
        return StoredAttempt(
            execution_id=row.execution_id,
            job_id=row.job_id,
            task_id=row.task_id,
            worker_id=row.worker_id,
            status=ExecutionStatus(row.status) if row.status else None,
            result_json=row.result_json,
            failure_class=row.failure_class,
            started_at=_to_aware(row.started_at),
            finished_at=_to_aware(row.finished_at) if row.finished_at else None,
        )

    async def list_for_job(self, job_id: str) -> list[StoredAttempt]:
        async with self._db.sessions() as session:
            rows = (
                (
                    await session.execute(
                        select(models.AttemptRow)
                        .where(models.AttemptRow.job_id == job_id)
                        .order_by(models.AttemptRow.id)
                    )
                )
                .scalars()
                .all()
            )
        return [
            StoredAttempt(
                execution_id=r.execution_id,
                job_id=r.job_id,
                task_id=r.task_id,
                worker_id=r.worker_id,
                status=ExecutionStatus(r.status) if r.status else None,
                result_json=r.result_json,
                failure_class=r.failure_class,
                started_at=_to_aware(r.started_at),
                finished_at=_to_aware(r.finished_at) if r.finished_at else None,
            )
            for r in rows
        ]


class ArtifactRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def record(
        self,
        job_id: str,
        task_id: str,
        artifact_ref: ArtifactRef,
        metadata: Mapping[str, Any],
    ) -> StoredArtifact:
        now = _utc_now_naive()
        async with self._db.sessions() as session, session.begin():
            session.add(
                models.ArtifactRow(
                    job_id=job_id,
                    task_id=task_id,
                    artifact_uri=artifact_ref.uri,
                    metadata_json=_dump_json(metadata),
                    created_at=now,
                )
            )
        return StoredArtifact(
            artifact_ref=artifact_ref,
            metadata=dict(metadata),
            recorded_at=_to_aware(now),
        )

    async def list_for_job(self, job_id: str) -> list[StoredArtifact]:
        async with self._db.sessions() as session:
            rows = (
                (
                    await session.execute(
                        select(models.ArtifactRow)
                        .where(models.ArtifactRow.job_id == job_id)
                        .order_by(models.ArtifactRow.id)
                    )
                )
                .scalars()
                .all()
            )
        return [
            StoredArtifact(
                artifact_ref=ArtifactRef(uri=r.artifact_uri),
                metadata=json.loads(r.metadata_json),
                recorded_at=_to_aware(r.created_at),
            )
            for r in rows
        ]


class DecisionRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def append(
        self,
        job_id: str,
        task_id: str | None,
        decision_type: str,
        payload: Mapping[str, Any],
    ) -> StoredDecision:
        now = _utc_now_naive()
        async with self._db.sessions() as session, session.begin():
            session.add(
                models.DecisionRow(
                    job_id=job_id,
                    task_id=task_id,
                    decision_type=decision_type,
                    payload_json=_dump_json(payload),
                    created_at=now,
                )
            )
        return StoredDecision(
            decision_type=decision_type,
            task_id=task_id,
            payload=dict(payload),
            created_at=_to_aware(now),
        )

    async def list_for_job(self, job_id: str) -> list[StoredDecision]:
        async with self._db.sessions() as session:
            rows = (
                (
                    await session.execute(
                        select(models.DecisionRow)
                        .where(models.DecisionRow.job_id == job_id)
                        .order_by(models.DecisionRow.id)
                    )
                )
                .scalars()
                .all()
            )
        return [
            StoredDecision(
                decision_type=r.decision_type,
                task_id=r.task_id,
                payload=json.loads(r.payload_json),
                created_at=_to_aware(r.created_at),
            )
            for r in rows
        ]


class VerificationRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def record(self, job_id: str, task_id: str, verification_json: str) -> StoredVerification:
        now = _utc_now_naive()
        async with self._db.sessions() as session, session.begin():
            session.add(
                models.VerificationRunRow(
                    job_id=job_id,
                    task_id=task_id,
                    verification_json=verification_json,
                    created_at=now,
                )
            )
        return StoredVerification(
            task_id=task_id,
            verification_json=verification_json,
            created_at=_to_aware(now),
        )

    async def list_for_job(self, job_id: str) -> list[StoredVerification]:
        async with self._db.sessions() as session:
            rows = (
                (
                    await session.execute(
                        select(models.VerificationRunRow)
                        .where(models.VerificationRunRow.job_id == job_id)
                        .order_by(models.VerificationRunRow.id)
                    )
                )
                .scalars()
                .all()
            )
        return [
            StoredVerification(
                task_id=r.task_id,
                verification_json=r.verification_json,
                created_at=_to_aware(r.created_at),
            )
            for r in rows
        ]


class CostUsageRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def record(
        self, job_id: str, task_id: str, worker_id: str, usage_json: str
    ) -> StoredCostUsage:
        now = _utc_now_naive()
        async with self._db.sessions() as session, session.begin():
            session.add(
                models.CostUsageRow(
                    job_id=job_id,
                    task_id=task_id,
                    worker_id=worker_id,
                    usage_json=usage_json,
                    created_at=now,
                )
            )
        return StoredCostUsage(
            task_id=task_id,
            worker_id=worker_id,
            usage_json=usage_json,
            created_at=_to_aware(now),
        )

    async def list_for_job(self, job_id: str) -> list[StoredCostUsage]:
        async with self._db.sessions() as session:
            rows = (
                (
                    await session.execute(
                        select(models.CostUsageRow)
                        .where(models.CostUsageRow.job_id == job_id)
                        .order_by(models.CostUsageRow.id)
                    )
                )
                .scalars()
                .all()
            )
        return [
            StoredCostUsage(
                task_id=r.task_id,
                worker_id=r.worker_id,
                usage_json=r.usage_json,
                created_at=_to_aware(r.created_at),
            )
            for r in rows
        ]


class EventRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def append(self, event: OrchestratorEvent) -> None:
        ts = event.timestamp
        if ts.tzinfo is not None:
            ts = ts.astimezone(_UTC).replace(tzinfo=None)
        async with self._db.sessions() as session, session.begin():
            session.add(
                models.EventRow(
                    type=event.type.value,
                    job_id=event.job_id,
                    task_id=event.task_id,
                    worker_id=event.worker_id,
                    payload_json=json.dumps(event.payload, default=str),
                    timestamp=ts,
                )
            )

    async def list_for_job(self, job_id: str) -> list[OrchestratorEvent]:
        async with self._db.sessions() as session:
            rows = (
                (
                    await session.execute(
                        select(models.EventRow)
                        .where(models.EventRow.job_id == job_id)
                        .order_by(models.EventRow.id)
                    )
                )
                .scalars()
                .all()
            )
        return [
            OrchestratorEvent(
                type=EventType(r.type),
                job_id=r.job_id,
                task_id=r.task_id,
                worker_id=r.worker_id,
                payload=json.loads(r.payload_json),
                timestamp=_to_aware(r.timestamp),
            )
            for r in rows
        ]


class WorkerPerformanceRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def record_outcome(self, outcome: WorkerResult) -> StoredPerformanceOutcome:
        now = _utc_now_naive()
        async with self._db.sessions() as session, session.begin():
            session.add(
                models.WorkerPerformanceRow(
                    worker_id=outcome.worker_id,
                    task_id=outcome.task_id,
                    execution_id=outcome.execution_id,
                    status=outcome.status.value,
                    confidence=outcome.confidence,
                    duration_seconds=outcome.duration_seconds,
                    usage_json=_dump_json(outcome.usage),
                    created_at=now,
                )
            )
        return StoredPerformanceOutcome(
            execution_id=outcome.execution_id,
            task_id=outcome.task_id,
            status=outcome.status,
            confidence=outcome.confidence,
            duration_seconds=outcome.duration_seconds,
            usage=dict(outcome.usage),
            created_at=_to_aware(now),
        )

    async def list_for_worker(self, worker_id: str) -> list[StoredPerformanceOutcome]:
        async with self._db.sessions() as session:
            rows = (
                (
                    await session.execute(
                        select(models.WorkerPerformanceRow)
                        .where(models.WorkerPerformanceRow.worker_id == worker_id)
                        .order_by(models.WorkerPerformanceRow.id)
                    )
                )
                .scalars()
                .all()
            )
        return [
            StoredPerformanceOutcome(
                execution_id=r.execution_id,
                task_id=r.task_id,
                status=ExecutionStatus(r.status),
                confidence=r.confidence,
                duration_seconds=r.duration_seconds,
                usage=json.loads(r.usage_json),
                created_at=_to_aware(r.created_at),
            )
            for r in rows
        ]
