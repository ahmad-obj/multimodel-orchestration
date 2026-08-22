from orchestrator.capabilities.history import PerformanceHistory, PerformanceObservation


def _outcome(
    worker_id: str,
    *,
    task_type: str = "debugging",
    labels: tuple[str, ...] = ("debugging",),
    success: bool = True,
) -> PerformanceObservation:
    return PerformanceObservation(
        worker_id=worker_id,
        task_type=task_type,
        capability_labels=set(labels),
        difficulty="medium",
        verified_success=success,
        attempt_count=1,
        duration_seconds=1,
        manager_acceptance=success,
    )


def test_under_five_samples_use_base_reliability() -> None:
    history = PerformanceHistory([_outcome("worker") for _ in range(4)])

    summary = history.summarize(
        "worker", "debugging", {"debugging"}, base_reliability=0.7
    )

    assert summary.sample_count == 4
    assert summary.history_score == 0.7


def test_twenty_samples_use_observed_success_rate() -> None:
    rows = [_outcome("worker") for _ in range(16)] + [
        _outcome("worker", success=False) for _ in range(4)
    ]
    history = PerformanceHistory(rows)

    summary = history.summarize(
        "worker", "debugging", {"debugging"}, base_reliability=0.5
    )

    assert summary.sample_count == 20
    assert summary.verified_success_rate == 0.8
    assert summary.history_score == 0.8


def test_specific_history_wins_over_unrelated_history() -> None:
    rows = [_outcome("worker") for _ in range(10)] + [
        _outcome(
            "worker",
            task_type="research",
            labels=("research",),
            success=False,
        )
        for _ in range(20)
    ]
    history = PerformanceHistory(rows)

    summary = history.summarize(
        "worker", "debugging", {"debugging"}, base_reliability=0.5
    )

    assert summary.sample_count == 10
    assert summary.verified_success_rate == 1.0
    assert summary.history_score == 0.75
