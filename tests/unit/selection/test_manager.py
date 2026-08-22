from pathlib import Path

from orchestrator.domain.common import CostClass, WorkerStatus
from orchestrator.domain.tasks import TaskAnalysis, TaskComplexity, TaskRisk
from orchestrator.domain.workers import WorkerDescriptor, WorkerProfile
from orchestrator.selection.manager import ManagerSelector


def w(worker_id, can_manage, score):
    p=WorkerProfile(id=worker_id,harness="x",model="m",capabilities={"reasoning":score,"coding":score},reliability=.9,speed=.7,cost_class=CostClass.FREE,parallel_capacity=1,tools={"filesystem"},can_manage=can_manage,is_paid=False)
    return WorkerDescriptor(profile=p,executable_path=Path("/fake"),status=WorkerStatus.AVAILABLE)


def analysis():
    return TaskAnalysis(task_type="coding",complexity=TaskComplexity.HIGH,risk=TaskRisk.MEDIUM,confidence=.9,capability_weights={"reasoning":.9,"coding":.8},required_tools={"filesystem"},constraints=[],expected_outputs=["done"],parallelizable_hint=True)


def test_non_manager_worker_is_never_ranked() -> None:
    selection=ManagerSelector().rank(analysis(),[w("strong",False,.99),w("manager",True,.75)])
    assert [r.worker.profile.id for r in selection.ranked] == ["manager"]


def test_close_manager_scores_need_tiebreak() -> None:
    selection=ManagerSelector().rank(analysis(),[w("a",True,.85),w("b",True,.84)])
    assert selection.needs_tiebreak is True
