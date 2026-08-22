from typing import TypeVar

from pydantic import BaseModel

from orchestrator.domain.common import ExecutionStatus
from orchestrator.domain.results import WorkerResult
from orchestrator.domain.workers import WorkerDescriptor, WorkerRequest
from orchestrator.workers.base import WorkerAdapter

T = TypeVar("T", bound=BaseModel)


class StructuredExecutionError(RuntimeError):
    def __init__(self, result: WorkerResult):
        super().__init__(result.summary)
        self.result = result


async def execute_structured(adapter: WorkerAdapter, worker: WorkerDescriptor, request: WorkerRequest, output_model: type[T]) -> tuple[WorkerResult, T]:
    request = request.model_copy(update={"expected_output_schema": output_model.model_json_schema()})
    result = await adapter.execute(worker, request)
    if result.status is not ExecutionStatus.SUCCEEDED:
        raise StructuredExecutionError(result)
    return result, output_model.model_validate(result.structured_output)
