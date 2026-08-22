from __future__ import annotations

import hashlib
import re
from pathlib import Path

from pydantic import BaseModel

from orchestrator.workspace.git import GitClient


def _slug(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-._")
    return cleaned or "item"


class WorktreeLease(BaseModel):
    job_id: str
    task_id: str
    worker_id: str
    path: Path
    branch: str
    base_sha: str


class WorktreeManager:
    def __init__(self, git: GitClient, root: Path) -> None:
        self.git = git
        self.root = root.resolve()
        self._leases: dict[tuple[str, str, str], WorktreeLease] = {}
        self._owned_paths: set[Path] = set()
        self._source_repos: dict[tuple[str, str, str], Path] = {}

    def owns(self, path: Path) -> bool:
        return path.resolve() in self._owned_paths

    def lease_for(self, job_id: str, task_id: str, worker_id: str) -> WorktreeLease | None:
        return self._leases.get((job_id, task_id, worker_id))

    async def acquire(
        self,
        job_id: str,
        task_id: str,
        worker_id: str,
        source_repo: Path,
    ) -> WorktreeLease:
        key = (job_id, task_id, worker_id)
        existing = self._leases.get(key)
        if existing is not None:
            return existing

        base_sha = await self.git.head_sha(source_repo)
        job_slug = _slug(job_id)
        task_slug = _slug(task_id)
        worker_slug = _slug(worker_id)
        digest = hashlib.sha256(
            f"{job_id}\0{task_id}\0{worker_id}\0{base_sha}".encode()
        ).hexdigest()[:8]
        leaf = f"{task_slug}-{worker_slug}-{digest}"
        path = (self.root / job_slug / leaf).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("generated worktree escaped orchestrator root")
        branch = f"orchestrator/{job_slug}/{leaf}"

        await self.git.create_branch(source_repo, branch, base_sha)
        try:
            await self.git.create_worktree(source_repo, path, branch)
        except Exception:
            try:
                await self.git.delete_branch(source_repo, branch, force=True)
            except Exception:
                pass
            raise

        lease = WorktreeLease(
            job_id=job_id,
            task_id=task_id,
            worker_id=worker_id,
            path=path,
            branch=branch,
            base_sha=base_sha,
        )
        self._leases[key] = lease
        self._owned_paths.add(path)
        self._source_repos[key] = source_repo.resolve()
        return lease

    async def release(self, lease: WorktreeLease) -> None:
        path = lease.path.resolve()
        if path not in self._owned_paths:
            raise ValueError("worktree lease is not owned by this manager")
        key = (lease.job_id, lease.task_id, lease.worker_id)
        source_repo = self._source_repos.get(key)
        if source_repo is None:
            raise ValueError("worktree lease source repository is unknown")
        await self.git.remove_worktree(source_repo, path, owned_root=self.root)
        self._owned_paths.remove(path)
        self._leases.pop(key, None)
        self._source_repos.pop(key, None)
