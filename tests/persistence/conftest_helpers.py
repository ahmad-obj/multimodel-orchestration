from __future__ import annotations

from pathlib import Path

from orchestrator.domain.common import CostClass, WorkerStatus
from orchestrator.domain.tasks import SubtaskSpec, TaskPlan, TaskRisk
from orchestrator.domain.workers import WorkerDescriptor, WorkerProfile


def make_profile(worker_id: str = "codex-main") -> WorkerProfile:
    return WorkerProfile(
        id=worker_id,
        harness="codex",
        model="gpt-5-codex",
        capabilities={"coding": 0.9, "debugging": 0.8},
        reliability=0.95,
        speed=0.7,
        cost_class=CostClass.INCLUDED,
        parallel_capacity=2,
        context_tokens=200_000,
        tools={"shell", "filesystem"},
        can_manage=True,
        can_modify_repo=True,
    )


def make_descriptor(worker_id: str = "codex-main") -> WorkerDescriptor:
    return WorkerDescriptor(
        profile=make_profile(worker_id),
        executable_path=Path("/usr/bin/codex"),
        status=WorkerStatus.AVAILABLE,
        health_reason=None,
    )


def make_plan() -> TaskPlan:
    return TaskPlan(
        goal="Implement feature X",
        confidence=0.85,
        subtasks=[
            SubtaskSpec(
                id="inspect",
                objective="Inspect the repo",
                capability_weights={"repo_navigation": 0.9},
                dependencies=[],
                expected_outputs=["repo structure"],
                required_tools={"filesystem"},
                context_requirements=["repository tree"],
                write_paths=[],
                read_only=True,
                risk=TaskRisk.LOW,
                verification=["manager_review"],
            ),
            SubtaskSpec(
                id="implement",
                objective="Implement the feature",
                capability_weights={"coding": 0.9},
                dependencies=["inspect"],
                expected_outputs=["source files"],
                required_tools={"shell"},
                context_requirements=["repo structure"],
                write_paths=["src/"],
                read_only=False,
                risk=TaskRisk.MEDIUM,
                verification=["tests_pass"],
            ),
        ],
        final_expected_outputs=["feature X complete"],
    )
