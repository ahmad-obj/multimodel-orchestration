from datetime import UTC, datetime

from pydantic import BaseModel, Field


class PerformanceObservation(BaseModel):
    worker_id: str
    task_type: str
    capability_labels: set[str] = Field(default_factory=set)
    difficulty: str
    verified_success: bool
    attempt_count: int = Field(ge=1)
    duration_seconds: float = Field(ge=0)
    manager_acceptance: bool
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class PerformanceSummary(BaseModel):
    worker_id: str
    sample_count: int
    verified_success_rate: float | None
    history_score: float


class PerformanceHistory:
    def __init__(self, observations: list[PerformanceObservation] | None = None) -> None:
        self._observations = list(observations or [])

    def record(self, observation: PerformanceObservation) -> None:
        self._observations.append(observation)

    def summarize(
        self,
        worker_id: str,
        task_type: str,
        capability_labels: set[str],
        *,
        base_reliability: float,
    ) -> PerformanceSummary:
        rows = [row for row in self._observations if row.worker_id == worker_id]
        specific = [
            row
            for row in rows
            if row.task_type == task_type or bool(row.capability_labels & capability_labels)
        ]
        selected = specific if len(specific) >= 5 else rows
        count = len(selected)
        if count == 0:
            return PerformanceSummary(
                worker_id=worker_id,
                sample_count=0,
                verified_success_rate=None,
                history_score=base_reliability,
            )
        observed = sum(1 for row in selected if row.verified_success) / count
        if count < 5:
            score = base_reliability
        else:
            confidence = min(1.0, count / 20)
            score = base_reliability * (1 - confidence) + observed * confidence
        return PerformanceSummary(
            worker_id=worker_id,
            sample_count=count,
            verified_success_rate=round(observed, 6),
            history_score=round(score, 6),
        )
