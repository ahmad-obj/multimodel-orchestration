from orchestrator.domain.common import CostClass, WorkerStatus
from orchestrator.domain.tasks import TaskAnalysis, TaskComplexity, TaskRisk
from orchestrator.domain.workers import WorkerDescriptor, WorkerProfile
from orchestrator.policies.cost import CostPolicy
from orchestrator.selection.filters import eligible_workers


def analysis():
    return TaskAnalysis(
        task_type="debugging",
        complexity=TaskComplexity.HIGH,
        risk=TaskRisk.MEDIUM,
        confidence=0.9,
        capability_weights={"coding": 0.9},
        required_tools={"filesystem", "git"},
        constraints=[],
        expected_outputs=["fix"],
        parallelizable_hint=False,
    )


def worker(*, paid=False, tools=None, can_manage=True, modify=True, status=WorkerStatus.AVAILABLE):
    p = WorkerProfile(
        id=f"w-{paid}-{len(tools or [])}",
        harness="x",
        model="m",
        capabilities={"coding": 0.9},
        reliability=0.9,
        speed=0.7,
        cost_class=CostClass.PAID if paid else CostClass.FREE,
        parallel_capacity=1,
        tools=set(tools or []),
        can_manage=can_manage,
        can_modify_repo=modify,
        is_paid=paid,
    )
    return WorkerDescriptor(profile=p, executable_path=None, status=status)


def test_filters_reject_paid_missing_tools_and_nonmanager() -> None:
    candidates = [
        worker(paid=True, tools={"filesystem", "git"}),
        worker(tools={"filesystem"}),
        worker(tools={"filesystem", "git"}, can_manage=False),
    ]
    result = eligible_workers(
        candidates, analysis(), CostPolicy(), for_manager=True, requires_write=True
    )
    assert result.eligible == []
    assert len(result.rejected) == 3
