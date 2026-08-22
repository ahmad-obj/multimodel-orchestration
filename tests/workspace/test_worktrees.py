from pathlib import Path

import pytest

from orchestrator.workspace.git import GitClient
from orchestrator.workspace.worktrees import WorktreeManager


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
async def test_worktree_manager_uses_owned_hashed_path_and_releases(tmp_path):
    repo = tmp_path / "repo"
    git = await init_repo(repo)
    root = tmp_path / "data" / "worktrees"
    manager = WorktreeManager(git, root)

    lease = await manager.acquire("job-42", "T3", "codex/default", repo)

    assert lease.path.parent == root / "job-42"
    assert lease.path.name.startswith("T3-codex-default-")
    assert lease.branch.startswith("orchestrator/job-42/T3-codex-default-")
    assert lease.path.exists()
    assert manager.owns(lease.path)

    await manager.release(lease)
    assert not lease.path.exists()
    assert not manager.owns(lease.path)


@pytest.mark.asyncio
async def test_release_refuses_unowned_lease(tmp_path):
    repo = tmp_path / "repo"
    git = await init_repo(repo)
    manager = WorktreeManager(git, tmp_path / "owned")
    other = WorktreeManager(git, tmp_path / "other")
    lease = await other.acquire("job", "T", "worker", repo)

    with pytest.raises(ValueError, match="not owned"):
        await manager.release(lease)
