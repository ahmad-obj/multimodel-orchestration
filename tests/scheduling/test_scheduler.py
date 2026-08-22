from pathlib import Path

from orchestrator.capabilities.scoring import WorkerScorer
from orchestrator.domain.common import CostClass, WorkerStatus
from orchestrator.domain.tasks import SubtaskSpec, TaskPlan, TaskRisk
from orchestrator.domain.workers import WorkerDescriptor, WorkerProfile
from orchestrator.policies.cost import CostPolicy
from orchestrator.scheduling.scheduler import Scheduler


def task(id, dependencies=(), weights=None):
    return SubtaskSpec(
        id=id,
        objective=id,
        capability_weights=weights or {"simple_tasks": 0.8},
        dependencies=list(dependencies),
        expected_outputs=["out"],
        required_tools={"filesystem"},
        read_only=True,
        risk=TaskRisk.LOW,
        verification=["manager_review"],
    )


def plan(*tasks):
    return TaskPlan(
        goal="g", confidence=0.9, subtasks=list(tasks), final_expected_outputs=["done"]
    )


def d(worker_id, cost, cap, reliability=0.8, speed=0.8, paid=False):
    p = WorkerProfile(
        id=worker_id,
        harness="x",
        model="m",
        capabilities={"simple_tasks": cap},
        reliability=reliability,
        speed=speed,
        cost_class=cost,
        parallel_capacity=2,
        tools={"filesystem"},
        is_paid=paid,
    )
    return WorkerDescriptor(
        profile=p, executable_path=Path("/fake"), status=WorkerStatus.AVAILABLE
    )


class Registry:
    def __init__(self, workers):
        self._w = workers

    def available(self):
        return self._w


def test_ready_tasks_respects_dependencies():
    p = plan(task("T1"), task("T2"), task("T3", ["T1", "T2"]))
    scheduler = Scheduler(
        registry=Registry([]), scorer=WorkerScorer(), cost_policy=CostPolicy()
    )
    assert [
        item.id for item in scheduler.ready_tasks(p, completed=set(), running=set())
    ] == ["T1", "T2"]
    assert [
        item.id
        for item in scheduler.ready_tasks(p, completed={"T1", "T2"}, running=set())
    ] == ["T3"]


def test_assign_prefers_free_adequate_and_never_paid(tmp_path):
    workers = [
        d("free", CostClass.FREE, 0.82, speed=0.95),
        d("included", CostClass.INCLUDED, 0.95, reliability=0.9, speed=0.5),
        d("paid", CostClass.PAID, 1.0, paid=True),
    ]
    scheduler = Scheduler(Registry(workers), WorkerScorer(), CostPolicy())
    assignment = scheduler.assign("job", task("T1"), tmp_path)
    assert assignment.worker_id == "free"


def test_assign_respects_persisted_preferred_worker_after_reassignment(tmp_path):
    workers = [
        d("free-fast", CostClass.FREE, 0.95, speed=1.0),
        d("free-reassigned", CostClass.FREE, 0.8, speed=0.5),
    ]
    scheduler = Scheduler(Registry(workers), WorkerScorer(), CostPolicy())

    assignment = scheduler.assign(
        "job",
        task("T1"),
        tmp_path,
        preferred_worker_id="free-reassigned",
    )

    assert assignment.worker_id == "free-reassigned"
