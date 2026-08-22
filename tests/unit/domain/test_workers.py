from pathlib import Path

import pytest
from pydantic import ValidationError

from orchestrator.domain.common import CostClass
from orchestrator.domain.workers import WorkerProfile, WorkerRequest


def test_worker_profile_rejects_capability_outside_unit_interval() -> None:
    with pytest.raises(ValidationError):
        WorkerProfile(
            id="codex/default",
            harness="codex",
            model="default",
            capabilities={"coding": 1.2},
            reliability=0.9,
            speed=0.5,
            cost_class=CostClass.INCLUDED,
            parallel_capacity=1,
            context_tokens=None,
            tools={"filesystem", "shell", "git"},
            can_manage=True,
            can_modify_repo=True,
            is_paid=False,
        )


def test_worker_request_requires_workspace_for_modifying_task(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        WorkerRequest(
            job_id="job-1",
            task_id="task-1",
            objective="change code",
            repo_path=tmp_path,
            workspace_path=None,
            read_only=False,
        )
