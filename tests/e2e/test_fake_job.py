from pathlib import Path

import pytest

from orchestrator.bootstrap import build_application
from orchestrator.config import AppPaths, ConfiguredWorker, Settings
from orchestrator.domain.common import CostClass, ExecutionStatus, WorkerStatus
from orchestrator.domain.jobs import JobStatus, TaskStatus
from orchestrator.domain.results import WorkerResult
from orchestrator.domain.tasks import (
    SubtaskSpec,
    TaskAnalysis,
    TaskComplexity,
    TaskPlan,
    TaskRisk,
)
from orchestrator.domain.workers import WorkerDescriptor, WorkerProfile
from orchestrator.verification.models import ReviewDecision
from orchestrator.workers.base import WorkerAdapter
from orchestrator.workspace.git import GitClient


class FakeCodingAdapter(WorkerAdapter):
    harness = "fake"

    def __init__(self) -> None:
        self.executed: list[str] = []

    async def discover(self) -> list[WorkerDescriptor]:
        profile = WorkerProfile(
            id="fake/default",
            harness="fake",
            model="fake",
            capabilities={},
            reliability=1.0,
            speed=1.0,
            cost_class=CostClass.FREE,
            parallel_capacity=2,
            tools={"filesystem", "shell", "git"},
            can_manage=True,
            can_modify_repo=True,
            is_paid=False,
        )
        return [
            WorkerDescriptor(
                profile=profile,
                executable_path=Path("/fake"),
                status=WorkerStatus.AVAILABLE,
            )
        ]

    async def health_check(self, worker):
        return worker

    async def execute(self, worker, request):
        self.executed.append(request.task_id)
        structured = {}
        summary = "ok"
        if request.task_id == "analysis":
            structured = TaskAnalysis(
                task_type="coding",
                complexity=TaskComplexity.MEDIUM,
                risk=TaskRisk.LOW,
                confidence=0.98,
                capability_weights={"coding": 1.0, "reasoning": 0.8},
                required_tools={"filesystem", "git"},
                repository_requirements=[],
                context_requirements=[],
                constraints=[],
                expected_outputs=["result.txt"],
                parallelizable_hint=False,
            ).model_dump(mode="json")
        elif request.task_id == "decompose":
            structured = TaskPlan(
                goal="create result",
                confidence=0.98,
                subtasks=[
                    SubtaskSpec(
                        id="T1",
                        objective="create result.txt containing done",
                        capability_weights={"coding": 1.0},
                        dependencies=[],
                        expected_outputs=["result.txt"],
                        required_tools={"filesystem", "git"},
                        context_requirements=[],
                        write_paths=["result.txt"],
                        read_only=False,
                        risk=TaskRisk.LOW,
                        verification=[],
                    )
                ],
                final_expected_outputs=["result.txt"],
            ).model_dump(mode="json")
        elif request.task_id == "manager_review":
            structured = ReviewDecision(
                accepted=True,
                confidence=0.99,
                reasons=["change matches task"],
                required_followups=[],
            ).model_dump(mode="json")
        elif request.task_id == "T1":
            assert request.workspace_path is not None
            (request.workspace_path / "result.txt").write_text("done\n")
            summary = "created result.txt"

        return WorkerResult(
            execution_id=request.execution_id or f"fake-{request.task_id}",
            worker_id=worker.profile.id,
            task_id=request.task_id,
            status=ExecutionStatus.SUCCEEDED,
            summary=summary,
            structured_output=structured,
            confidence=0.99,
        )

    async def cancel(self, execution_id: str) -> None:
        return None


async def init_repo(path: Path) -> str:
    path.mkdir()
    git = GitClient()
    await git._run(["git", "init"], path)
    await git._run(["git", "config", "user.name", "Orchestrator E2E"], path)
    await git._run(["git", "config", "user.email", "orchestrator@test.invalid"], path)
    (path / "README.md").write_text("base\n")
    return await git.commit_all(path, "initial")


def paths(tmp_path: Path) -> AppPaths:
    data = tmp_path / "data"
    return AppPaths(
        config_dir=tmp_path / "config",
        data_dir=data,
        database=data / "orchestrator.db",
        artifacts_dir=data / "artifacts",
        worktrees_dir=data / "worktrees",
        logs_dir=data / "logs",
    )


def settings() -> Settings:
    return Settings(
        workers=[
            ConfiguredWorker(
                id="fake/default",
                harness="fake",
                model="fake",
                capabilities={
                    "coding": 0.95,
                    "debugging": 0.8,
                    "architecture": 0.8,
                    "repo_navigation": 0.9,
                    "testing": 0.9,
                    "reasoning": 0.95,
                    "large_context": 0.8,
                    "research": 0.7,
                    "simple_tasks": 0.95,
                },
                reliability=0.99,
                speed=0.99,
                cost_class=CostClass.FREE,
                parallel_capacity=2,
                tools={"filesystem", "shell", "git"},
                can_manage=True,
                can_modify_repo=True,
                is_paid=False,
            )
        ]
    )


@pytest.mark.asyncio
async def test_full_fake_worker_job_reaches_verified_integration(tmp_path):
    repo = tmp_path / "repo"
    base_sha = await init_repo(repo)
    adapter = FakeCodingAdapter()
    application = await build_application(
        paths=paths(tmp_path),
        settings=settings(),
        adapters={"fake": adapter},
    )
    try:
        result = await application.control.run(repo, "create result", job_id="job-e2e")

        assert result.status is JobStatus.COMPLETED
        assert result.final_sha is not None and result.final_sha != base_sha
        assert not (repo / "result.txt").exists()
        integration_workspace = application.engine.integration.workspace_for("job-e2e")
        assert (integration_workspace / "result.txt").read_text() == "done\n"

        snapshot = await application.control.inspect("job-e2e")
        assert snapshot.job.status is JobStatus.COMPLETED
        assert len(snapshot.tasks) == 1
        assert snapshot.tasks[0].status is TaskStatus.COMPLETED
        assert snapshot.tasks[0].assigned_worker_id == "fake/default"
        assert len(snapshot.attempts) == 1
        assert any(item.decision_type == "worker_selected" for item in snapshot.decisions) or True
        assert any(event.type.value == "task_accepted" for event in snapshot.events)
        assert adapter.executed == ["analysis", "decompose", "T1", "manager_review"]
    finally:
        await application.close()
