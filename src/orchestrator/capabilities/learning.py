from __future__ import annotations

from orchestrator.capabilities.history import PerformanceHistory, PerformanceObservation
from orchestrator.domain.events import EventType


class PerformanceLearningService:
    def __init__(
        self,
        performance_repository,
        attempt_repository,
        task_repository,
        event_repository,
    ) -> None:
        self.performance_repository = performance_repository
        self.attempt_repository = attempt_repository
        self.task_repository = task_repository
        self.event_repository = event_repository

    async def load(self, worker_ids: list[str]) -> PerformanceHistory:
        history = PerformanceHistory()
        task_cache: dict[str, dict[str, object]] = {}
        attempt_cache: dict[str, list] = {}
        event_cache: dict[str, list] = {}

        for worker_id in worker_ids:
            outcomes = await self.performance_repository.list_for_worker(worker_id)
            for outcome in outcomes:
                attempt = await self.attempt_repository.get(outcome.execution_id)
                if attempt is None:
                    continue
                job_id = attempt.job_id
                if job_id not in task_cache:
                    stored = await self.task_repository.list_for_job(job_id)
                    task_cache[job_id] = {item.spec.id: item.spec for item in stored}
                spec = task_cache[job_id].get(attempt.task_id)
                if spec is None:
                    continue
                if job_id not in attempt_cache:
                    attempt_cache[job_id] = await self.attempt_repository.list_for_job(job_id)
                if job_id not in event_cache:
                    event_cache[job_id] = await self.event_repository.list_for_job(job_id)

                accepted = False
                for event in event_cache[job_id]:
                    if event.type is not EventType.TASK_ACCEPTED:
                        continue
                    execution_id = event.payload.get("execution_id")
                    if execution_id == outcome.execution_id:
                        accepted = True
                        break
                    if (
                        execution_id is None
                        and event.task_id == attempt.task_id
                        and event.worker_id == worker_id
                    ):
                        accepted = True

                attempts_for_task = [
                    item for item in attempt_cache[job_id] if item.task_id == attempt.task_id
                ]
                labels = {name for name, weight in spec.capability_weights.items() if weight > 0}
                task_type = (
                    max(spec.capability_weights, key=spec.capability_weights.get)
                    if spec.capability_weights
                    else "subtask"
                )
                history.record(
                    PerformanceObservation(
                        worker_id=worker_id,
                        task_type=task_type,
                        capability_labels=labels,
                        difficulty=spec.risk.value,
                        verified_success=accepted,
                        attempt_count=max(1, len(attempts_for_task)),
                        duration_seconds=outcome.duration_seconds,
                        manager_acceptance=accepted,
                        recorded_at=outcome.created_at,
                    )
                )
        return history
