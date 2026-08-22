from pathlib import Path

from pydantic import BaseModel, Field

from orchestrator.capabilities.scoring import WorkerScorer
from orchestrator.domain.artifacts import ArtifactRef
from orchestrator.domain.common import CostClass
from orchestrator.domain.tasks import SubtaskSpec, TaskAnalysis, TaskComplexity, TaskPlan
from orchestrator.domain.workers import WorkerPermissions
from orchestrator.policies.cost import CostPolicy
from orchestrator.selection.filters import eligible_workers


class Assignment(BaseModel):
    job_id: str
    subtask: SubtaskSpec
    worker_id: str
    source_repo: Path
    relevant_artifacts: list[ArtifactRef] = Field(default_factory=list)
    permissions: WorkerPermissions = Field(default_factory=WorkerPermissions)


class Scheduler:
    def __init__(
        self,
        registry,
        scorer: WorkerScorer | None = None,
        cost_policy: CostPolicy | None = None,
    ) -> None:
        self.registry = registry
        self.scorer = scorer or WorkerScorer()
        self.cost_policy = cost_policy or CostPolicy()

    def ready_tasks(
        self,
        plan: TaskPlan,
        *,
        completed: set[str],
        running: set[str],
    ) -> list[SubtaskSpec]:
        return [
            task
            for task in plan.subtasks
            if task.id not in completed
            and task.id not in running
            and set(task.dependencies) <= completed
        ]

    def _analysis_for(self, task: SubtaskSpec) -> TaskAnalysis:
        return TaskAnalysis(
            task_type="subtask",
            complexity=TaskComplexity.MEDIUM,
            risk=task.risk,
            confidence=1.0,
            capability_weights=task.capability_weights,
            required_tools=task.required_tools,
            context_requirements=task.context_requirements,
            constraints=[],
            expected_outputs=task.expected_outputs,
            parallelizable_hint=task.preferred_parallel_group is not None,
        )

    def assign(
        self,
        job_id: str,
        subtask: SubtaskSpec,
        source_repo: Path,
        relevant_artifacts: list[ArtifactRef] | None = None,
        *,
        preferred_worker_id: str | None = None,
    ) -> Assignment:
        analysis = self._analysis_for(subtask)
        filtered = eligible_workers(
            self.registry.available(),
            analysis,
            self.cost_policy,
            for_manager=False,
            requires_write=not subtask.read_only,
        )
        scored = [(worker, self.scorer.score(worker.profile, analysis)) for worker in filtered.eligible]
        scored = [(worker, score) for worker, score in scored if score.adequate]
        if not scored:
            raise RuntimeError(f"no adequate worker for task {subtask.id}")

        if preferred_worker_id is not None:
            preferred = [
                (worker, score)
                for worker, score in scored
                if worker.profile.id == preferred_worker_id
            ]
            if preferred:
                worker_id = preferred[0][0].profile.id
            else:
                raise RuntimeError(
                    f"preferred worker {preferred_worker_id} is not eligible for task {subtask.id}"
                )
        else:
            cost_rank = {
                CostClass.FREE: 0,
                CostClass.INCLUDED: 1,
                CostClass.CHEAP: 2,
                CostClass.PAID: 3,
            }
            cheapest_rank = min(cost_rank[worker.profile.cost_class] for worker, _ in scored)
            cheapest = [
                (worker, score)
                for worker, score in scored
                if cost_rank[worker.profile.cost_class] == cheapest_rank
            ]
            cheapest.sort(key=lambda item: item[1].total, reverse=True)
            worker_id = cheapest[0][0].profile.id

        safe_prefixes = [
            "git status",
            "git diff",
            "git log",
            "git grep",
            "find ",
            "rg ",
            "grep ",
        ]
        if not subtask.read_only:
            safe_prefixes += [
                "pytest",
                "python -m pytest",
                "npm test",
                "pnpm test",
                "uv run",
                "ruff ",
            ]
        return Assignment(
            job_id=job_id,
            subtask=subtask,
            worker_id=worker_id,
            source_repo=source_repo,
            relevant_artifacts=relevant_artifacts or [],
            permissions=WorkerPermissions(
                network_allowed=False,
                subagents_allowed=False,
                allowed_shell_prefixes=safe_prefixes,
            ),
        )
