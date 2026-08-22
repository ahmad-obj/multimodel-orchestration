from pathlib import Path

import pytest

from orchestrator.domain.common import CostClass, ExecutionStatus, WorkerStatus
from orchestrator.domain.results import WorkerResult
from orchestrator.domain.tasks import SubtaskSpec, TaskPlan, TaskRisk
from orchestrator.domain.workers import WorkerDescriptor, WorkerProfile
from orchestrator.managers.models import ManagerAction
from orchestrator.managers.supervisor import ManagerPolicyError, ManagerSupervisor


class Adapter:
    def __init__(self, payload):
        self.payload = payload
        self.requests = []

    async def execute(self, worker, request):
        self.requests.append(request)
        return WorkerResult(
            execution_id="e",
            worker_id=worker.profile.id,
            task_id=request.task_id,
            status=ExecutionStatus.SUCCEEDED,
            summary="decision",
            structured_output=self.payload,
        )


class Registry:
    def __init__(self, workers, adapter):
        self.workers = {worker.profile.id: worker for worker in workers}
        self.adapters = {"fake": adapter}

    def get(self, worker_id):
        return self.workers[worker_id]

    def available(self):
        return list(self.workers.values())


def worker(worker_id, paid=False):
    profile = WorkerProfile(
        id=worker_id,
        harness="fake",
        model=worker_id,
        capabilities={"reasoning": 0.9},
        reliability=0.9,
        speed=0.8,
        cost_class=CostClass.PAID if paid else CostClass.INCLUDED,
        parallel_capacity=1,
        tools={"filesystem", "git"},
        can_manage=True,
        is_paid=paid,
    )
    return WorkerDescriptor(
        profile=profile,
        executable_path=Path("/x"),
        status=WorkerStatus.AVAILABLE,
    )


def subtask(task_id="T1", dependencies=None):
    return SubtaskSpec(
        id=task_id,
        objective="inspect",
        capability_weights={"reasoning": 1},
        dependencies=dependencies or [],
        expected_outputs=["x"],
        required_tools=set(),
        read_only=True,
        risk=TaskRisk.LOW,
        verification=[],
    )


def plan():
    return TaskPlan(
        goal="g",
        confidence=0.9,
        subtasks=[subtask()],
        final_expected_outputs=["done"],
    )


@pytest.mark.asyncio
async def test_paid_reassignment_request_is_rejected(tmp_path):
    payload = {
        "action": "reassign",
        "task_ids": ["T1"],
        "reason": "x",
        "requested_worker_id": "paid",
    }
    registry = Registry([worker("manager"), worker("paid", True)], Adapter(payload))
    with pytest.raises(ManagerPolicyError, match="paid"):
        await ManagerSupervisor(registry).review_cycle(
            "manager", plan(), {"objective": "g"}, tmp_path, completed_task_ids=set()
        )


@pytest.mark.asyncio
async def test_invalid_new_dependency_is_rejected_by_plan_validator(tmp_path):
    new = subtask("T2", ["missing"]).model_dump(mode="json")
    payload = {
        "action": "add_subtasks",
        "task_ids": ["T1"],
        "reason": "need more",
        "new_subtasks": [new],
    }
    registry = Registry([worker("manager")], Adapter(payload))
    with pytest.raises(Exception):
        await ManagerSupervisor(registry).review_cycle(
            "manager", plan(), {"objective": "g"}, tmp_path, completed_task_ids=set()
        )


@pytest.mark.asyncio
async def test_valid_accept_decision_returns_without_replan(tmp_path):
    payload = {"action": "accept", "task_ids": ["T1"], "reason": "verified"}
    registry = Registry([worker("manager")], Adapter(payload))
    decision, revised = await ManagerSupervisor(registry).review_cycle(
        "manager", plan(), {"objective": "g"}, tmp_path, completed_task_ids=set()
    )
    assert decision.action is ManagerAction.ACCEPT
    assert revised is None


@pytest.mark.asyncio
async def test_manager_context_contains_available_worker_summaries(tmp_path):
    adapter = Adapter({"action": "accept", "task_ids": ["T1"], "reason": "ok"})
    registry = Registry([worker("manager"), worker("other")], adapter)
    await ManagerSupervisor(registry).review_cycle(
        "manager",
        plan(),
        {"job_id": "job", "objective": "g"},
        tmp_path,
        completed_task_ids=set(),
    )
    objective = adapter.requests[0].objective
    assert "available_workers" in objective
    assert "other" in objective
