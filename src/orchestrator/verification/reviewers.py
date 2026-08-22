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
        repo_path: Path,
        manager_worker_id: str | None = None,
        cost_policy: CostPolicy | None = None,
    ) -> None:
        self.registry = registry
        self.repo_path = repo_path
        self.manager_worker_id = manager_worker_id
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

    def _select(self, kind: str, implementer_worker_id: str):
        if kind == "manager_review" and self.manager_worker_id is not None:
            manager = self.registry.get(self.manager_worker_id)
            if self.cost_policy.permits(manager.profile):
                return manager
            return None
        candidates = self._independent_candidates(implementer_worker_id)
        return candidates[0] if candidates else None

    async def review(
        self,
        *,
        kind: str,
        context: dict[str, object],
        implementer_worker_id: str,
    ) -> ReviewDecision | None:
        reviewer = self._select(kind, implementer_worker_id)
        if reviewer is None:
            return None
        adapter = self.registry.adapters[reviewer.profile.harness]
        request = WorkerRequest(
            job_id="verification-review",
            task_id=kind,
            objective=(
                "Review the supplied implementation evidence. Return a structured acceptance "
                "decision only. Do not modify the repository, spawn workers, or use network tools.\n\n"
                + json.dumps(context, sort_keys=True, default=str)
            ),
            repo_path=self.repo_path,
            workspace_path=self.repo_path,
            read_only=True,
            permissions=WorkerPermissions(network_allowed=False, subagents_allowed=False),
        )
        _result, decision = await execute_structured(
            adapter, reviewer, request, ReviewDecision
        )
        return decision
