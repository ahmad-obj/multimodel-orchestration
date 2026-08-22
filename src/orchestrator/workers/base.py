from abc import ABC, abstractmethod

from orchestrator.domain.results import WorkerResult
from orchestrator.domain.workers import WorkerDescriptor, WorkerRequest


class WorkerAdapter(ABC):
    harness: str

    @abstractmethod
    async def discover(self) -> list[WorkerDescriptor]:
        raise NotImplementedError

    @abstractmethod
    async def health_check(self, worker: WorkerDescriptor) -> WorkerDescriptor:
        raise NotImplementedError

    @abstractmethod
    async def execute(self, worker: WorkerDescriptor, request: WorkerRequest) -> WorkerResult:
        raise NotImplementedError

    @abstractmethod
    async def cancel(self, execution_id: str) -> None:
        raise NotImplementedError
