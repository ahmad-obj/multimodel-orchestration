import pytest
from pydantic import ValidationError

from orchestrator.domain.tasks import SubtaskSpec, TaskRisk


def test_subtask_requires_expected_output() -> None:
    with pytest.raises(ValidationError):
        SubtaskSpec(
            id="inspect", objective="inspect repo", capability_weights={"repo_navigation": 0.8},
            dependencies=[], expected_outputs=[], required_tools={"filesystem"},
            context_requirements=["repository tree"], write_paths=[], read_only=True,
            risk=TaskRisk.LOW, verification=["manager_review"],
        )
