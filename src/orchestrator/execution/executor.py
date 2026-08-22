import asyncio

from orchestrator.domain.common import ExecutionStatus
from orchestrator.domain.events import EventType, OrchestratorEvent
from orchestrator.domain.workers import WorkerRequest
from orchestrator.scheduling.scheduler import Assignment


class TaskExecutor:
    def __init__(
        self,
        registry,
        *,
        artifact_store=None,
        attempt_repository=None,
        artifact_repository=None,
        cost_repository=None,
        event_bus=None,
        worktree_manager=None,
        git_client=None,
    ) -> None:
        self.registry = registry
        self.artifact_store = artifact_store
        self.attempt_repository = attempt_repository
        self.artifact_repository = artifact_repository
        self.cost_repository = cost_repository
        self.event_bus = event_bus
        self.worktree_manager = worktree_manager
        self.git_client = git_client
        self._semaphores: dict[str, asyncio.Semaphore] = {}

    def _semaphore(self, worker_id: str) -> asyncio.Semaphore:
        if worker_id not in self._semaphores:
            capacity = self.registry.get(worker_id).profile.parallel_capacity
            self._semaphores[worker_id] = asyncio.Semaphore(capacity)
        return self._semaphores[worker_id]

    async def _publish(self, event: OrchestratorEvent) -> None:
        if self.event_bus is not None:
            await self.event_bus.publish(event)

    async def execute_assignment(self, assignment: Assignment):
        worker = self.registry.get(assignment.worker_id)
        adapter = self.registry.adapters[worker.profile.harness]
        lease = None
        if assignment.subtask.read_only:
            workspace = assignment.source_repo
        else:
            if self.worktree_manager is None or self.git_client is None:
                raise RuntimeError("modifying assignments require worktree_manager and git_client")
            lease = await self.worktree_manager.acquire(
                assignment.job_id,
                assignment.subtask.id,
                assignment.worker_id,
                assignment.source_repo,
            )
            workspace = lease.path

        request = WorkerRequest(
            job_id=assignment.job_id,
            task_id=assignment.subtask.id,
            objective=assignment.subtask.objective,
            repo_path=assignment.source_repo,
            workspace_path=workspace,
            read_only=assignment.subtask.read_only,
            permissions=assignment.permissions,
            relevant_artifacts=assignment.relevant_artifacts,
        )
        async with self._semaphore(assignment.worker_id):
            await self._publish(
                OrchestratorEvent(
                    type=EventType.WORKER_STARTED,
                    job_id=assignment.job_id,
                    task_id=assignment.subtask.id,
                    worker_id=assignment.worker_id,
                )
            )
            result = await adapter.execute(worker, request)
            if (
                lease is not None
                and result.status is ExecutionStatus.SUCCEEDED
                and result.local_commit is None
                and await self.git_client.status_porcelain(lease.path)
            ):
                commit = await self.git_client.commit_all(
                    lease.path,
                    f"orchestrator: complete {assignment.subtask.id} with {assignment.worker_id}",
                )
                result = result.model_copy(update={"local_commit": commit})

            event_type = (
                EventType.WORKER_COMPLETED
                if result.status is ExecutionStatus.SUCCEEDED
                else EventType.WORKER_FAILED
            )
            await self._publish(
                OrchestratorEvent(
                    type=event_type,
                    job_id=assignment.job_id,
                    task_id=assignment.subtask.id,
                    worker_id=assignment.worker_id,
                    payload={"confidence": result.confidence, "status": result.status.value},
                )
            )
            if self.cost_repository is not None and result.usage:
                await self.cost_repository.record(
                    assignment.job_id,
                    assignment.subtask.id,
                    assignment.worker_id,
                    result.model_dump_json(),
                )
            return result

    async def execute_many(self, assignments: list[Assignment]):
        return list(await asyncio.gather(*(self.execute_assignment(a) for a in assignments)))
