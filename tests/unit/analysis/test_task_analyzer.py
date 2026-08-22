from pathlib import Path

from orchestrator.analysis.repository import RepositorySummary
from orchestrator.analysis.task_analyzer import TaskAnalyzer
from orchestrator.domain.common import CostClass, ExecutionStatus, WorkerStatus
from orchestrator.domain.results import WorkerResult
from orchestrator.domain.tasks import TaskAnalysis, TaskComplexity, TaskRisk
from orchestrator.domain.workers import WorkerDescriptor, WorkerProfile


class FakeRegistry:
    def __init__(self, workers): self._workers=workers; self.adapters={"gemini":object(),"codex":object()}
    def available(self): return self._workers


class FakeExecutor:
    def __init__(self): self.last_worker=None
    async def __call__(self, adapter, worker, request, output_model):
        self.last_worker=worker
        analysis=TaskAnalysis(
            task_type="repository_inspection", complexity=TaskComplexity.LOW, risk=TaskRisk.LOW,
            confidence=.9, capability_weights={"repo_navigation":.9,"simple_tasks":.8},
            required_tools={"filesystem"}, constraints=[], expected_outputs=["files"], parallelizable_hint=False,
        )
        result=WorkerResult(execution_id="e",worker_id=worker.profile.id,task_id=request.task_id,status=ExecutionStatus.SUCCEEDED,summary="ok",structured_output=analysis.model_dump(mode="json"))
        return result, analysis


def descriptor(worker_id,harness,cost,paid=False):
    p=WorkerProfile(id=worker_id,harness=harness,model="m",capabilities={"reasoning":.8,"simple_tasks":.9,"repo_navigation":.9},reliability=.8,speed=.8,cost_class=cost,parallel_capacity=1,tools={"filesystem"},can_manage=True,is_paid=paid)
    return WorkerDescriptor(profile=p,executable_path=Path("/fake"),status=WorkerStatus.AVAILABLE)


async def test_analyzer_never_selects_paid_worker(tmp_path) -> None:
    free=descriptor("gemini/flash","gemini",CostClass.FREE)
    paid=descriptor("codex/paid","codex",CostClass.PAID,True)
    executor=FakeExecutor()
    summary=RepositorySummary(root=tmp_path,branch="main",head_sha="abc",dirty=False,top_level_entries=[],manifests=[],language_hints=["python"],test_hints=[])
    result=await TaskAnalyzer(FakeRegistry([paid,free]),executor).analyze("find files",summary)
    assert executor.last_worker.profile.is_paid is False
    assert result.task_type == "repository_inspection"
