from pathlib import Path

import pytest

from orchestrator.domain.tasks import SubtaskSpec, TaskPlan, TaskRisk
from orchestrator.integration.service import IntegrationService
from orchestrator.workspace.git import GitClient


async def init_repo(path: Path) -> tuple[GitClient, str]:
    path.mkdir()
    git = GitClient()
    await git._run(["git", "init", "-b", "main"], path)
    await git._run(["git", "config", "user.name", "Test"], path)
    await git._run(["git", "config", "user.email", "test@example.invalid"], path)
    (path / "base.txt").write_text("base\n")
    await git.commit_all(path, "initial")
    return git, await git.head_sha(path)


def task(task_id: str, deps: list[str] | None = None) -> SubtaskSpec:
    return SubtaskSpec(
        id=task_id,
        objective=f"complete {task_id}",
        capability_weights={"coding": 1.0},
        dependencies=deps or [],
        expected_outputs=[task_id],
        required_tools={"filesystem", "git"},
        write_paths=[f"{task_id}.txt"],
        read_only=False,
        risk=TaskRisk.LOW,
        verification=[],
    )


async def task_commit(
    git: GitClient,
    repo: Path,
    root: Path,
    branch: str,
    filename: str,
    value: str,
) -> str:
    base = await git.head_sha(repo)
    await git.create_branch(repo, branch, base)
    worktree = root / branch.replace("/", "-")
    await git.create_worktree(repo, worktree, branch)
    (worktree / filename).write_text(value)
    return await git.commit_all(worktree, branch)


@pytest.mark.asyncio
async def test_integrates_commits_in_topological_order_without_touching_source(tmp_path):
    repo = tmp_path / "repo"
    git, base = await init_repo(repo)
    before_branch = await git.current_branch(repo)
    before_head = await git.head_sha(repo)
    commit_one = await task_commit(git, repo, tmp_path, "task-1", "T1.txt", "one\n")
    commit_two = await task_commit(git, repo, tmp_path, "task-2", "T2.txt", "two\n")
    plan = TaskPlan(
        goal="integrate",
        confidence=1.0,
        subtasks=[task("T1"), task("T2", ["T1"])],
        final_expected_outputs=["done"],
    )
    service = IntegrationService(git, integration_root=tmp_path / "integration")

    result = await service.integrate(
        "job-1",
        repo,
        base,
        plan,
        {"T2": commit_two, "T1": commit_one},
    )

    assert result.status == "succeeded"
    assert result.integrated_task_ids == ["T1", "T2"]
    assert result.head_sha is not None
    workspace = service.workspace_for("job-1")
    assert (workspace / "T1.txt").read_text() == "one\n"
    assert (workspace / "T2.txt").read_text() == "two\n"
    assert await git.current_branch(repo) == before_branch
    assert await git.head_sha(repo) == before_head


@pytest.mark.asyncio
async def test_conflict_is_aborted_and_recorded(tmp_path):
    repo = tmp_path / "repo"
    git, _base = await init_repo(repo)
    (repo / "same.txt").write_text("base\n")
    await git.commit_all(repo, "add same")
    base = await git.head_sha(repo)

    await git.create_branch(repo, "left", base)
    left = tmp_path / "left"
    await git.create_worktree(repo, left, "left")
    (left / "same.txt").write_text("left\n")
    left_sha = await git.commit_all(left, "left")

    await git.create_branch(repo, "right", base)
    right = tmp_path / "right"
    await git.create_worktree(repo, right, "right")
    (right / "same.txt").write_text("right\n")
    right_sha = await git.commit_all(right, "right")

    plan = TaskPlan(
        goal="conflict",
        confidence=1.0,
        subtasks=[task("T1"), task("T2", ["T1"])],
        final_expected_outputs=["done"],
    )
    service = IntegrationService(git, integration_root=tmp_path / "integration")

    result = await service.integrate(
        "job-conflict",
        repo,
        base,
        plan,
        {"T1": left_sha, "T2": right_sha},
    )

    assert result.status == "conflict"
    assert result.integrated_task_ids == ["T1"]
    assert result.conflicting_task_ids == ["T2"]
    assert await git.status_porcelain(service.workspace_for("job-conflict")) == ""
