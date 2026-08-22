from pathlib import Path

from pydantic import BaseModel

from orchestrator.domain.results import WorkerResult
from orchestrator.domain.workers import WorkerRequest
from orchestrator.selection.worker import WorkerSelection, WorkerSelector


class SingleTaskRun(BaseModel):
    selection: WorkerSelection
    result: WorkerResult


class SingleTaskService:
    def __init__(self, registry, adapters, analyzer, selector: WorkerSelector | None = None) -> None:
        self.registry = registry
        self.adapters = adapters
        self.analyzer = analyzer
        self.selector = selector or WorkerSelector()

    async def run(self, repo: Path, objective: str, *, repository_summary) -> SingleTaskRun:
        await self.registry.refresh()
        analysis = await self.analyzer.analyze(objective, repository_summary)
        selection = self.selector.select(analysis, self.registry.available(), requires_write=False)
        worker = selection.worker
        adapter = self.adapters[worker.profile.harness]
        request = WorkerRequest(
            job_id="single-task",
            task_id="single-task",
            objective=objective,
            repo_path=repo,
            workspace_path=None,
            read_only=True,
        )
        result = await adapter.execute(worker, request)
        return SingleTaskRun(selection=selection, result=result)
