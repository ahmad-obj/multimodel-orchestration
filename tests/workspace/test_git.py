from pathlib import Path

import pytest

from orchestrator.workspace.git import GitClient, GitCommandError


async def init_repo(path: Path) -> None:
    path.mkdir()
    git = GitClient()
    await git._run(["git", "init"], path)
    await git._run(["git", "config", "user.name", "Orchestrator Test"], path)
    await git._run(["git", "config", "user.email", "orchestrator@test.invalid"], path)
    (path / "README.md").write_text("# Test\n")
    await git.commit_all(path, "initial")


@pytest.mark.asyncio
async def test_git_repository_and_worktree_lifecycle(tmp_path):
    repo = tmp_path / "repo"
    await init_repo(repo)
    git = GitClient()

    assert await git.is_repository(repo)
    assert await git.status_porcelain(repo) == ""
    base = await git.head_sha(repo)
    assert len(base) == 40

    branch = "orchestrator/job/T1-worker"
    await git.create_branch(repo, branch, base)
    worktree = tmp_path / "wt"
    await git.create_worktree(repo, worktree, branch)
    (worktree / "result.txt").write_text("done\n")
    sha = await git.commit_all(worktree, "task result")

    assert len(sha) == 40
    assert (await git.head_sha(worktree)) == sha
    assert await git.changed_files(worktree, base) == ["result.txt"]
    assert await git.status_porcelain(repo) == ""
    await git.remove_worktree(repo, worktree)
    assert not worktree.exists()


@pytest.mark.asyncio
async def test_changed_files_are_derived_from_git_history(tmp_path):
    repo = tmp_path / "repo"
    await init_repo(repo)
    git = GitClient()
    base = await git.head_sha(repo)
    (repo / "alpha.py").write_text("a = 1\n")
    (repo / "nested").mkdir()
    (repo / "nested" / "beta.py").write_text("b = 2\n")
    await git.commit_all(repo, "add files")

    assert await git.changed_files(repo, base) == ["alpha.py", "nested/beta.py"]


@pytest.mark.asyncio
async def test_cherry_pick_conflict_can_be_aborted(tmp_path):
    repo = tmp_path / "repo"
    await init_repo(repo)
    git = GitClient()
    base = await git.head_sha(repo)

    await git.create_branch(repo, "left", base)
    left = tmp_path / "left"
    await git.create_worktree(repo, left, "left")
    (left / "README.md").write_text("left\n")
    left_sha = await git.commit_all(left, "left")

    (repo / "README.md").write_text("main\n")
    await git.commit_all(repo, "main")

    with pytest.raises(GitCommandError):
        await git.cherry_pick(repo, left_sha)
    await git.abort_cherry_pick(repo)
    assert await git.status_porcelain(repo) == ""
