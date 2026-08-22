from orchestrator.capabilities.scoring import WorkerScorer
from orchestrator.domain.common import CostClass
from orchestrator.domain.tasks import TaskAnalysis, TaskComplexity, TaskRisk
from orchestrator.domain.workers import WorkerProfile


def make_analysis(weights):
    return TaskAnalysis(
        task_type="repository_inspection", complexity=TaskComplexity.LOW, risk=TaskRisk.LOW,
        confidence=0.9, capability_weights=weights, required_tools={"filesystem"},
        constraints=[], expected_outputs=["file list"], parallelizable_hint=False,
    )


def test_easy_file_task_prefers_free_adequate_worker() -> None:
    codex = WorkerProfile(
        id="codex/default", harness="codex", model="default",
        capabilities={"repo_navigation":0.95,"simple_tasks":0.95}, reliability=0.82, speed=0.45,
        cost_class=CostClass.INCLUDED, parallel_capacity=1, tools={"filesystem"},
        can_manage=True, can_modify_repo=True, is_paid=False,
    )
    flash = WorkerProfile(
        id="gemini/flash", harness="gemini", model="flash",
        capabilities={"repo_navigation":0.85,"simple_tasks":0.9}, reliability=0.85, speed=0.95,
        cost_class=CostClass.FREE, parallel_capacity=2, tools={"filesystem"},
        can_manage=True, can_modify_repo=True, is_paid=False,
    )
    scorer = WorkerScorer()
    scores = [scorer.score(p, make_analysis({"repo_navigation":0.9,"simple_tasks":0.8})) for p in [codex, flash]]
    assert max(scores, key=lambda s: s.total).worker_id == "gemini/flash"


def test_required_high_weight_dimension_has_floor() -> None:
    weak = WorkerProfile(
        id="weak", harness="x", model="x", capabilities={"debugging":0.4}, reliability=1, speed=1,
        cost_class=CostClass.FREE, parallel_capacity=1, tools={"filesystem"}, is_paid=False,
    )
    score = WorkerScorer().score(weak, make_analysis({"debugging":0.9}))
    assert score.adequate is False
