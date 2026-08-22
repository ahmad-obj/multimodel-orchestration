import inspect
from collections.abc import Callable

from orchestrator.domain.events import OrchestratorEvent


class EventBus:
    def __init__(self, repository):
        self.repository = repository
        self._subscribers: list[Callable] = []

    def subscribe(self, callback: Callable) -> None:
        self._subscribers.append(callback)

    async def publish(self, event: OrchestratorEvent) -> None:
        await self.repository.append(event)
        for subscriber in list(self._subscribers):
            result = subscriber(event)
            if inspect.isawaitable(result):
                await result
