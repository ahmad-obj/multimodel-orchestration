from __future__ import annotations

import json
from pathlib import Path

from orchestrator.domain.tasks import TaskPlan
from orchestrator.domain.workers import WorkerPermissions, WorkerRequest
from orchestrator.execution.structured import execute_structured
from orchestrator.managers.models import ManagerAction, ManagerDecision
from orchestrator.planning.validator import PlanValidator
from orchestrator.policies.cost import CostPolicy


class ManagerPolicyError(ValueError):
    pass


class ManagerSupervisor:
    def __init__(
        self,
        registry,
        *,
        validator: PlanValidator | None = None,
        cost_policy: CostPolicy | None = None,
    ) -> None:
        self.registry = registry
        self.validator = validator or PlanValidator()
        self.cost_policy = cost_policy or CostPolicy()

    def _validate_target_tasks(
        self,
        decision: ManagerDecision,
        current_plan: TaskPlan,
        completed_task_ids: set[str],
    ) -> None:
        plan_ids = {task.id for task in current_plan.subtasks}
        unknown = sorted(set(decision.task_ids) - plan_ids)
        if unknown:
            raise ManagerPolicyError(f"manager referenced unknown tasks: {', '.join(unknown)}")
        protected = sorted(set(decision.task_ids) & completed_task_ids)
        if protected and decision.action in {
            ManagerAction.REASSIGN,
            ManagerAction.CANCEL_SUBTASKS,
            ManagerAction.REJECT,
        }:
            raise ManagerPolicyError(
                f"manager cannot {decision.action.value} completed tasks: {', '.join(protected)}"
            )

    def _validate_worker_request(self, decision: ManagerDecision) -> None:
        if decision.requested_worker_id is None:
            return
        try:
            descriptor = self.registry.get(decision.requested_worker_id)
        except (KeyError, LookupError) as exc:
            raise ManagerPolicyError(
                f"manager requested unknown worker {decision.requested_worker_id}"
            ) from exc
        if not self.cost_policy.permits(descriptor.profile):
            raise ManagerPolicyError(
                f"manager requested paid worker {decision.requested_worker_id}; approval is required"
            )

    @staticmethod
    def _validate_new_subtask_policy(decision: ManagerDecision) -> None:
        forbidden = (
            "git push",
            "create pull request",
            "open pull request",
            "create pr",
            "open pr",
            "spawn agent",
            "spawn subagent",
            "create subagent",
        )
        for task in decision.new_subtasks:
            text = task.objective.casefold()
            if any(term in text for term in forbidden):
                raise ManagerPolicyError(
                    f"new subtask {task.id} requests an operation forbidden by V1 policy"
                )

    async def review_cycle(
        self,
        manager_worker_id: str,
        current_plan: TaskPlan,
        context: dict[str, object],
        repo_path: Path,
        *,
        completed_task_ids: set[str],
    ) -> tuple[ManagerDecision, TaskPlan | None]:
        manager = self.registry.get(manager_worker_id)
        if not manager.profile.can_manage:
            raise ManagerPolicyError(f"worker {manager_worker_id} is not manager-qualified")
        adapter = self.registry.adapters[manager.profile.harness]
        available_workers = [
            {
                "id": descriptor.profile.id,
                "harness": descriptor.profile.harness,
                "model": descriptor.profile.model,
                "capabilities": descriptor.profile.capabilities,
                "cost_class": descriptor.profile.cost_class.value,
                "can_modify_repo": descriptor.profile.can_modify_repo,
            }
            for descriptor in self.registry.available()
        ]
        compact_context = {
            "job_id": context.get("job_id"),
            "objective": context.get("objective"),
            "plan": current_plan.model_dump(mode="json"),
            "completed_task_ids": sorted(completed_task_ids),
            "state": context.get("state", {}),
            "verification": context.get("verification", {}),
            "failures": context.get("failures", {}),
            "available_workers": available_workers,
            "cost_policy": {"allow_paid": self.cost_policy.allow_paid},
        }
        request = WorkerRequest(
            job_id=str(context.get("job_id") or "manager-review"),
            task_id="manager-review",
            objective=(
                "Review the current job state and return exactly one structured manager decision. "
                "Do not execute tools, spawn workers, push Git changes, or bypass cost policy.\n\n"
                + json.dumps(compact_context, sort_keys=True, default=str)
            ),
            repo_path=repo_path,
            workspace_path=repo_path,
            read_only=True,
            permissions=WorkerPermissions(network_allowed=False, subagents_allowed=False),
        )
        _result, decision = await execute_structured(adapter, manager, request, ManagerDecision)
        self._validate_target_tasks(decision, current_plan, completed_task_ids)
        self._validate_worker_request(decision)
        self._validate_new_subtask_policy(decision)

        revised: TaskPlan | None = None
        if decision.action is ManagerAction.ADD_SUBTASKS:
            revised = current_plan.model_copy(
                update={"subtasks": [*current_plan.subtasks, *decision.new_subtasks]}
            )
            revised = self.validator.validate(revised)
        return decision, revised
