from pathlib import Path

from orchestrator.domain.common import CostClass, WorkerStatus
from orchestrator.domain.tasks import SubtaskSpec, TaskAnalysis, TaskComplexity, TaskPlan, TaskRisk
from orchestrator.domain.workers import WorkerDescriptor, WorkerProfile
from orchestrator.planning.service import PlanningService


def worker():
    p=WorkerProfile(id="mgr",harness="x",model="m",capabilities={"reasoning":.9,"coding":.9,"simple_tasks":.9},reliability=.9,speed=.8,cost_class=CostClass.FREE,parallel_capacity=1,tools={"filesystem","git"},can_manage=True,can_modify_repo=True,is_paid=False)
    return WorkerDescriptor(profile=p,executable_path=Path("/fake"),status=WorkerStatus.AVAILABLE)


class Registry:
    adapters={"x":object()}
    def available(self): return [worker()]


class Analyzer:
    async def analyze(self,*args): return TaskAnalysis(task_type="coding",complexity=TaskComplexity.HIGH,risk=TaskRisk.MEDIUM,confidence=.9,capability_weights={"reasoning":.9,"coding":.9},required_tools={"filesystem"},constraints=[],expected_outputs=["fix"],parallelizable_hint=True)


class Decomposer:
    def __init__(self): self.calls=0
    async def create_plan(self,*args,**kwargs):
        self.calls+=1
        if self.calls==1:
            return TaskPlan(goal="g",confidence=.9,subtasks=[SubtaskSpec(id="a",objective="a",capability_weights={"reasoning":.8},dependencies=["b"],expected_outputs=["a"],required_tools={"filesystem"},read_only=True,risk=TaskRisk.LOW,verification=["manager_review"]),SubtaskSpec(id="b",objective="b",capability_weights={"reasoning":.8},dependencies=["a"],expected_outputs=["b"],required_tools={"filesystem"},read_only=True,risk=TaskRisk.LOW,verification=["manager_review"])],final_expected_outputs=["done"])
        return TaskPlan(goal="g",confidence=.9,subtasks=[SubtaskSpec(id="a",objective="a",capability_weights={"reasoning":.8},dependencies=[],expected_outputs=["a"],required_tools={"filesystem"},read_only=True,risk=TaskRisk.LOW,verification=["manager_review"])],final_expected_outputs=["done"])


async def test_planning_service_repairs_invalid_plan() -> None:
    decomposer=Decomposer()
    service=PlanningService(analyzer=Analyzer(),decomposer=decomposer)
    planned=await service.plan("fix",object(),Registry())
    assert planned.plan_attempts == 2
    assert decomposer.calls == 2
    assert planned.manager_worker_id == "mgr"
