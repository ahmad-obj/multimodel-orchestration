from orchestrator.capabilities.history import PerformanceHistory, PerformanceObservation
from orchestrator.capabilities.scoring import WorkerScorer
from orchestrator.domain.common import CostClass
from orchestrator.domain.tasks import TaskAnalysis, TaskComplexity, TaskRisk
from orchestrator.domain.workers import WorkerProfile


def _profile(worker_id: str) -> WorkerProfile:
    return WorkerProfile(
        id=worker_id,
        harness="fake",
        model=worker_id,
        capabilities={"debugging": 0.8},
        reliability=0.7,
        speed=0.7,
        cost_class=CostClass.FREE,
        parallel_capacity=1,
    )


def _analysis(task_type: str = "debugging") -> TaskAnalysis:
    capability = "debugging" if task_type == "debugging" else "research"
    return TaskAnalysis(
        task_type=task_type,
        complexity=TaskComplexity.HIGH,
        risk=TaskRisk.MEDIUM,
        confidence=0.9,
        capability_weights={capability: 1.0},
        required_tools=set(),
        constraints=[],
        expected_outputs=["result"],
        parallelizable_hint=False,
    )


def test_verified_history_breaks_near_equal_worker_tie() -> None:
    rows = []
    for index in range(20):
        rows.append(
            PerformanceObservation(
                worker_id="worker-a",
                task_type="debugging",
                capability_labels={"debugging"},
                difficulty="high",
                verified_success=index < 5,
                attempt_count=1,
                duration_seconds=1,
                manager_acceptance=index < 5,
            )
        )
        rows.append(
            PerformanceObservation(
                worker_id="worker-b",
                task_type="debugging",
                capability_labels={"debugging"},
                difficulty="high",
                verified_success=index < 19,
                attempt_count=1,
                duration_seconds=1,
                manager_acceptance=index < 19,
            )
        )

    scorer = WorkerScorer(history=PerformanceHistory(rows))

    assert (
        scorer.score(_profile("worker-b"), _analysis()).total
        > scorer.score(_profile("worker-a"), _analysis()).total
    )
