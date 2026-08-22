from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from orchestrator.domain.tasks import TaskPlan
from orchestrator.planning.validator import PlanValidator
from orchestrator.verification.models import VerificationResult
from orchestrator.workspace.git import GitClient, GitCommandError


def _slug(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-._")
    return cleaned or "job"


class IntegrationResult(BaseModel):
    status: Literal["succeeded", "conflict", "verification_failed"]
    branch: str
    head_sha: str | None = None
    integrated_task_ids: list[str] = Field(default_factory=list)
    conflicting_task_ids: list[str] = Field(default_factory=list)
    verification: VerificationResult | None = None


class IntegrationService:
    def __init__(
        self,
        git: GitClient,
        *,
        integration_root: Path,
        verification_service=None,
        validator: PlanValidator | None = None,
    ) -> None:
        self.git = git
        self.integration_root = integration_root.resolve()
        self.verification_service = verification_service
        self.validator = validator or PlanValidator()
        self._workspaces: dict[str, Path] = {}

    def workspace_for(self, job_id: str) -> Path:
        return self._workspaces[job_id]

    async def _prepare_workspace(
        self,
        job_id: str,
        source_repo: Path,
        base_sha: str,
    ) -> tuple[str, Path]:
        slug = _slug(job_id)
        branch = f"orchestrator/{slug}/integration"
        workspace = (self.integration_root / f"{slug}-integration").resolve()
        if not workspace.is_relative_to(self.integration_root):
            raise ValueError("integration workspace escaped orchestrator root")
        await self.git.create_branch(source_repo, branch, base_sha)
        await self.git.create_worktree(source_repo, workspace, branch)
        self._workspaces[job_id] = workspace
        return branch, workspace

    async def integrate(
        self,
        job_id: str,
        source_repo: Path,
        base_sha: str,
        plan: TaskPlan,
        accepted_commits: dict[str, str],
    ) -> IntegrationResult:
        self.validator.validate(plan)
        branch, workspace = await self._prepare_workspace(job_id, source_repo, base_sha)
        integrated: list[str] = []
        order = self.validator.topological_order(plan)
        for task_id in order:
            sha = accepted_commits.get(task_id)
            if sha is None:
                continue
            try:
                await self.git.cherry_pick(workspace, sha)
            except GitCommandError:
                await self.git.abort_cherry_pick(workspace)
                return IntegrationResult(
                    status="conflict",
                    branch=branch,
                    head_sha=await self.git.head_sha(workspace),
                    integrated_task_ids=integrated,
                    conflicting_task_ids=[task_id],
                )
            integrated.append(task_id)

        verification = None
        if self.verification_service is not None:
            verification = await self.verification_service.verify_repository(job_id, workspace)
            if not verification.passed:
                return IntegrationResult(
                    status="verification_failed",
                    branch=branch,
                    head_sha=await self.git.head_sha(workspace),
                    integrated_task_ids=integrated,
                    verification=verification,
                )

        return IntegrationResult(
            status="succeeded",
            branch=branch,
            head_sha=await self.git.head_sha(workspace),
            integrated_task_ids=integrated,
            verification=verification,
        )
