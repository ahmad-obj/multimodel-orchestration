from pathlib import Path

from orchestrator.domain.common import CostClass, WorkerStatus
from orchestrator.domain.tasks import SubtaskSpec, TaskRisk
from orchestrator.domain.workers import WorkerDescriptor, WorkerProfile
from orchestrator.execution.failures import FailureClass
from orchestrator.policies.cost import CostPolicy
from orchestrator.policies.escalation import EscalationActionType, EscalationPolicy


class Registry:
    def __init__(self, workers):
        self._workers = workers

    def available(self):
        return self._workers

    def get(self, worker_id):
        return next(item for item in self._workers if item.profile.id == worker_id)


def worker(worker_id, capability, cost=CostClass.FREE, paid=False):
    profile = WorkerProfile(
        id=worker_id,
        harness="x",
        model=worker_id,
        capabilities={"coding": capability},
        reliability=0.8,
        speed=0.8,
        cost_class=cost,
        parallel_capacity=1,
        tools={"filesystem", "shell", "git"},
        can_modify_repo=True,
        is_paid=paid,
    )
    return WorkerDescriptor(
        profile=profile,
        executable_path=Path("/x"),
        status=WorkerStatus.AVAILABLE,
    )


def task():
    return SubtaskSpec(
        id="T",
        objective="fix",
        capability_weights={"coding": 1},
        expected_outputs=["fix"],
        read_only=False,
        risk=TaskRisk.LOW,
        verification=[],
    )


def test_timeout_retries_same_once_then_alternative():
    registry = Registry([worker("a", 0.8), worker("b", 0.8)])
    policy = EscalationPolicy()
    first = policy.decide(
        FailureClass.TIMEOUT,
        ["a"],
        task(),
        1,
        registry,
        current_worker_id="a",
    )
    assert first.type is EscalationActionType.RETRY_SAME
    second = policy.decide(
        FailureClass.TIMEOUT,
        ["a", "a"],
        task(),
        2,
        registry,
        current_worker_id="a",
    )
    assert second.type is EscalationActionType.REASSIGN
    assert second.worker_id == "b"


def test_implementation_failure_uses_different_worker():
    registry = Registry([worker("a", 0.7), worker("b", 0.8)])
    action = EscalationPolicy().decide(
        FailureClass.IMPLEMENTATION_FAILURE,
        ["a"],
        task(),
        1,
        registry,
        current_worker_id="a",
    )
    assert action.type in {EscalationActionType.REASSIGN, EscalationActionType.ESCALATE}
    assert action.worker_id == "b"


def test_paid_candidate_requires_approval():
    registry = Registry(
        [worker("a", 0.6), worker("premium", 1, CostClass.PAID, True)]
    )
    action = EscalationPolicy(cost_policy=CostPolicy(allow_paid=False)).decide(
        FailureClass.INSUFFICIENT_CAPABILITY,
        ["a"],
        task(),
        1,
        registry,
        current_worker_id="a",
    )
    assert action.type is EscalationActionType.REQUIRES_USER_APPROVAL
    assert action.candidate_worker_ids == ["premium"]


def test_policy_failure_stops_and_attempts_are_bounded():
    registry = Registry([worker("a", 0.8), worker("b", 0.9)])
    policy = EscalationPolicy()
    blocked = policy.decide(
        FailureClass.POLICY_PERMISSION,
        ["a"],
        task(),
        1,
        registry,
        current_worker_id="a",
    )
    capped = policy.decide(
        FailureClass.UNKNOWN,
        ["a", "b", "a", "b"],
        task(),
        4,
        registry,
        current_worker_id="b",
    )
    assert blocked.type is EscalationActionType.STOP
    assert capped.type is EscalationActionType.STOP
