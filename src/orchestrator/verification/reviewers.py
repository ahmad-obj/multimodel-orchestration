from __future__ import annotations

import json
from pathlib import Path

from orchestrator.domain.workers import WorkerPermissions, WorkerRequest
from orchestrator.execution.structured import execute_structured
from orchestrator.policies.cost import CostPolicy
from orchestrator.verification.models import ReviewDecision


class StructuredReviewProvider:
    def __init__(
        self,
        registry,
        *,
        repo_path: Path | None,
        manager_worker_id: str | None = None,
        job_repository=None,
        cost_policy: CostPolicy | None = None,
    ) -> None:
        self.registry = registry
        self.repo_path = repo_path
        self.manager_worker_id = manager_worker_id
        self.job_repository = job_repository
        self.cost_policy = cost_policy or CostPolicy()

    def _independent_candidates(self, implementer_worker_id: str):
        candidates = []
        for descriptor in self.registry.available():
            profile = descriptor.profile
            if profile.id == implementer_worker_id:
                continue
            if not self.cost_policy.permits(profile):
                continue
            score = (
                0.45 * profile.capabilities.get("reasoning", 0.0)
                + 0.35 * profile.capabilities.get("testing", 0.0)
                + 0.20 * profile.reliability
            )
            candidates.append((score, descriptor))
        candidates.sort(key=lambda item: item[0], reverse=True)
        return [descriptor for _score, descriptor in candidates]

    async def _manager_id_for(self, context: dict[str, object]) -> str | None:
        if self.manager_worker_id is not None:
            return self.manager_worker_id
        if self.job_repository is None:
            return None
        job_id = context.get("job_id")
        if not isinstance(job_id, str) or not job_id:
            return None
        job = await self.job_repository.get(job_id)
        return None if job is None else job.manager_worker_id

    async def _select(
        self,
        kind: str,
        implementer_worker_id: str,
        context: dict[str, object],
    ):
        if kind == "manager_review":
            manager_id = await self._manager_id_for(context)
            if manager_id is not None:
                manager = self.registry.get(manager_id)
                if self.cost_policy.permits(manager.profile):
                    return manager
                return None
        candidates = self._independent_candidates(implementer_worker_id)
        return candidates[0] if candidates else None

    def _repo_for(self, context: dict[str, object]) -> Path:
        workspace = context.get("workspace")
        if isinstance(workspace, str) and workspace:
            return Path(workspace)
        if self.repo_path is not None:
            return self.repo_path
        return Path.cwd()

    async def review(
        self,
        *,
        kind: str,
        context: dict[str, object],
        implementer_worker_id: str,
    ) -> ReviewDecision | None:
        reviewer = await self._select(kind, implementer_worker_id, context)
        if reviewer is None:
            return None
        adapter = self.registry.adapters[reviewer.profile.harness]
        repo_path = self._repo_for(context)
        request = WorkerRequest(
            job_id=str(context.get("job_id") or "verification-review"),
            task_id=kind,
            objective=(
                "Review the supplied implementation evidence. Return a structured "
                "acceptance decision only. Do not modify the repository, spawn workers, "
                "or use network tools.\n\n" + json.dumps(context, sort_keys=True, default=str)
            ),
            repo_path=repo_path,
            workspace_path=repo_path,
            read_only=True,
            permissions=WorkerPermissions(network_allowed=False, subagents_allowed=False),
        )
        _result, decision = await execute_structured(adapter, reviewer, request, ReviewDecision)
        return decision
