import asyncio
import time
from pathlib import Path

from orchestrator.domain.common import CostClass, ExecutionStatus, WorkerStatus
from orchestrator.domain.results import WorkerResult
from orchestrator.domain.tasks import SubtaskSpec, TaskRisk
from orchestrator.domain.workers import WorkerDescriptor, WorkerProfile
from orchestrator.execution.executor import TaskExecutor
from orchestrator.scheduling.scheduler import Assignment


class FakeAdapter:
    def __init__(self,delay): self.delay=delay
    async def execute(self,worker,request):
        await asyncio.sleep(self.delay)
        return WorkerResult(execution_id=f"e-{request.task_id}",worker_id=worker.profile.id,task_id=request.task_id,status=ExecutionStatus.SUCCEEDED,summary="ok")


class Registry:
    def __init__(self,capacity):
        p=WorkerProfile(id="w",harness="x",model="m",capabilities={"simple_tasks":.9},reliability=.9,speed=.9,cost_class=CostClass.FREE,parallel_capacity=capacity,tools={"filesystem"},is_paid=False)
        self.worker=WorkerDescriptor(profile=p,executable_path=Path("/fake"),status=WorkerStatus.AVAILABLE)
        self.adapters={"x":FakeAdapter(.20)}
    def get(self,worker_id): return self.worker


def assignment(task_id,tmp_path):
    sub=SubtaskSpec(id=task_id,objective=task_id,capability_weights={"simple_tasks":.8},expected_outputs=["o"],required_tools={"filesystem"},read_only=True,risk=TaskRisk.LOW,verification=["manager_review"])
    return Assignment(job_id="j",subtask=sub,worker_id="w",source_repo=tmp_path)


async def test_executor_runs_independent_tasks_concurrently(tmp_path):
    ex=TaskExecutor(Registry(2))
    started=time.perf_counter(); results=await ex.execute_many([assignment("T1",tmp_path),assignment("T2",tmp_path)]); elapsed=time.perf_counter()-started
    assert len(results)==2
    assert elapsed < .35


async def test_executor_respects_worker_parallel_capacity(tmp_path):
    ex=TaskExecutor(Registry(1))
    started=time.perf_counter(); await ex.execute_many([assignment("T1",tmp_path),assignment("T2",tmp_path)]); elapsed=time.perf_counter()-started
    assert elapsed >= .38
