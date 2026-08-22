import json
from collections.abc import Awaitable, Callable

from orchestrator.domain.tasks import TaskAnalysis, TaskPlan
from orchestrator.domain.workers import WorkerDescriptor, WorkerRequest
from orchestrator.execution.structured import execute_structured


def _repo_summary_json(repository_summary: object) -> str:
    dump = getattr(repository_summary, "model_dump", None)
    data = dump(mode="json") if callable(dump) else repository_summary
    return json.dumps(data, default=str, sort_keys=True)


class TaskDecomposer:
    def __init__(self, adapters, executor: Callable[..., Awaitable] = execute_structured) -> None:
        self.adapters = adapters
        self.executor = executor

    async def create_plan(
        self,
        manager: WorkerDescriptor,
        objective: str,
        analysis: TaskAnalysis,
        repository_summary,
        *,
        repair_feedback: list[dict[str, object]] | None = None,
        previous_plan: TaskPlan | None = None,
    ) -> TaskPlan:
        prompt = (
            "Decompose this coding objective into a dependency-aware TaskPlan JSON. "
            "Use outcome-oriented subtasks; explicit dependency IDs; read_only flags; "
            "required tools/capabilities/context; write_paths for modifying tasks that "
            "may run in parallel; real parallel groups only; no worker IDs and no "
            "spawning. Report confidence and human_question only when material "
            "information is missing.\n"
            f"Objective: {objective}\n"
            f"Analysis: {json.dumps(analysis.model_dump(mode='json'), sort_keys=True)}\n"
            f"Repository summary: {_repo_summary_json(repository_summary)}"
        )
        if previous_plan is not None:
            prompt += f"\nPrevious invalid plan: {previous_plan.model_dump_json()}"
        if repair_feedback:
            prompt += (
                f"\nValidation errors to repair: {json.dumps(repair_feedback, sort_keys=True)}"
            )
        repo_path = getattr(repository_summary, "root", __import__("pathlib").Path.cwd())
        request = WorkerRequest(
            job_id="planning",
            task_id="decompose",
            objective=prompt,
            repo_path=repo_path,
            workspace_path=None,
            read_only=True,
            timeout_seconds=300,
        )
        adapter = self.adapters[manager.profile.harness]
        _, plan = await self.executor(adapter, manager, request, TaskPlan)
        return plan
