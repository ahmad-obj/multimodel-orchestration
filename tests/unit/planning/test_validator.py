import pytest

from orchestrator.domain.tasks import SubtaskSpec, TaskPlan, TaskRisk
from orchestrator.planning.validator import PlanValidationError, PlanValidator


def s(id, deps=(), read_only=True, write_paths=(), group=None, tools=None):
    return SubtaskSpec(
        id=id,
        objective=id,
        capability_weights={"reasoning": 0.7},
        dependencies=list(deps),
        expected_outputs=["out"],
        required_tools=set(tools or {"filesystem"}),
        context_requirements=[],
        write_paths=list(write_paths),
        read_only=read_only,
        risk=TaskRisk.LOW,
        verification=["manager_review"],
        preferred_parallel_group=group,
    )


def plan(*tasks):
    return TaskPlan(goal="g", confidence=0.9, subtasks=list(tasks), final_expected_outputs=["done"])


@pytest.mark.parametrize(
    ("p", "code"),
    [
        (plan(s("T1", ["T2"]), s("T2", ["T1"])), "cycle"),
        (plan(s("T1"), s("T2", ["MISSING"])), "missing_dependency"),
        (plan(s("T1"), s("T1")), "duplicate_task_id"),
        (plan(s("T1", read_only=False, tools={"filesystem"})), "invalid_modification_requirements"),
        (
            plan(
                s(
                    "T1",
                    read_only=False,
                    write_paths=["src/app.py"],
                    group="g",
                    tools={"filesystem", "git"},
                ),
                s(
                    "T2",
                    read_only=False,
                    write_paths=["src/app.py"],
                    group="g",
                    tools={"filesystem", "git"},
                ),
            ),
            "conflicting_parallel_writes",
        ),
    ],
)
def test_invalid_plans(p, code) -> None:
    with pytest.raises(PlanValidationError) as exc:
        PlanValidator().validate(p)
    assert code in {e.code for e in exc.value.errors}
