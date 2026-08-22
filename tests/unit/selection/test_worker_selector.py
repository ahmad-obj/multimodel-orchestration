from pathlib import Path

from orchestrator.domain.common import CostClass, WorkerStatus
from orchestrator.domain.tasks import TaskAnalysis, TaskComplexity, TaskRisk
from orchestrator.domain.workers import WorkerDescriptor, WorkerProfile
from orchestrator.selection.worker import WorkerSelector


def d(worker_id,cost,nav,simple,reliability,speed):
    p=WorkerProfile(id=worker_id,harness="x",model="m",capabilities={"repo_navigation":nav,"simple_tasks":simple},reliability=reliability,speed=speed,cost_class=cost,parallel_capacity=1,tools={"filesystem"},is_paid=False)
    return WorkerDescriptor(profile=p,executable_path=Path("/fake"),status=WorkerStatus.AVAILABLE)


def test_selector_returns_free_adequate_worker() -> None:
    a=TaskAnalysis(task_type="repo",complexity=TaskComplexity.LOW,risk=TaskRisk.LOW,confidence=.9,capability_weights={"repo_navigation":.9,"simple_tasks":.8},required_tools={"filesystem"},constraints=[],expected_outputs=["files"],parallelizable_hint=False)
    selected=WorkerSelector().select(a,[d("codex",CostClass.INCLUDED,.95,.95,.82,.45),d("flash",CostClass.FREE,.85,.9,.85,.95)],requires_write=False)
    assert selected.worker.profile.id == "flash"
    assert selected.scores[0].worker_id == "flash"
