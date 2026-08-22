from sqlalchemy import select

from orchestrator.domain.jobs import JobStatus
from orchestrator.persistence import models
from orchestrator.persistence.repositories import (
    JobRepository,
    StoredJob,
    _to_aware,
    _utc_now_naive,
)


class JobStore(JobRepository):
    async def set_manager(self, job_id: str, worker_id: str) -> None:
        now = _utc_now_naive()
        async with self._db.sessions() as session, session.begin():
            row = (
                await session.execute(select(models.JobRow).where(models.JobRow.id == job_id))
            ).scalar_one_or_none()
            if row is None:
                raise ValueError(f"job {job_id!r} not found")
            row.manager_worker_id = worker_id
            row.updated_at = now

    async def list_recent(self, *, limit: int = 50) -> list[StoredJob]:
        if limit < 1:
            raise ValueError("limit must be positive")
        async with self._db.sessions() as session:
            rows = (
                (
                    await session.execute(
                        select(models.JobRow)
                        .order_by(models.JobRow.created_at.desc(), models.JobRow.id.desc())
                        .limit(limit)
                    )
                )
                .scalars()
                .all()
            )
        return [
            StoredJob(
                job_id=row.id,
                original_request=row.original_request,
                repo_path=row.repo_path,
                status=JobStatus(row.status),
                manager_worker_id=row.manager_worker_id,
                created_at=_to_aware(row.created_at),
                updated_at=_to_aware(row.updated_at),
            )
            for row in rows
        ]
