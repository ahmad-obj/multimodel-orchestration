from orchestrator.domain.common import ExecutionStatus
from orchestrator.domain.events import EventType
from orchestrator.domain.results import WorkerResult


class AcceptedCommitStore:
    def __init__(self, attempt_repository, event_repository) -> None:
        self.attempt_repository = attempt_repository
        self.event_repository = event_repository

    async def for_job(self, job_id: str) -> dict[str, str]:
        events = await self.event_repository.list_for_job(job_id)
        accepted = {
            event.task_id
            for event in events
            if event.type is EventType.TASK_ACCEPTED and event.task_id is not None
        }
        attempts = await self.attempt_repository.list_for_job(job_id)
        commits: dict[str, str] = {}
        for attempt in attempts:
            if attempt.task_id not in accepted:
                continue
            if attempt.status is not ExecutionStatus.SUCCEEDED or not attempt.result_json:
                continue
            result = WorkerResult.model_validate_json(attempt.result_json)
            if result.local_commit:
                commits[attempt.task_id] = result.local_commit
        return commits
