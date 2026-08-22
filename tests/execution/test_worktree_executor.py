from pathlib import Path

import pytest

from orchestrator.domain.common import CostClass, ExecutionStatus, WorkerStatus
from orchestrator.domain.results import WorkerResult
from orchestrator.domain.tasks import SubtaskSpec, TaskRisk
from orchestrator.domain.workers import WorkerDescriptor, WorkerProfile
from orchestrator.execution.executor import TaskExecutor
from orchestrator.scheduling.scheduler import Assignment
from orchestrator.workspace.git import GitClient
from orchestrator.workspace.worktrees import WorktreeManager


class FakeRegistry:
    def __init__(self, descriptor, adapter):
        self.descriptor = descriptor
        self.adapters = {descriptor.profile.harness: adapter}

    def get(self, worker_id):
        assert worker_id == self.descriptor.profile.id
        return self.descriptor


class ModifyingAdapter:
    async def execute(self, worker, request):
        assert request.workspace_path != request.repo_path
        (request.workspace_path / "result.txt").write_text("done\n")
        return WorkerResult(
            execution_id="exec-1",
            worker_id=worker.profile.id,
            task_id=request.task_id,
            status=ExecutionStatus.SUCCEEDED,
            summary="done",
            changed_files=["result.txt"],
            confidence=0.9,
        )


async def init_repo(path: Path) -> GitClient:
    path.mkdir()
    git = GitClient()
    await git._run(["git", "init"], path)
    await git._run(["git", "config", "user.name", "Test"], path)
    await git._run(["git", "config", "user.email", "test@example.invalid"], path)
    (path / "README.md").write_text("base\n")
    await git.commit_all(path, "initial")
    return git


@pytest.mark.asyncio
async def test_modifying_assignment_uses_worktree_and_commits(tmp_path):
    repo = tmp_path / "repo"
    git = await init_repo(repo)
    profile = WorkerProfile(
        id="codex/default",
        harness="fake",
        model="x",
        capabilities={"coding": 1.0},
        reliability=1.0,
        speed=1.0,
        cost_class=CostClass.INCLUDED,
        parallel_capacity=1,
        tools={"filesystem", "shell", "git"},
        can_modify_repo=True,
    )
    descriptor = WorkerDescriptor(
        profile=profile,
        executable_path=Path("/fake"),
        status=WorkerStatus.AVAILABLE,
    )
    registry = FakeRegistry(descriptor, ModifyingAdapter())
    manager = WorktreeManager(git, tmp_path / "data" / "worktrees")
    executor = TaskExecutor(registry, worktree_manager=manager, git_client=git)
    subtask = SubtaskSpec(
        id="T1",
        objective="write result",
        capability_weights={"coding": 1.0},
        expected_outputs=["result"],
        read_only=False,
        risk=TaskRisk.LOW,
        verification=[],
    )
    assignment = Assignment(
        job_id="job-1",
        subtask=subtask,
        worker_id=profile.id,
        source_repo=repo,
    )

    result = await executor.execute_assignment(assignment)

    assert not (repo / "result.txt").exists()
    assert result.local_commit is not None
    lease = manager.lease_for("job-1", "T1", profile.id)
    assert lease is not None
    assert (lease.path / "result.txt").read_text() == "done\n"
    assert await git.head_sha(lease.path) == result.local_commit
