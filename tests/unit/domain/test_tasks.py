import pytest
from pydantic import ValidationError

from orchestrator.domain.tasks import TaskAnalysis, TaskComplexity, TaskRisk


def test_task_analysis_rejects_invalid_weight() -> None:
    with pytest.raises(ValidationError):
        TaskAnalysis(
            task_type="debugging",
            complexity=TaskComplexity.HIGH,
            risk=TaskRisk.MEDIUM,
            confidence=0.8,
            capability_weights={"debugging": 1.5},
            required_tools={"filesystem"},
            repository_requirements=["git repository"],
            context_requirements=["test failure output"],
            required_context_tokens=None,
            constraints=[],
            expected_outputs=["passing tests"],
            parallelizable_hint=True,
        )


def test_task_analysis_requires_positive_capability() -> None:
    with pytest.raises(ValidationError):
        TaskAnalysis(
            task_type="inspection",
            complexity=TaskComplexity.LOW,
            risk=TaskRisk.LOW,
            confidence=0.9,
            capability_weights={"simple_tasks": 0.0},
            required_tools=set(),
            constraints=[],
            expected_outputs=["files"],
            parallelizable_hint=False,
        )
