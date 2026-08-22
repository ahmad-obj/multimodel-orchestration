from __future__ import annotations

import asyncio
from pathlib import Path

from pydantic import BaseModel


class GitCommandError(RuntimeError):
    def __init__(self, command: list[str], returncode: int, stdout: str, stderr: str) -> None:
        self.command = command
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        super().__init__(f"git command failed ({returncode}): {' '.join(command)}\n{stderr.strip()}")


class GitCommandResult(BaseModel):
    stdout: str
    stderr: str
    returncode: int


class GitClient:
    async def _run(self, argv: list[str], cwd: Path, *, check: bool = True) -> GitCommandResult:
        process = await asyncio.create_subprocess_exec(
            *argv,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_b, stderr_b = await process.communicate()
        result = GitCommandResult(
            stdout=stdout_b.decode(errors="replace"),
            stderr=stderr_b.decode(errors="replace"),
            returncode=process.returncode or 0,
        )
        if check and result.returncode != 0:
            raise GitCommandError(argv, result.returncode, result.stdout, result.stderr)
        return result

    async def is_repository(self, repo: Path) -> bool:
        result = await self._run(["git", "rev-parse", "--is-inside-work-tree"], repo, check=False)
        return result.returncode == 0 and result.stdout.strip() == "true"

    async def current_branch(self, repo: Path) -> str:
        result = await self._run(["git", "branch", "--show-current"], repo)
        return result.stdout.strip()

    async def head_sha(self, repo: Path) -> str:
        result = await self._run(["git", "rev-parse", "HEAD"], repo)
        return result.stdout.strip()

    async def status_porcelain(self, repo: Path) -> str:
        result = await self._run(["git", "status", "--porcelain"], repo)
        return result.stdout.strip()

    async def changed_files(self, repo: Path, base_sha: str) -> list[str]:
        result = await self._run(
            ["git", "diff", "--name-only", "--diff-filter=ACMRTUXB", base_sha, "HEAD"],
            repo,
        )
        return sorted({line.strip() for line in result.stdout.splitlines() if line.strip()})

    async def create_branch(self, repo: Path, branch: str, start_point: str) -> None:
        await self._run(["git", "branch", branch, start_point], repo)

    async def create_worktree(self, repo: Path, path: Path, branch: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        await self._run(["git", "worktree", "add", str(path), branch], repo)

    async def delete_branch(self, repo: Path, branch: str, *, force: bool = False) -> None:
        flag = "-D" if force else "-d"
        await self._run(["git", "branch", flag, branch], repo)

    async def remove_worktree(
        self,
        repo: Path,
        path: Path,
        *,
        owned_root: Path | None = None,
    ) -> None:
        resolved = path.resolve()
        if owned_root is not None and not resolved.is_relative_to(owned_root.resolve()):
            raise ValueError("refusing to remove worktree outside orchestrator-owned root")
        await self._run(["git", "worktree", "remove", "--force", str(path)], repo)

    async def commit_all(self, worktree: Path, message: str) -> str:
        await self._run(["git", "add", "-A"], worktree)
        await self._run(["git", "commit", "-m", message], worktree)
        return await self.head_sha(worktree)

    async def cherry_pick(self, repo: Path, sha: str) -> None:
        await self._run(["git", "cherry-pick", sha], repo)

    async def abort_cherry_pick(self, repo: Path) -> None:
        result = await self._run(["git", "cherry-pick", "--abort"], repo, check=False)
        if result.returncode != 0 and "no cherry-pick" not in result.stderr.lower():
            raise GitCommandError(
                ["git", "cherry-pick", "--abort"],
                result.returncode,
                result.stdout,
                result.stderr,
            )
